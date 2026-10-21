#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Adds context on `gh issue edit` or `gh pr edit` that adds an
`ai:` label without also removing at least one other `ai:` label, as a reminder that only
one `ai:` state label may remain after the move. Never denies, the command is reversible.
"""

import os
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GH_LABEL_EDIT = re.compile(r"^gh\s+(issue|pr)\s+edit\b")

MESSAGE = (
    "Exactly one ai: state label must remain after this move. Remove every other ai: "
    "label in the same call, then list the labels to confirm the result."
)


def flag_values(tokens: list[str], flag: str) -> list[str]:
    """Every value given to flag in tokens, exact or `flag=value` form, in order."""
    values: list[str] = []
    prefix = f"{flag}="
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == flag:
            if index + 1 < len(tokens):
                values.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith(prefix):
            values.append(token[len(prefix) :])
            index += 1
            continue
        index += 1
    return values


def has_ai_label(values: list[str]) -> bool:
    """Whether any comma separated element of values starts with "ai:"."""
    return any(item.strip().startswith("ai:") for value in values for item in value.split(","))


def label_move_message(part: str) -> Optional[str]:
    """The context message for a `gh issue edit` or `gh pr edit` part, or None."""
    if not GH_LABEL_EDIT.match(part):
        return None
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None

    if not has_ai_label(flag_values(tokens, "--add-label")):
        return None
    if has_ai_label(flag_values(tokens, "--remove-label")):
        return None
    return MESSAGE


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    for raw_part in _common.command_parts(command):
        part = _common.strip_env_prefix(raw_part)
        if not part.startswith("gh "):
            continue
        message = label_move_message(part)
        if message:
            return _common.context(EVENT, message)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
