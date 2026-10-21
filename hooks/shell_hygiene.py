#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies file content written through the shell: a heredoc or
redirect into a file, `tee`, `sed -i`, `perl -i`, a heredoc fed to an interpreter, an
inline interpreter one liner that spans lines or is too long to review, and an inline
interpreter one liner that opens a file for writing.
"""

import os
import re
import shlex
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

FLAG_FOR_INTERPRETER = {
    "python3": "-c",
    "python": "-c",
    "node": "-e",
    "perl": "-e",
    "ruby": "-e",
}
MODE_CHARS = set("rwaxbt+")
MODE_KWARG = re.compile(r"^mode\s*=\s*(.+)$")


def inline_calls(command: str) -> list:
    """Every inline python -c, node -e, perl -e or ruby -e call that starts a command
    part of command, after splitting on &&, ||, ; and |.

    The interpreter is anchored to the start of its part, the same position
    `INLINE_FLAG` anchors to, so a mention inside another command's argument, such as
    `echo python3 -c '...'`, is not an inline call. A leading environment assignment is
    stripped first, so `FOO=bar python3 -c '...'` still anchors. A part that cannot be
    split into shell tokens is skipped rather than failing the whole command.
    """
    calls = []
    for part in _common.command_parts(command):
        try:
            tokens = shlex.split(_common.strip_env_prefix(part))
        except ValueError:
            continue
        if len(tokens) < 3:
            continue
        name = os.path.basename(tokens[0])
        flag = FLAG_FOR_INTERPRETER.get(name)
        if flag and tokens[1] == flag:
            calls.append((name, tokens[2]))
    return calls


def _strip_quotes(text: str) -> str:
    return text.strip().strip("'\"")


def _is_write_mode(text: str) -> bool:
    """Whether text is a file mode string that opens a file for writing or appending."""
    mode = _strip_quotes(text)
    if not mode or len(mode) > 4 or any(char not in MODE_CHARS for char in mode):
        return False
    return "w" in mode or "a" in mode


def _split_args(args: str) -> list:
    """Splits a call's argument text on top level commas, keeping quoted text intact."""
    parts: list = []
    current: list = []
    quote = ""
    for char in args:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
            continue
        if char == ",":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts]


def _open_call_writes(code: str, call: str) -> bool:
    """Whether a call such as open( or File.open( in code opens a file for writing,
    from its second positional argument or a mode= keyword argument.

    The lookbehind only excludes a preceding identifier character, not a preceding
    dot, so a dotted receiver such as `io.open(` or `pathlib.Path(p).open(` is caught
    too, alongside the bare `open(` call it is written to also match. A path object's
    `.open(mode)` takes the mode as its only argument, so for a dotted call a single
    argument is checked too, not only the second positional argument of the builtin
    `open(path, mode)`.
    """
    pattern = re.compile(r"(?<!\w)" + re.escape(call) + r"\s*\(([^()]*)\)")
    for match in pattern.finditer(code):
        dotted = match.start() > 0 and code[match.start() - 1] == "."
        args = _split_args(match.group(1))
        if len(args) >= 2 and _is_write_mode(args[1]):
            return True
        if dotted and len(args) == 1 and _is_write_mode(args[0]):
            return True
        for arg in args:
            kwarg = MODE_KWARG.match(arg)
            if kwarg and _is_write_mode(kwarg.group(1)):
                return True
    return False


PERL_OPEN_PAREN = re.compile(r"(?<![\w.])open\s*\(([^()]*)\)")
PERL_OPEN_NO_PAREN = re.compile(r"(?<!\w)open\s+(?!\()([^;]*)")


def _perl_open_writes(code: str) -> bool:
    """Whether a perl open call in code carries a > mode: `open(FH, ">", $file)`, the
    two argument form `open(FH, ">$file")`, or the common parenless spelling
    `open my $fh, ">", "file"`."""
    if any(">" in match.group(1) for match in PERL_OPEN_PAREN.finditer(code)):
        return True
    return any(">" in match.group(1) for match in PERL_OPEN_NO_PAREN.finditer(code))


def inline_writes_file(interpreter: str, code: str) -> bool:
    """Whether an inline interpreter one liner's code argument opens a file for
    writing. A read only one liner returns False."""
    if interpreter in ("python3", "python"):
        return ".write_text(" in code or ".write_bytes(" in code or _open_call_writes(code, "open")
    if interpreter == "node":
        return (
            "writeFileSync(" in code
            or "writeFile(" in code
            or "appendFileSync(" in code
            or "appendFile(" in code
        )
    if interpreter == "ruby":
        return "File.write(" in code or _open_call_writes(code, "File.open")
    if interpreter == "perl":
        return _perl_open_writes(code)
    return False


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

    for interpreter, code in inline_calls(command):
        if inline_writes_file(interpreter, code):
            return _common.deny(
                EVENT,
                "This inline interpreter one liner opens a file for writing, which is "
                f"file authoring through the shell. {USE_FILE_TOOLS}",
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
