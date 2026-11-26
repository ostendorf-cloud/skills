#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""SessionStart hook. Adds the rules for the session that talks to the user as context.

Reads main-session.md from the directory this script sits in, where scripts/install.py
copies rules/main-session.md next to the installed hooks, so the installation needs no
checkout. A checkout run falls back to ../rules/main-session.md. The content is emitted
for every SessionStart source: startup, resume, clear and compact.

A payload with a non empty agent_id marks a subagent and gets nothing.

ASSUMPTION, not verified: the payload of the main session carries no agent_id or an empty
one, and SessionStart may not fire inside a subagent at all. The code is safe either way:
an absent or empty agent_id emits the rules, a non empty one emits nothing.

The harness cuts additional context at 10000 characters. The shipped file stays under
9000, which the test asserts.
"""

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT_START = "SessionStart"
RULES_NAME = "main-session.md"


def rules_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(here, RULES_NAME),
        os.path.join(os.path.dirname(here), "rules", RULES_NAME),
    ]


def read_rules() -> Optional[str]:
    for path in rules_paths():
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read().strip()
        except OSError:
            continue
        if text:
            return text
    return None


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT_START:
        return _common.emit_empty()
    if payload.get("agent_id"):
        return _common.emit_empty()

    text = read_rules()
    if not text:
        return _common.emit_empty()
    return _common.context(EVENT_START, text)


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
