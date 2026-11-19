#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash, Read, Write, Edit, MultiEdit and NotebookEdit. Denies a call
whose input names a session scratchpad path with a dash instead of a slash before the
session id.

The real layout is `/private/tmp/claude-<uid>/<project dir>/<session id>/`. The project
dir is the absolute project path with every separator turned into a dash, so it starts
with a dash. A slip joins the session id to it with a dash as well. Such a path does not
exist, so the call fails with "no such file" or writes into a stray directory.

The hook reads only the tool input. It touches no file, starts no process and writes
nothing. It does not check that the corrected path exists.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

# Tool input fields that hold a command or a path.
INPUT_FIELDS = ("command", "file_path", "notebook_path")

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# The project dir starts with a dash and holds no slash. The session id follows it after
# a dash, where the real layout has a slash. The lookahead ends the id on a separator, so
# a longer hex run is not taken for a session id.
WRONG_PATH = re.compile(
    r"(?P<base>(?:/private)?/tmp/claude-[0-9]+/-[A-Za-z0-9._-]*?)"
    rf"-(?P<session>{UUID})(?![0-9A-Za-z_-])"
)


def corrected_paths(text: str) -> list[str]:
    """The corrected form of every wrong scratchpad path in text, in order, without
    repeats. The corrected form ends on the session id, followed by a slash."""
    found: list[str] = []
    for match in WRONG_PATH.finditer(text):
        fixed = f"{match.group('base')}/{match.group('session')}/"
        if fixed not in found:
            found.append(fixed)
    return found


def main() -> int:
    payload = _common.read_payload()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return _common.emit_empty()

    fixed: list[str] = []
    for field in INPUT_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str):
            fixed.extend(path for path in corrected_paths(value) if path not in fixed)
    if not fixed:
        return _common.emit_empty()

    return _common.deny(
        EVENT,
        "The scratchpad path has a dash before the session id. The session id is its own "
        "directory. Retry with: " + " ".join(fixed),
    )


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
