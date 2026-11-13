#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""SessionStart hook. Warns once when the installed skills lag the checkout they were
installed from, or when that checkout itself lags origin/main.

Reads every installed target's state file under ~/.config/agent-skills, written by
scripts/install.py, and compares the commit it recorded against the checkout on this
machine. Both comparisons are offline: no fetch, only the commit already recorded and
the remote tracking ref the checkout already has locally. A machine with no checkout,
or a checkout with no origin/main ref, says nothing for that half of the check.
"""

import json
import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT_START = "SessionStart"
SHORT_LEN = 12


def home_dir() -> str:
    return os.environ.get("HOME") or os.path.expanduser("~")


def agent_skills_dir() -> str:
    return os.path.join(home_dir(), ".config", "agent-skills")


def state_paths(directory: str) -> list[str]:
    """Every installed target's state file in directory, default target first."""
    if not os.path.isdir(directory):
        return []
    found = []
    default = os.path.join(directory, "state.json")
    if os.path.isfile(default):
        found.append(default)
    for name in sorted(os.listdir(directory)):
        if name.endswith(".state.json"):
            found.append(os.path.join(directory, name))
    return found


def read_state(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def short(commit: str) -> str:
    return commit[:SHORT_LEN]


def check_source(source: str, recorded: Optional[str]) -> list[str]:
    """The warning lines for one installed source checkout. [] when nothing to say.

    The first line compares the commit recorded at install time against the checkout's
    current HEAD. The second compares that same HEAD against origin's default branch as
    last fetched, independent of the first: the installed copy can match a checkout
    that itself lags origin/main, which is the lag the first comparison alone misses.
    """
    if not source or not os.path.isdir(source):
        return []
    current = _common.run_git(["rev-parse", "HEAD"], source)
    if not current:
        return []

    lines: list[str] = []
    if recorded and recorded != current:
        lines.append(
            f"The installed skills are at {short(recorded)}, but the checkout at "
            f"{source} is at {short(current)}. Run `task install` to update them."
        )

    branch = _common.default_branch(source)
    origin_ref = _common.run_git(["rev-parse", f"refs/remotes/origin/{branch}"], source)
    if origin_ref and origin_ref != current:
        lines.append(
            f"The checkout at {source} is at {short(current)}, but its last known "
            f"origin/{branch} is {short(origin_ref)}. Pull the checkout, the comparison "
            "above only sees what it has on disk."
        )
    return lines


def collect_messages() -> list[str]:
    messages: list[str] = []
    seen_sources: set[str] = set()
    for path in state_paths(agent_skills_dir()):
        state = read_state(path)
        if not state:
            continue
        source = state.get("source") or ""
        if not source or source in seen_sources:
            continue
        seen_sources.add(source)
        messages.extend(check_source(source, state.get("commit")))
    return messages


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT_START:
        return _common.emit_empty()

    messages = collect_messages()
    if not messages:
        return _common.emit_empty()
    return _common.context(EVENT_START, "\n".join(messages))


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
