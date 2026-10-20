#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies file content written through the shell: a heredoc or
redirect into a file, `tee`, `sed -i`, `perl -i`, a heredoc fed to an interpreter, and an
inline interpreter one liner that spans lines or is too long to review.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

INTERPRETERS = r"python3?|node|perl|ruby"
INLINE_FLAG = re.compile(r"(^|[;&|]\s*)(python3?\s+-c|node\s+-e|perl\s+-e|ruby\s+-e)\b")
STDIN_SCRIPT = re.compile(r"(^|[;&|]\s*)(" + INTERPRETERS + r")\s+(-\s*)?<<")
HEREDOC = re.compile(r"<<-?\s*[\"']?\w+")
IN_PLACE = re.compile(r"\b(sed|perl)\s+(-[a-zA-Z]*i\S*|--in-place\S*)")
TEE = re.compile(r"(^|[;&|]\s*)tee\b")

WRITE_REDIRECT = re.compile(r"(?<![0-9<>])(>{1,2})\s*(?P<target>[^\s;&|()]+)")
ALLOWED_TARGETS = re.compile(
    r"^(/dev/(null|stdout|stderr|tty)\b"
    r"|\$\{?(TMPDIR|GITHUB_OUTPUT|GITHUB_ENV|GITHUB_STEP_SUMMARY)\}?"
    r"|/tmp(/|$)"
    r"|/private/tmp(/|$))"
)

INLINE_LIMIT = 200

USE_FILE_TOOLS = "Use the Write or Edit tool instead, it shows the exact content or diff."
SCRIPT_FILE = (
    "If this logic will run again, put it in a script file: repository specific under "
    "scripts/, generally useful in the shared scripts repository."
)


def is_allowed_target(target: str) -> bool:
    """Whether a redirect or tee target is one of the allowed scratch destinations."""
    stripped = target.strip("'\"")
    if stripped in ("&1", "&2"):
        return True
    return bool(ALLOWED_TARGETS.match(stripped))


def offending_redirect(command: str) -> Optional[str]:
    """The first write-redirect target in command that is not an allowed destination.

    The operator itself is matched against a quote-masked copy of command, so a `>`
    that only appears inside a single or double quoted string, such as a commit
    message or a jq filter, is not mistaken for a redirect. The target text is then
    read back from the real command at the same position, so a genuinely quoted
    target such as "$GITHUB_OUTPUT" still reads correctly.
    """
    for match in WRITE_REDIRECT.finditer(_common.mask_quoted(command)):
        start, end = match.span("target")
        target = command[start:end]
        if not is_allowed_target(target):
            return target.strip("'\"")
    return None


def tee_target(command: str) -> Optional[str]:
    """The file tee writes to, or None when tee is absent or the target is a flag."""
    match = TEE.search(command)
    if not match:
        return None
    for token in command[match.end() :].split():
        if token.startswith("-"):
            continue
        return token
    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    if STDIN_SCRIPT.search(command):
        return _common.deny(
            EVENT,
            "This feeds a program to an interpreter through stdin or a heredoc, which "
            f"cannot be reviewed in an approval prompt. {USE_FILE_TOOLS} {SCRIPT_FILE}",
        )

    if IN_PLACE.search(command):
        return _common.deny(
            EVENT, f"sed -i and perl -i edit a file in place through the shell. {USE_FILE_TOOLS}"
        )

    target = tee_target(command)
    if target and not is_allowed_target(target):
        return _common.deny(EVENT, f"tee writes {target} through the shell. {USE_FILE_TOOLS}")

    redirect = offending_redirect(command)
    if redirect:
        if HEREDOC.search(_common.mask_quoted(command)):
            return _common.deny(
                EVENT,
                f"This writes {redirect} from a heredoc, which is file authoring "
                f"through the shell. {USE_FILE_TOOLS}",
            )
        return _common.deny(
            EVENT, f"This redirects output into {redirect} through the shell. {USE_FILE_TOOLS}"
        )

    inline = INLINE_FLAG.search(command)
    if inline and ("\n" in command or len(command) > INLINE_LIMIT):
        return _common.deny(
            EVENT,
            "This inline interpreter one liner spans multiple lines or is too long to "
            f"review in an approval prompt. {SCRIPT_FILE} {USE_FILE_TOOLS}",
        )

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
