#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Adds context on `gh issue edit` or `gh pr edit` that adds an
`ai:` label without also removing at least one other `ai:` label, as a reminder that only
one `ai:` state label may remain after the move. Never denies, the command is reversible.
"""

import os
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

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
    """The context message for a `gh issue edit` or `gh pr edit` part, or None.

    The subcommand is found through `_common.gh_dispatch`, so a flag in front of the
    noun does not hide it: `gh --hostname example.com issue edit 1 --add-label ...`
    moves a label just as the plain form does. The flag value scans read the whole
    token list, so they need no dispatch awareness of their own.

    Expects a part already run through `_common.normalize_command_part`, so a wrapper
    prefix such as `sudo` or `mise exec --` in front of gh does not hide the move.
    """
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None
    dispatch = _common.gh_dispatch(tokens)
    if len(dispatch) < 2 or dispatch[0] not in ("issue", "pr"):
        return None
    if _common.subcommand_after(dispatch[1:], space_form_takes_value=True) != "edit":
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
        part = _common.normalize_command_part(raw_part)
        if _common.command_name(part) != "gh":
            continue
        message = label_move_message(part)
        if message:
            return _common.context(EVENT, message)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
