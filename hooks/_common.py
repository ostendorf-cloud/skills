# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the skills repository hooks.

Covers reading the hook payload, splitting a shell command into parts, finding the
repository root and its default branch, reading `.agent-skills.json`, and emitting the
deny or context JSON the hook protocol expects.
"""

import json
import os
import subprocess
import sys
from typing import Any, Optional


def read_payload() -> dict[str, Any]:
    """Reads the hook JSON payload from stdin. Returns {} on any failure."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def command_parts(command: str) -> list[str]:
    """Splits a shell command into parts on &&, ||, ;, | and newlines.

    Quoted sections are kept intact so an operator inside a string does not split the
    command. Empty parts are dropped and the rest are stripped of surrounding whitespace.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    length = len(command)

    while index < length:
        char = command[index]

        if quote:
            current.append(char)
            if char == quote and (index == 0 or command[index - 1] != "\\"):
                quote = ""
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            continue

        if char == "\n":
            parts.append("".join(current))
            current = []
            index += 1
            continue

        if char == "|" and command[index + 1 : index + 2] == "|":
            parts.append("".join(current))
            current = []
            index += 2
            continue

        if char == "&" and command[index + 1 : index + 2] == "&":
            parts.append("".join(current))
            current = []
            index += 2
            continue

        if char in (";", "|"):
            parts.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def strip_env_prefix(part: str) -> str:
    """Removes leading environment assignments ("VAR=value") from a command part."""
    tokens = part.split()
    while tokens and _looks_like_assignment(tokens[0]):
        tokens = tokens[1:]
    return " ".join(tokens)


def _looks_like_assignment(token: str) -> bool:
    name, sep, _ = token.partition("=")
    if not sep:
        return False
    return (
        bool(name)
        and (name[0].isalpha() or name[0] == "_")
        and all(char.isalnum() or char == "_" for char in name)
    )


def run_git(args: list[str], cwd: Optional[str]) -> Optional[str]:
    """Runs git with args in cwd. Returns stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_root(cwd: Optional[str]) -> Optional[str]:
    """The repository root for cwd, or None when cwd is not inside a git repository."""
    return run_git(["rev-parse", "--show-toplevel"], cwd)


def agent_skills_config(root: Optional[str]) -> dict[str, Any]:
    """Reads .agent-skills.json from the repository root. {} when absent or invalid."""
    if not root:
        return {}
    path = os.path.join(root, ".agent-skills.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def default_branch(cwd: Optional[str]) -> str:
    """The repository's default branch name, detected from the checkout in cwd.

    Tries the remote's HEAD symref first, then falls back to main or master, whichever
    exists as a local branch. Defaults to "main" when nothing can be determined.
    """
    ref = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
    if ref:
        return ref.rsplit("/", 1)[-1]

    listing = run_git(["branch", "--list"], cwd) or ""
    names = {line.strip("* ").strip() for line in listing.splitlines()}
    for candidate in ("main", "master"):
        if candidate in names:
            return candidate
    return "main"


def emit(payload: dict[str, Any]) -> int:
    """Prints payload as the hook's JSON response. Always returns 0."""
    print(json.dumps(payload))
    return 0


def emit_empty() -> int:
    """Prints the empty response: nothing to say, never blocks."""
    print("{}")
    return 0


def deny(event: str, reason: str) -> int:
    """Emits a PreToolUse deny decision with the given reason."""
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def context(event: str, message: str) -> int:
    """Emits additional context for the given hook event."""
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": message,
            }
        }
    )
