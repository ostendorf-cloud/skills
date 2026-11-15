#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a `git commit` whose subject is not a Conventional
Commit, whose subject exceeds 72 characters, or whose message carries an attribution
trailer, a generated-by marker at the start of a line, or a link to Claude or
Anthropic outside the allowed documentation hosts.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

HEADER = re.compile(
    r"^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)"
    r"(\([a-z0-9._/-]+\))?!?: .+$"
)
SUBJECT_LIMIT = 72

MESSAGE_SOURCE = re.compile(r"(?:^|\s)(-m\b|--message\b|-F\b|--file\b)")

TRAILER = re.compile(r"co-authored-by:", re.IGNORECASE)
GENERATED_WITH = re.compile(r"(?m:^[^\w\n]*Generated with\b)")
DOMAIN_LINK = re.compile(r"(?i)\b((?:[a-z0-9-]+\.)*(?:claude\.com|claude\.ai|anthropic\.com))\b")
ALLOWED_DOC_HOSTS = {
    "docs.claude.com",
    "code.claude.com",
    "platform.claude.com",
    "docs.anthropic.com",
}

HEREDOC_MESSAGE = re.compile(r"<<[-~]?['\"]?(\w+)['\"]?\s*\n(.*?)\n\1", re.DOTALL)
MESSAGE_FLAG = re.compile(r"(?:^|\s)(?:-m|--message=?)\s*(['\"])(.*?)(?<!\\)\1", re.DOTALL)
MESSAGE_FLAG_BARE = re.compile(r"(?:^|\s)-m\s+([^\s'\"]+)")
FILE_FLAG = re.compile(r"(?:^|\s)(?:-F|--file)(?:\s+|=)(\S+)")

FORMAT_HINT = (
    "Use type(scope)!: subject, with type one of feat, fix, chore, docs, style, "
    "refactor, perf, test, build, ci, revert, at most 72 characters. This applies "
    "inside a repository, not in a fixture under the session scratch directory."
)


def extract_messages(command: str) -> list[str]:
    """Every -m/--message value in command, in the order they appear."""
    matches: list[tuple[int, str]] = []
    for match in MESSAGE_FLAG.finditer(command):
        matches.append((match.start(), match.group(2)))
    for match in MESSAGE_FLAG_BARE.finditer(command):
        matches.append((match.start(), match.group(1)))
    matches.sort(key=lambda item: item[0])
    return [value for _, value in matches]


def extract_message(command: str, cwd: Optional[str]) -> Optional[str]:
    """The commit message the command would write, or None when it carries none.

    Every -m/--message value is concatenated in order: the first is the subject, the
    rest become the body, the same way git itself joins multiple -m flags.
    """
    heredoc = HEREDOC_MESSAGE.search(command)
    if heredoc:
        return heredoc.group(2)

    file_match = FILE_FLAG.search(command)
    if file_match:
        file_path = file_match.group(1).strip("'\"")
        if file_path == "-":
            return None
        path = file_path if os.path.isabs(file_path) else os.path.join(cwd or "", file_path)
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return None

    values = extract_messages(command)
    if not values:
        return None
    return "\n\n".join(values)


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


def message_violation(message: str) -> Optional[str]:
    """The deny reason for a commit message, or None when it is fine."""
    lines = message.strip("\n").splitlines()
    if not lines:
        return None

    subject = lines[0]

    if len(subject) > SUBJECT_LIMIT or not HEADER.match(subject):
        return f"Commit subject {subject!r} is not a Conventional Commit. {FORMAT_HINT}"

    if carries_forbidden_text(message):
        return (
            "Commit message carries an attribution line, a generated-by marker or a link "
            "to Claude or Anthropic. The baseline forbids attribution lines, session links "
            "or tool names in commits, pull requests and comments. This applies inside a "
            "repository."
        )

    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or os.getcwd()

    git_path: Optional[str] = None
    is_commit = False
    commit_dir: Optional[str] = None
    for raw_part, directory in _common.part_dirs(command, cwd):
        part = _common.normalize_command_part(raw_part)
        normalized, path = _common.strip_global_git_options(part)
        if normalized.startswith("git commit") or normalized == "git commit":
            is_commit = True
            git_path = path
            commit_dir = _common.git_part_dir(raw_part, directory, path)
            break

    if not is_commit:
        return _common.emit_empty()

    # A commit in a throwaway fixture repository under the session scratch directory or
    # $TMPDIR is outside this check. A commit in a real repository is checked as before.
    if _common.in_scratch(commit_dir):
        return _common.emit_empty()

    if "--amend" in command and not MESSAGE_SOURCE.search(command):
        return _common.emit_empty()

    message = extract_message(command, git_path or cwd)
    if message is None:
        return _common.emit_empty()

    reason = message_violation(message)
    if reason:
        return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
