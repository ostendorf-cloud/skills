#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a write-up of a finding in a public repository: the
title, label or text of a `gh issue create|edit|comment`, `gh pr create|edit|comment|review`,
a `gh api` write to an issue, pull request or comment, or a `git commit` message, when it
carries the finding vocabulary (the VOCABULARY table below, plus the `security` label).

Design: a sibling of tracker_body.py, not an extension. tracker_body.py is about
attribution only and the two rules change for different reasons, so each hook keeps one
purpose. The command splitting, wrapper stripping and flag value helpers are imported
from tracker_body.py and commit_message.py unchanged, so their behaviour stays as tested.

The repository is public unless the lookup says otherwise. The target comes from
`--repo`/`-R`, the endpoint of a `gh api` call, or the git remote `origin` of the working
directory. The lookup runs only after a vocabulary match, `gh repo view <slug> --json
isPrivate`, with a short timeout, and the answer is cached per repository in a file under
$TMPDIR for the session. An unreadable or failed answer counts as public: that is the
documented fail closed case, not an internal error. An internal error in the hook itself
still prints `{}`.

Tests replace the lookup through the environment variable AGENT_SKILLS_VISIBILITY_CMD, an
executable called with the slug that prints `true` or `false`. No test uses the network.

A repository opts out of words in `.agent-skills.json`, read from the repository root of
the working directory: `{"publicFindings": {"allowWords": ["alert"]}}`. The entries are
names from VOCABULARY or the label name `security`.

A message or body file is read only from the session scratch scope ($TMPDIR) or below the
working directory. Any other path, or a file that cannot be read, counts as unreadable and
is allowed. Standard input falls back to scanning the raw command text, as in tracker_body.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402
import commit_message  # noqa: E402
import tracker_body  # noqa: E402

EVENT = "PreToolUse"

VISIBILITY_CMD_ENV = "AGENT_SKILLS_VISIBILITY_CMD"
LOOKUP_TIMEOUT = 5
CACHE_NAME = "agent-skills-public-findings.json"

SECURITY_LABEL = "security"

VOCABULARY = {
    "cve": re.compile(r"CVE-\d", re.IGNORECASE),
    "codeql": re.compile(r"CodeQL", re.IGNORECASE),
    "code scanning": re.compile(r"code\s+scanning", re.IGNORECASE),
    "alert": re.compile(r"alert\s*#?\d", re.IGNORECASE),
    "vulnerab": re.compile(r"vulnerab", re.IGNORECASE),
    "exploit": re.compile(r"exploit", re.IGNORECASE),
    "injection": re.compile(r"injection", re.IGNORECASE),
    "xss": re.compile(r"\bXSS\b", re.IGNORECASE),
    "ssrf": re.compile(r"\bSSRF\b", re.IGNORECASE),
    "path traversal": re.compile(r"path\s+traversal", re.IGNORECASE),
    "sanitiz": re.compile(r"sanitiz", re.IGNORECASE),
    "ghsa": re.compile(r"GHSA-", re.IGNORECASE),
}

PR_SUBCOMMANDS = frozenset({"create", "edit", "comment", "review"})
ISSUE_SUBCOMMANDS = frozenset({"create", "edit", "comment"})

TITLE_FLAGS = (("--title",), ("-t",))
LABEL_FLAGS = (("--label", "--add-label"), ("-l",))
METHOD_FLAGS = (("--method",), ("-X",))
REPO_FLAGS = (("--repo",), ("-R",))

API_VALUE_FLAGS = frozenset(
    {
        "-X",
        "--method",
        "-f",
        "-F",
        "--field",
        "--raw-field",
        "-H",
        "--header",
        "--input",
        "--jq",
        "-q",
        "--template",
        "-t",
        "--hostname",
        "--cache",
        "-p",
        "--preview",
    }
)
API_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT"})
API_TRACKER_ENDPOINT = re.compile(r"(?:^|/)(?:issues|pulls|comments|reviews)(?:/|$)")
API_TEXT_KEYS = frozenset({"title", "body", "labels", "labels[]"})
API_ENDPOINT_REPO = re.compile(r"^/?repos/([^/\s]+)/([^/\s]+)")
REMOTE_SLUG = re.compile(r"[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$")

REASON = (
    "A public repository gets no write-up of a finding before the fix is merged. "
    'Use a draft security advisory, or a plain title and body such as "resolve static '
    'analysis findings" with no finding detail.'
)


def allowed_words(directory: Optional[str]) -> frozenset[str]:
    """The words the repository of directory opts out of, lower case. Empty when the
    config is absent, invalid or names no list."""
    config = _common.agent_skills_config(_common.repo_root(directory))
    section = config.get("publicFindings")
    if not isinstance(section, dict):
        return frozenset()
    words = section.get("allowWords")
    if not isinstance(words, list):
        return frozenset()
    return frozenset(word.strip().lower() for word in words if isinstance(word, str))


def finding_words(texts: list[str], labels: list[str], allow: frozenset[str]) -> list[str]:
    """The vocabulary names that texts or labels match and allow does not opt out of."""
    found: list[str] = []
    if SECURITY_LABEL not in allow:
        for label in labels:
            for item in label.split(","):
                if item.strip().lower() == SECURITY_LABEL:
                    found.append(SECURITY_LABEL)
    for name, pattern in VOCABULARY.items():
        if name in allow:
            continue
        if any(pattern.search(text) for text in texts):
            found.append(name)
    return found


def readable_path(path: str, cwd: Optional[str]) -> Optional[str]:
    """The resolved path when it lies in the session scratch scope or below cwd, else
    None. The hook never reads a file elsewhere on behalf of a command."""
    full = path if os.path.isabs(path) else os.path.join(cwd or "", path)
    real = os.path.realpath(full)
    roots = list(_common.scratch_roots())
    if cwd:
        roots.append(os.path.realpath(cwd))
    for root in roots:
        try:
            if os.path.commonpath([root, real]) == root:
                return real
        except ValueError:
            continue
    return None


def read_text(path: str, cwd: Optional[str]) -> Optional[str]:
    """The content of path, or None when it is out of scope or cannot be read."""
    real = readable_path(path, cwd)
    if real is None:
        return None
    try:
        with open(real, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def file_texts(paths: list[str], full_command: str, cwd: Optional[str]) -> list[str]:
    """The readable text of every path, with the stdin fallback of tracker_body."""
    texts: list[str] = []
    for path in paths:
        if path in tracker_body.STDIN_MARKERS:
            texts.append(full_command)
            continue
        content = read_text(path, cwd)
        if content:
            texts.append(content)
    return texts


def values_of(tokens: list[str], flags: tuple[tuple[str, ...], tuple[str, ...]]) -> list[str]:
    """Every value of a long and short flag group, see tracker_body.flag_values."""
    return tracker_body.flag_values(tokens, flags[0], flags[1])


def slug_from_remote(directory: Optional[str]) -> str:
    """owner/name from the origin remote of directory, "" when unknown."""
    url = _common.run_git(["remote", "get-url", "origin"], directory)
    if not url:
        return ""
    match = REMOTE_SLUG.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def cache_path() -> str:
    """The per session cache file, under $TMPDIR."""
    return os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), CACHE_NAME)


def read_cache() -> dict[str, Any]:
    """The cached answers by repository, {} when there is no readable cache."""
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_cache(slug: str, private: bool) -> None:
    """Remembers the answer for slug. A cache that cannot be written is skipped."""
    data = read_cache()
    data[slug] = private
    try:
        with open(cache_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        pass


def lookup_private(slug: str) -> Optional[bool]:
    """Whether the repository is private, None when the answer cannot be read."""
    override = os.environ.get(VISIBILITY_CMD_ENV)
    if override:
        command = [override, slug]
    else:
        command = ["gh", "repo", "view", slug, "--json", "isPrivate", "--jq", ".isPrivate"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT, check=False
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    answer = result.stdout.strip().lower()
    if answer == "true":
        return True
    if answer == "false":
        return False
    return None


def is_private(slug: str) -> bool:
    """Whether the repository is known to be private. Unknown counts as public."""
    if not slug:
        return False
    cached = read_cache().get(slug)
    if isinstance(cached, bool):
        return cached
    answer = lookup_private(slug)
    if answer is None:
        return False
    write_cache(slug, answer)
    return answer


def gh_write(part: str, full_command: str, cwd: Optional[str]) -> Optional[tuple]:
    """(texts, labels, repo slug) a matched `gh` part would write, None when the part is
    not a covered write or does not parse. Expects wrapper prefixes already removed."""
    if _common.command_name(part) != "gh":
        return None
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None
    dispatch = _common.gh_dispatch(["gh"] + tokens[1:])
    if not dispatch:
        return None
    noun = dispatch[0]
    sub = _common.subcommand_after(dispatch[1:], space_form_takes_value=True)
    repo = (values_of(tokens, REPO_FLAGS) or [""])[-1]

    if (noun == "pr" and sub in PR_SUBCOMMANDS) or (noun == "issue" and sub in ISSUE_SUBCOMMANDS):
        texts = values_of(tokens, TITLE_FLAGS)
        texts.extend(tracker_body.flag_values(tokens, ("--body",), ("-b",)))
        paths = tracker_body.flag_values(tokens, ("--body-file",), ("-F",))
        texts.extend(file_texts(paths, full_command, cwd))
        return texts, values_of(tokens, LABEL_FLAGS), repo

    if noun == "api":
        return api_write(tokens, dispatch, full_command, cwd, repo)
    return None


def api_write(
    tokens: list[str], dispatch: list[str], full_command: str, cwd: Optional[str], repo: str
) -> Optional[tuple]:
    """The same triple for a `gh api` call that writes to an issue, pull request or
    comment. A call with fields and no method is a POST, as gh itself treats it."""
    operands = _common.subcommand_tokens(dispatch[1:], API_VALUE_FLAGS)
    endpoint = operands[0] if operands else ""
    if not API_TRACKER_ENDPOINT.search(endpoint.split("?", 1)[0]):
        return None

    fields = tracker_body.flag_values(tokens, ("--field", "--raw-field"), ("-f", "-F"))
    inputs = tracker_body.flag_values(tokens, ("--input",), ())
    methods = [value.upper() for value in values_of(tokens, METHOD_FLAGS)]
    if methods:
        if methods[-1] not in API_WRITE_METHODS:
            return None
    elif not fields and not inputs:
        return None

    texts: list[str] = []
    labels: list[str] = []
    for value in fields:
        key, separator, rest = value.partition("=")
        if not separator or key not in API_TEXT_KEYS:
            continue
        if rest.startswith("@") and len(rest) > 1:
            texts.extend(file_texts([rest[1:]], full_command, cwd))
        elif key.startswith("labels"):
            labels.append(rest)
        else:
            texts.append(rest)
    texts.extend(file_texts(inputs, full_command, cwd))

    match = API_ENDPOINT_REPO.match(endpoint)
    slug = f"{match.group(1)}/{match.group(2)}" if match else repo
    return texts, labels, slug


def commit_text(command: str, cwd: Optional[str]) -> Optional[str]:
    """The message a `git commit` command would write, None when it carries none or
    the message file is unreadable."""
    heredoc = commit_message.HEREDOC_MESSAGE.search(command)
    if heredoc:
        return heredoc.group(2)
    file_match = commit_message.FILE_FLAG.search(command)
    if file_match:
        path = file_match.group(1).strip("'\"")
        return None if path == "-" else read_text(path, cwd)
    values = commit_message.extract_messages(command)
    return "\n\n".join(values) if values else None


def deny_for(texts: list[str], labels: list[str], slug: str, directory: Optional[str]) -> bool:
    """Whether the write is a finding write-up in a public repository."""
    if not finding_words(texts, labels, frozenset()):
        return False
    found = finding_words(texts, labels, allowed_words(directory))
    return bool(found) and not is_private(slug)


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()
    cwd = payload.get("cwd") or os.getcwd()

    for raw_part, directory in _common.part_dirs(command, cwd):
        part = _common.strip_wrappers(raw_part)
        where = directory or cwd

        if _common.command_name(part) == "gh":
            write = gh_write(part, command, where)
            if write is None:
                continue
            texts, labels, repo = write
            slug = repo or slug_from_remote(where)
            if deny_for(texts, labels, slug, where):
                return _common.deny(EVENT, REASON)
            continue

        normalized = _common.normalize_command_part(raw_part)
        stripped, path = _common.strip_global_git_options(normalized)
        if not stripped.startswith("git commit"):
            continue
        commit_dir = _common.git_part_dir(raw_part, directory, path)
        if _common.in_scratch(commit_dir):
            continue
        if "--amend" in command and not commit_message.MESSAGE_SOURCE.search(command):
            continue
        where = path or where
        message = commit_text(command, where)
        if message is None:
            continue
        if deny_for([message], [], slug_from_remote(where), where):
            return _common.deny(EVENT, REASON)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
