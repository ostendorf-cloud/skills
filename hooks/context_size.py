#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""UserPromptSubmit hook. Warns when the session context has grown large.

Reads transcript_path from the payload and finds the last assistant record with a
message.usage object. The context size is input_tokens, cache_creation_input_tokens and
cache_read_input_tokens added up. Records with isSidechain true belong to a subagent and
are skipped, as is a record whose sum is zero.

A transcript can reach several hundred megabytes, so the file is read from its end in
bounded chunks and never as a whole. The scan stops after MAX_SCAN_BYTES.

At or above the threshold the hook adds one context line. The threshold is 150000
tokens, overridable with AGENT_SKILLS_CONTEXT_WARN (integer tokens, 0 disables). The line
is repeated once per 50000 token band and session: the last warned band lives in a small
state file keyed by session_id under the system temp directory. An unwritable state file
means the warning shows anyway. A payload with a non empty agent_id gets nothing.
"""

import contextlib
import json
import os
import re
import sys
import tempfile
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT_PROMPT = "UserPromptSubmit"
ENV_THRESHOLD = "AGENT_SKILLS_CONTEXT_WARN"
DEFAULT_THRESHOLD = 150000
BAND_SIZE = 50000
CHUNK_SIZE = 64 * 1024
MAX_SCAN_BYTES = 16 * 1024 * 1024
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def threshold() -> int:
    """The warning threshold in tokens. 0 disables. An invalid value means the default."""
    raw = os.environ.get(ENV_THRESHOLD, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_THRESHOLD
    return value if value >= 0 else DEFAULT_THRESHOLD


def record_tokens(line: bytes) -> Optional[int]:
    """The context size a transcript line reports, or None when it reports none."""
    if b'"usage"' not in line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("isSidechain") is True:
        return None
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if record.get("type") != "assistant" or not isinstance(usage, dict):
        return None
    total = 0
    for key in USAGE_KEYS:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total or None


def last_context_tokens(path: str) -> Optional[int]:
    """The context size of the last assistant record, reading only the file's tail."""
    try:
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
                for line in reversed(lines):
                    tokens = record_tokens(line)
                    if tokens is not None:
                        return tokens
    except OSError:
        return None
    return None


def state_path(session_id: Any) -> Optional[str]:
    if not isinstance(session_id, str) or not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:100]
    return os.path.join(tempfile.gettempdir(), f"agent-skills-context-{safe}.json")


def read_band(path: Optional[str]) -> Optional[int]:
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            band = json.load(handle).get("band")
    except (OSError, ValueError, AttributeError):
        return None
    return band if isinstance(band, int) and not isinstance(band, bool) else None


def write_band(path: Optional[str], band: int) -> None:
    """Writes the warned band atomically. Any failure is ignored."""
    if path is None:
        return
    temp = None
    try:
        descriptor, temp = tempfile.mkstemp(
            prefix=".agent-skills-context-", dir=os.path.dirname(path)
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"band": band}, handle)
        os.replace(temp, path)
        temp = None
    except OSError:
        pass
    finally:
        if temp is not None:
            with contextlib.suppress(OSError):
                os.unlink(temp)


def clear_band(path: Optional[str]) -> None:
    if path is None:
        return
    with contextlib.suppress(OSError):
        os.unlink(path)


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT_PROMPT:
        return _common.emit_empty()
    if payload.get("agent_id"):
        return _common.emit_empty()
    limit = threshold()
    transcript = payload.get("transcript_path")
    if limit == 0 or not isinstance(transcript, str) or not transcript:
        return _common.emit_empty()

    tokens = last_context_tokens(transcript)
    if tokens is None:
        return _common.emit_empty()

    path = state_path(payload.get("session_id"))
    if tokens < limit:
        # A compaction shrank the context: the next growth past the limit warns again.
        clear_band(path)
        return _common.emit_empty()

    band = tokens // BAND_SIZE
    warned = read_band(path)
    if warned is not None and band <= warned:
        return _common.emit_empty()
    write_band(path, band)
    return _common.context(
        EVENT_PROMPT,
        f"The context holds about {tokens // 1000}k tokens. Finish the current step, "
        "write the state to the issue with the `handoff` skill, then continue from the "
        "handoff or stop with the state recorded. Never make `/clear` by the user the only "
        "way on. Interactive: offer `/clear` as a choice in one line. Unattended "
        "(`CI=true`): never ask.",
    )


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
