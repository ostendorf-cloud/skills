#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a `git commit` whose subject is not a Conventional
Commit, whose subject exceeds 72 characters, or whose body carries an attribution line
or a generated-by marker.
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
FORBIDDEN_BODY = re.compile(
    r"co-authored-by:|generated with|claude\.ai|anthropic\.com", re.IGNORECASE
)

HEREDOC_MESSAGE = re.compile(r"<<[-~]?['\"]?(\w+)['\"]?\s*\n(.*?)\n\1", re.DOTALL)
MESSAGE_FLAG = re.compile(r"(?:^|\s)(?:-m|--message=?)\s*(['\"])(.*?)(?<!\\)\1", re.DOTALL)
MESSAGE_FLAG_BARE = re.compile(r"(?:^|\s)-m\s+([^\s'\"]+)")
FILE_FLAG = re.compile(r"(?:^|\s)(?:-F|--file)(?:\s+|=)(\S+)")

FORMAT_HINT = (
    "Use type(scope)!: subject, with type one of feat, fix, chore, docs, style, "
    "refactor, perf, test, build, ci, revert, at most 72 characters."
)


def extract_message(command: str, cwd: Optional[str]) -> Optional[str]:
    """The commit message the command would write, or None when it carries none."""
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

    flag = MESSAGE_FLAG.search(command)
    if flag:
        return flag.group(2)

    bare = MESSAGE_FLAG_BARE.search(command)
    if bare:
        return bare.group(1)

    return None


def message_violation(message: str) -> Optional[str]:
    """The deny reason for a commit message, or None when it is fine."""
    lines = message.strip("\n").splitlines()
    if not lines:
        return None

    subject = lines[0]
    body = "\n".join(lines[1:])

    if len(subject) > SUBJECT_LIMIT or not HEADER.match(subject):
        return f"Commit subject {subject!r} is not a Conventional Commit. {FORMAT_HINT}"

    if FORBIDDEN_BODY.search(body):
        return (
            "Commit body carries an attribution line or a generated-by marker. Drop it, "
            "commits read as human work."
        )

    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""

    if not any(
        part.startswith("git commit") or part == "git commit"
        for part in (_common.strip_env_prefix(p) for p in _common.command_parts(command))
    ):
        return _common.emit_empty()

    if "--amend" in command and not MESSAGE_SOURCE.search(command):
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    message = extract_message(command, cwd)
    if message is None:
        return _common.emit_empty()

    reason = message_violation(message)
    if reason:
        return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(main())
