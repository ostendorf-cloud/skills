#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a `gh pr create`, `gh pr edit`, `gh pr comment`,
`gh pr review`, `gh issue create`, `gh issue edit`, `gh issue comment` or `gh api`
call that writes an attribution trailer, a generated-by marker at the start of a
line, or a link to Claude or Anthropic, outside the allowed documentation hosts,
into the tracker.
"""

import os
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

PR_SUBCOMMANDS = frozenset({"create", "edit", "comment", "review"})
ISSUE_SUBCOMMANDS = frozenset({"create", "edit", "comment"})
LEADING_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")

BODY_LONG = ("--body",)
BODY_SHORT = ("-b",)
BODY_FILE_LONG = ("--body-file",)
BODY_FILE_SHORT = ("-F",)
API_FIELD_LONG = ("--field", "--raw-field")
API_FIELD_SHORT = ("-f", "-F")
API_INPUT_LONG = ("--input",)

STDIN_MARKERS = ("-", "/dev/stdin")

TRAILER = re.compile(r"co-authored-by:", re.IGNORECASE)
GENERATED_WITH = re.compile(r"(?m:^[^\w\n]*Generated with\b)")
DOMAIN_LINK = re.compile(r"(?i)\b((?:[a-z0-9-]+\.)*(?:claude\.com|claude\.ai|anthropic\.com))\b")
ALLOWED_DOC_HOSTS = {
    "docs.claude.com",
    "code.claude.com",
    "platform.claude.com",
    "docs.anthropic.com",
}

REASON = (
    "This writes an attribution line, a generated-by marker or a link to Claude or "
    "Anthropic into the tracker. The baseline forbids attribution lines, session links "
    "or tool names in commits, pull requests and comments."
)


def carries_forbidden_text(text: str) -> bool:
    """Whether text holds an attribution trailer, a generated-by marker at the start
    of a line, or a Claude or Anthropic link outside the allowed documentation hosts.

    Matches run on the text with its fenced blocks and inline code spans stripped, so
    a quotation of the pattern inside a span or a fence is not denied.
    """
    text = _common.strip_code(text)
    if TRAILER.search(text):
        return True
    if GENERATED_WITH.search(text):
        return True
    for match in DOMAIN_LINK.finditer(text):
        if match.group(1).lower() not in ALLOWED_DOC_HOSTS:
            return True
    return False


def flag_values(
    tokens: list[str], long_flags: tuple[str, ...], short_flags: tuple[str, ...]
) -> list[str]:
    """Every value passed to one of long_flags or short_flags in tokens, in order.

    Handles the spaced form (`--flag value`, `-f value`), `--flag=value`, and the
    attached shorthand gh's pflag also accepts: `-fvalue` and `-f=value` work the
    same as `-f value`.
    """
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        matched = False

        for flag in long_flags:
            if token == flag:
                if index + 1 < len(tokens):
                    values.append(tokens[index + 1])
                index += 2
                matched = True
                break
            prefix = flag + "="
            if token.startswith(prefix):
                values.append(token[len(prefix) :])
                index += 1
                matched = True
                break
        if matched:
            continue

        for flag in short_flags:
            if token == flag:
                if index + 1 < len(tokens):
                    values.append(tokens[index + 1])
                index += 2
                matched = True
                break
            if token.startswith(flag) and len(token) > len(flag):
                rest = token[len(flag) :]
                values.append(rest[1:] if rest.startswith("=") else rest)
                index += 1
                matched = True
                break
        if matched:
            continue

        index += 1
    return values


def read_body_file(path: str, cwd: Optional[str]) -> Optional[str]:
    """The content of a file path, or None when it cannot be read.

    The stdin markers "-" and "/dev/stdin" are handled by the caller instead, which
    falls back to scanning the whole raw command text.
    """
    full_path = path if os.path.isabs(path) else os.path.join(cwd or "", path)
    try:
        with open(full_path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def file_or_stdin_texts(paths: list[str], full_command: str, cwd: Optional[str]) -> list[str]:
    """The readable text for every path in paths, with the stdin fallback applied."""
    texts: list[str] = []
    for path in paths:
        if path in STDIN_MARKERS:
            texts.append(full_command)
            continue
        content = read_body_file(path, cwd)
        if content:
            texts.append(content)
    return texts


def tracker_text(tokens: list[str], full_command: str, cwd: Optional[str]) -> str:
    """All text a `gh pr` or `gh issue` call would write, from --body/-b and
    --body-file/-F. A body file read from stdin cannot be read here, so the whole
    raw command text is scanned instead, which still catches a piped value such as
    `printf '...' | gh pr comment 1 --body-file -`.
    """
    texts = flag_values(tokens, BODY_LONG, BODY_SHORT)
    file_paths = flag_values(tokens, BODY_FILE_LONG, BODY_FILE_SHORT)
    texts.extend(file_or_stdin_texts(file_paths, full_command, cwd))
    return "\n\n".join(texts)


def api_text(tokens: list[str], full_command: str, cwd: Optional[str]) -> str:
    """All text a `gh api` call would write to the field named "body", from
    -f/--field/--raw-field key=value pairs and --input, with the same stdin
    fallback as tracker_text.
    """
    texts: list[str] = []
    for value in flag_values(tokens, API_FIELD_LONG, API_FIELD_SHORT):
        key, separator, rest = value.partition("=")
        if separator and key == "body":
            texts.append(rest)
    file_paths = flag_values(tokens, API_INPUT_LONG, ())
    texts.extend(file_or_stdin_texts(file_paths, full_command, cwd))
    return "\n\n".join(texts)


def strip_leading_assignments(part: str) -> str:
    """Removes leading `VAR=value` environment assignments from part.

    Unlike `_common.strip_env_prefix`, this keeps the whitespace of everything after
    the assignments untouched, including a newline inside a quoted body a later
    `shlex.split` needs to see.
    """
    while True:
        match = LEADING_ASSIGNMENT.match(part)
        if not match:
            return part
        part = part[match.end() :]


def command_text(raw_part: str, full_command: str, cwd: Optional[str]) -> Optional[str]:
    """The text a matched `gh` part would write to the tracker, or None when the
    part does not match a covered subcommand or cannot be parsed as shell words.

    The subcommand is found through `_common.gh_dispatch`, so a flag in front of the
    noun does not hide it: `gh --hostname example.com pr create --body ...` and `gh
    --method POST api repos/o/r/issues -f body=...` write to the tracker just as the
    plain forms do. The flag value scans below read the whole token list, so they need
    no dispatch awareness of their own.

    `_common.command_name` has already established that the part runs a binary named
    gh, so the first token is replaced by the plain name for the dispatch walk, which
    keeps the absolute path form `/usr/local/bin/gh pr create` covered.
    """
    matching_part = _common.strip_env_prefix(raw_part)
    if _common.command_name(matching_part) != "gh":
        return None

    try:
        shell_tokens = shlex.split(strip_leading_assignments(raw_part))
    except ValueError:
        return None
    if not shell_tokens:
        return None

    dispatch = _common.gh_dispatch(["gh"] + shell_tokens[1:])
    if not dispatch:
        return None
    noun = dispatch[0]
    sub = _common.subcommand_after(dispatch[1:], space_form_takes_value=True)

    if noun == "pr" and sub in PR_SUBCOMMANDS:
        return tracker_text(shell_tokens, full_command, cwd)
    if noun == "issue" and sub in ISSUE_SUBCOMMANDS:
        return tracker_text(shell_tokens, full_command, cwd)
    if noun == "api":
        return api_text(shell_tokens, full_command, cwd)
    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()

    for raw_part in _common.command_parts(command):
        if _common.command_name(_common.strip_env_prefix(raw_part)) != "gh":
            continue

        # Runs before command_text, which cannot tell "does not parse" from "does not
        # match" and returns None for both, so an unparseable gh part would otherwise
        # reach the tracker unexamined.
        malformed = _common.malformed_quoting_violation(strip_leading_assignments(raw_part))
        if malformed:
            return _common.deny(EVENT, malformed)

        text = command_text(raw_part, command, cwd)
        if text and carries_forbidden_text(text):
            return _common.deny(EVENT, REASON)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
