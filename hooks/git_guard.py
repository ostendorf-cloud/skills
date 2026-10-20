#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a push to the default branch, a force push without
`--force-with-lease` or one onto the default branch, a command that bypasses hooks or
commit signing, and deletion of the default branch, local or remote.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GIT_PUSH = re.compile(r"^git\s+push\b")
GIT_BRANCH = re.compile(r"^git\s+branch\s+")
BYPASS_FLAGS = re.compile(r"--no-verify\b|--no-gpg-sign\b|-c\s+commit\.gpgsign=false")

USE_FEATURE_BRANCH = "Push a feature branch and open a pull request instead."
USE_FORCE_WITH_LEASE = (
    "Use --force-with-lease on a feature branch, it fails when the remote moved since "
    "the last fetch."
)


def current_branch(cwd: Optional[str]) -> str:
    """The checked out branch in cwd, or "" when it cannot be determined."""
    return _common.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd) or ""


def push_targets_default(tokens: list[str], cwd: Optional[str], default: str) -> bool:
    """Whether a `git push` with these tokens (after "push") reaches the default branch."""
    non_flag = [token for token in tokens if not token.startswith("-")]

    for token in non_flag[1:]:
        target = token.split(":")[-1]
        target = target[len("refs/heads/") :] if target.startswith("refs/heads/") else target
        if target == default:
            return True

    if len(non_flag) <= 1:
        return current_branch(cwd) == default

    return False


def push_violation(part: str, cwd: Optional[str], default: str) -> Optional[str]:
    """The deny reason for a `git push` part, or None when it is fine."""
    if not GIT_PUSH.match(part):
        return None

    tokens = part.split()[2:]

    if push_targets_default(tokens, cwd, default):
        return f"This pushes to {default}, the default branch. {USE_FEATURE_BRANCH}"

    if "--delete" in tokens and default in tokens:
        return f"This deletes {default} on the remote. The default branch is never deleted."

    has_plain_force = any(token in ("--force", "-f") for token in tokens)
    has_lease = any(
        token == "--force-with-lease" or token.startswith("--force-with-lease=") for token in tokens
    )

    if has_plain_force:
        return f"This force pushes without --force-with-lease. {USE_FORCE_WITH_LEASE}"

    if has_lease and push_targets_default(tokens, cwd, default):
        return f"This force pushes to {default}. {USE_FORCE_WITH_LEASE}"

    return None


def branch_delete_violation(part: str, default: str) -> Optional[str]:
    """The deny reason for a `git branch` part that deletes the default branch."""
    if not GIT_BRANCH.match(part):
        return None

    tokens = part.split()[2:]
    if not any(token in ("-D", "-d", "--delete") for token in tokens):
        return None

    names = [token for token in tokens if not token.startswith("-")]
    if default in names:
        return f"This deletes the local branch {default}, the default branch. It is never deleted."

    return None


def bypass_violation(part: str) -> Optional[str]:
    """The deny reason when part skips hooks or commit signing."""
    if BYPASS_FLAGS.search(part):
        return (
            "This bypasses git hooks or commit signing. Run the command without "
            "--no-verify, --no-gpg-sign or -c commit.gpgsign=false."
        )
    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    default = _common.default_branch(cwd)

    for raw_part in _common.command_parts(command):
        part = _common.strip_env_prefix(raw_part)
        if not part.startswith("git "):
            continue

        reason = (
            bypass_violation(part)
            or push_violation(part, cwd, default)
            or branch_delete_violation(part, default)
        )
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(main())
