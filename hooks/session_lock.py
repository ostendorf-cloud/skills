#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""SessionStart and SessionEnd hook. Records the session for its checkout and warns when
another live session already works in the same one. Cleans up its own record and any
record older than 24 hours.
"""

import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

import _common  # noqa: E402

EVENT_START = "SessionStart"
MAX_AGE_SECONDS = 24 * 60 * 60


def sessions_dir(cwd: Optional[str]) -> Optional[str]:
    """The directory session records live in, or None when cwd is not a git checkout."""
    common_dir = _common.run_git(["rev-parse", "--git-common-dir"], cwd)
    if not common_dir:
        return None
    if not os.path.isabs(common_dir):
        common_dir = os.path.join(cwd or os.getcwd(), common_dir)
    return os.path.join(common_dir, "agent-skills", "sessions")


def read_session(path: str) -> Optional[dict[str, object]]:
    """The cwd and started timestamp recorded at path, or None when unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None

    data = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            data[key] = value

    try:
        started = float(data.get("started", ""))
    except ValueError:
        return None

    return {"cwd": data.get("cwd", ""), "started": started}


def session_start(payload: dict[str, object]) -> int:
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or ""
    directory = sessions_dir(cwd)
    if not directory or not session_id:
        return _common.emit_empty()

    os.makedirs(directory, exist_ok=True)
    now = time.time()
    own_path = os.path.join(directory, session_id)
    with open(own_path, "w", encoding="utf-8") as handle:
        handle.write(f"cwd={cwd}\nstarted={int(now)}\npid={os.getppid()}\n")

    others = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if path == own_path:
            continue
        info = read_session(path)
        if info is None:
            continue
        age = now - info["started"]
        if age > MAX_AGE_SECONDS:
            with contextlib.suppress(OSError):
                os.remove(path)
            continue
        if info["cwd"] == cwd:
            others.append((name, age))

    if not others:
        return _common.emit_empty()

    name, age = others[0]
    minutes = int(age // 60)
    message = (
        f"Another session ({name}, started {minutes} min ago) works in this checkout. "
        "Use a worktree under .claude/worktrees/<branch> for parallel work, see the worktree "
        "skill."
    )
    return _common.context(EVENT_START, message)


def session_end(payload: dict[str, object]) -> int:
    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or ""
    directory = sessions_dir(cwd)
    if directory and session_id:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(directory, session_id))
    return _common.emit_empty()


def main() -> int:
    payload = _common.read_payload()
    event = payload.get("hook_event_name") or ""
    if event == "SessionStart":
        return session_start(payload)
    if event == "SessionEnd":
        return session_end(payload)
    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
