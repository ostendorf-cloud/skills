#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Stop hook. Blocks the end of a turn that names an owner step without asking for it.

The orchestrator asks every owner decision with the question tool in the same turn. An
owner step that stands only as bold text is never read. The hook looks at
last_assistant_message from the payload. It counts as a bold owner step when:

- a markdown table row holds a bold span, the header row of a table excepted, or
- a line starts with a bold span, after leading whitespace and an optional list or quote
  marker (`-`, `*`, `+`, `1.`, `>`).

Bold in the middle of a sentence and headings do not count. Fenced code blocks and inline
code spans are removed first.

When such a step exists, the hook reads the transcript from its end, back to the last real
user message: a user record the person wrote. Tool results, meta records and text the
harness injects mid-turn, such as a task notification, do not start a turn. The turn made
a question tool call when an assistant record in that range holds a tool_use block named
AskUserQuestion. Without one, the hook answers {"decision": "block", "reason": ...}.

The hook stays silent, answering {}, for unattended runs (CI=true), for a payload with a
non empty agent_id or agent_type, when stop_hook_active is true (the turn was already
blocked once), and whenever the transcript cannot be read. The transcript is read from its
end in bounded chunks, never as a whole.
"""

import json
import os
import re
import sys
from collections.abc import Iterator
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "Stop"
QUESTION_TOOL = "AskUserQuestion"
CHUNK_SIZE = 64 * 1024
MAX_SCAN_BYTES = 16 * 1024 * 1024
BOLD_SPAN = re.compile(r"\*\*[^*\n]+\*\*")
BOLD_LINE_START = re.compile(r"^\s*(?:(?:>|[-*+]|\d+[.)])\s+)*\*\*[^*\n]+\*\*")
# Text a harness injects as a user record, for example a finished background task.
INJECTED_PREFIXES = ("<task-notification>", "<system-reminder>", "<local-command")
TABLE_ROW = re.compile(r"^\s*\|")
TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]*-[\s:|-]*$")

REASON = (
    "An owner step stands as bold text and this turn made no question tool call. "
    "The user reads only the question tool. Ask every bold owner step with the question "
    "tool in this turn, then end the turn."
)


def has_owner_step(message: str) -> bool:
    """True when message holds a bold owner step as defined in the module docstring."""
    lines = _common.strip_code(message).splitlines()
    for index, line in enumerate(lines):
        if TABLE_ROW.match(line):
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if TABLE_SEPARATOR.match(following):
                continue
            if BOLD_SPAN.search(line):
                return True
        elif BOLD_LINE_START.match(line):
            return True
    return False


def reversed_lines(path: str) -> Iterator[bytes]:
    """The lines of a file, last first, reading at most MAX_SCAN_BYTES from its end."""
    with open(path, "rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        carry = b""
        scanned = 0
        while position > 0 and scanned < MAX_SCAN_BYTES:
            size = min(CHUNK_SIZE, position)
            position -= size
            scanned += size
            handle.seek(position)
            lines = (handle.read(size) + carry).split(b"\n")
            # The first line may be cut by the chunk edge: keep it for the next round.
            carry = lines.pop(0) if position > 0 else b""
            yield from reversed(lines)
        if position == 0 and carry:
            yield carry


def is_real_user_message(record: dict[str, Any]) -> bool:
    """A user record the person wrote.

    A tool_result, a meta record, a record whose origin is not human and text the harness
    injected (a task notification, a system reminder) arrive mid-turn and start no turn.
    A typed prompt carries origin {"kind": "human"} and starts a turn.
    """
    if record.get("type") != "user" or record.get("isMeta") is True:
        return False
    origin = record.get("origin")
    if origin and not (isinstance(origin, dict) and origin.get("kind") == "human"):
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return not content.lstrip().startswith(INJECTED_PREFIXES)
    if not isinstance(content, list):
        return False
    texts = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") == "tool_result":
            return False
        text = item.get("text")
        if isinstance(text, str):
            texts.append(text)
    return not any(text.lstrip().startswith(INJECTED_PREFIXES) for text in texts)


def calls_question_tool(record: dict[str, Any]) -> bool:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if record.get("type") != "assistant" or not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("type") == "tool_use"
        and item.get("name") == QUESTION_TOOL
        for item in content
    )


def turn_asked(path: str) -> bool:
    """True when the last turn of the transcript made a question tool call.

    Raises OSError when the file cannot be read.
    """
    for line in reversed_lines(path):
        if QUESTION_TOOL.encode() not in line and b'"user"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("isSidechain") is True:
            continue
        if calls_question_tool(record):
            return True
        if is_real_user_message(record):
            return False
    return False


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT:
        return _common.emit_empty()
    if os.environ.get("CI") == "true":
        return _common.emit_empty()
    if payload.get("agent_id") or payload.get("agent_type") or payload.get("stop_hook_active"):
        return _common.emit_empty()
    message = payload.get("last_assistant_message")
    transcript = payload.get("transcript_path")
    if not isinstance(message, str) or not isinstance(transcript, str) or not transcript:
        return _common.emit_empty()
    if not has_owner_step(message):
        return _common.emit_empty()
    try:
        asked = turn_asked(transcript)
    except OSError:
        return _common.emit_empty()
    if asked:
        return _common.emit_empty()
    return _common.emit({"decision": "block", "reason": REASON})


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
