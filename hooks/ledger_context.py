#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""SessionStart hook. Adds the ledger of the current workstream as context.

The ledger is one Markdown file per workstream, outside every repository:
<org folder>/.ledger/<stream>.md. See the Ledger section of rules/main-session.md.

The ledger directory comes from AGENT_SKILLS_LEDGER_DIR when set. Otherwise the hook
walks up from the session's cwd and takes the first directory that holds a `.ledger`
directory. It never guesses a path that does not exist.

The stream comes from AGENT_SKILLS_STREAM when set. Otherwise it is the first line of
the file `<ledger dir>/current`. A stream name holds letters, digits, dot, dash and
underscore only and does not start with a dot, so it can never leave the ledger directory.

The content is emitted for every SessionStart source: startup, resume, clear and compact.
It is cut at MAX_CHARS, the harness cuts additional context at 10000 characters.

With no ledger, no stream or an empty file the hook prints nothing and exits 0. So does a
payload with a non empty agent_id, which marks a subagent, and any unexpected error.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT_START = "SessionStart"
ENV_DIR = "AGENT_SKILLS_LEDGER_DIR"
ENV_STREAM = "AGENT_SKILLS_STREAM"
LEDGER_DIRNAME = ".ledger"
CURRENT_NAME = "current"
STREAM_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
MAX_CHARS = 8000
HEADER = "Ledger of the current workstream, file {path}. The issue and gh state win over it.\n\n"
CUT_NOTE = "\n\n[ledger cut, read the file for the rest]"


def ledger_dir(cwd: str) -> Optional[str]:
    """The ledger directory: the environment variable, else the nearest `.ledger` above cwd."""
    configured = os.environ.get(ENV_DIR, "").strip()
    if configured:
        return configured if os.path.isdir(configured) else None
    current = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(current, LEDGER_DIRNAME)
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def stream_name(directory: str) -> Optional[str]:
    """The current stream: the environment variable, else the first line of `current`."""
    name = os.environ.get(ENV_STREAM, "").strip()
    if not name:
        try:
            with open(os.path.join(directory, CURRENT_NAME), encoding="utf-8") as handle:
                name = handle.readline().strip()
        except OSError:
            return None
    return name if STREAM_NAME.fullmatch(name) else None


def read_ledger(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def build(cwd: str) -> Optional[str]:
    directory = ledger_dir(cwd)
    if not directory:
        return None
    stream = stream_name(directory)
    if not stream:
        return None
    path = os.path.join(directory, f"{stream}.md")
    text = read_ledger(path)
    if not text:
        return None
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + CUT_NOTE
    return HEADER.format(path=path) + text


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT_START or payload.get("agent_id"):
        return 0
    message = build(payload.get("cwd") or os.getcwd())
    if not message:
        return 0
    return _common.context(EVENT_START, message)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(_common.emit_empty())
