#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies file content written through the shell: a heredoc or
redirect into a file, `tee`, an in place edit of `sed` or `perl` in any flag order or
spelling, a heredoc fed to an interpreter directly or through a pipe, an inline
interpreter one liner that spans lines or is too long to review, and an inline
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

INLINE_FLAG = re.compile(r"^(python3?\s+-c|node\s+-e|perl\s+-e|ruby\s+-e)\b")
HEREDOC = re.compile(r"<<-?\s*[\"']?\w+")
TEE = re.compile(r"^tee\b")

IN_PLACE_COMMAND = re.compile(r"^(g?sed|perl[0-9.]*)$")
IN_PLACE_LONG = "--in-place"
IN_PLACE_CHARS = {"sed": set("iI"), "perl": set("i")}
VALUE_CHARS = {"sed": set("ef"), "perl": set("IemMEFxD")}
WORD_SPLIT = re.compile(r"[$(){};`&|]")
NESTED_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
MAX_PARTS = 64

WRITE_REDIRECT = re.compile(r"(?<![0-9<>])(>{1,2})\s*(?P<target>[^\s;&|()]+)")
ALLOWED_TARGETS = re.compile(
    r"^(/dev/(null|stdout|stderr|tty)\b"
    r"|\$\{?(GITHUB_OUTPUT|GITHUB_ENV|GITHUB_STEP_SUMMARY)\}?$)"
)
# Directories a redirect or tee may write into besides $TMPDIR, the session scratch
# scope. The path is resolved first, so `$TMPDIR/../repo/x` and `/tmp/../repo/x` are
# judged by where they land.
FIXED_SCRATCH_ROOTS = ("/tmp", "/private/tmp")

INLINE_LIMIT = 200

SCOPE_NOTE = (
    "This applies inside a repository and to any path outside the session scratch "
    "directory and $TMPDIR."
)
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
INTERPRETER_NAMES = set(FLAG_FOR_INTERPRETER)
MODE_CHARS = set("rwaxbt+")
MODE_KWARG = re.compile(r"^mode\s*=\s*(.+)$")


def inline_calls(command: str) -> list:
    """Every inline python -c, node -e, perl -e or ruby -e call that starts a command
    part of command, after splitting on &&, ||, ; and |.

    The interpreter is anchored to the start of its part, the same position
    `INLINE_FLAG` anchors to, so a mention inside another command's argument, such as
    `echo python3 -c '...'`, is not an inline call. A leading wrapper, such as an
    environment assignment, `env`, `mise exec --` or `time`, is stripped first
    through `_common.strip_wrappers`, so `mise exec -- python3 -c '...'` still
    anchors. A part that cannot be split into shell tokens is skipped rather than
    failing the whole command.
    """
    calls = []
    for part in _common.command_parts(command):
        try:
            tokens = shlex.split(_common.strip_wrappers(part))
        except ValueError:
            continue
        if len(tokens) < 3:
            continue
        name = os.path.basename(tokens[0])
        flag = FLAG_FOR_INTERPRETER.get(name)
        if flag and tokens[1] == flag:
            calls.append((name, tokens[2]))
    return calls


def shell_tokens(part: str) -> list:
    """The shell words of part, quotes removed, so a quoted flag such as `'-i'`
    reads as the flag it is and a quoted sentence stays one word.

    Falls back to splitting a quote masked copy when part cannot be tokenized,
    for example because a quote is left open by a heredoc body.
    """
    try:
        return shlex.split(part, comments=False, posix=True)
    except ValueError:
        return _common.mask_quoted(part).split()


def command_word(token: str) -> str:
    """The command name token carries, free of a path and of the shell punctuation
    a command word can sit behind, so `/usr/bin/python3`, `(python3` and
    `out=$(python3` all resolve to "python3".

    An `=` alone does not introduce a command: `out=$(sed` is a substitution and
    resolves to "sed", while the data argument `user=sed` of an unrelated command
    resolves to nothing and is never read as a call.
    """
    segments = [segment for segment in WORD_SPLIT.split(token) if segment]
    if not segments:
        return ""
    return os.path.basename(segments[-1])


def _interpreter_token(part: str) -> Optional[str]:
    """The interpreter name part starts with, or None when part does not start
    with one of the supported interpreters. The name is read through
    `command_word`, so a path and a leading subshell or substitution paren do not
    hide it."""
    tokens = part.split()
    if not tokens:
        return None
    name = command_word(tokens[0])
    return name if name in INTERPRETER_NAMES else None


def nested_shell_code(part: str) -> Optional[str]:
    """The code a nested shell call in part runs, the argument of `bash -c` and
    its relatives, or None when part holds no such call.

    A nested shell hides its code from every check that reads the outer command,
    so the code is scanned as commands of its own.
    """
    tokens = shell_tokens(part)
    for index, token in enumerate(tokens):
        if command_word(token) not in NESTED_SHELLS:
            continue
        for position in range(index + 1, len(tokens)):
            if tokens[position] == "-c":
                if position + 1 < len(tokens):
                    return tokens[position + 1]
                break
            if not tokens[position].startswith("-"):
                break
    return None


def scan_parts(command: str) -> list:
    """Every command part worth scanning: each part as written, the same part with
    its wrapper prefixes stripped where that differs, and the parts of the code a
    nested `bash -c` payload runs.

    A wrapper prefix hides a call from a check that anchors on the first token,
    and stripping one drops a leading assignment, which hides a call written as
    `out=$(sed ...)`. Keeping both forms means neither spelling escapes.
    """
    parts: list = []
    queue = list(_common.command_parts(command))
    while queue and len(parts) < MAX_PARTS:
        part = queue.pop(0)
        stripped = _common.strip_wrappers(part)
        parts.append(part)
        if stripped != part:
            parts.append(stripped)
        code = nested_shell_code(part)
        if code:
            queue.extend(_common.command_parts(code))
    return parts


def consumes_script_via_stdin(part: str) -> bool:
    """Whether part is an interpreter call whose program comes from a heredoc or a
    bare stdin redirect rather than from a file argument.

    The interpreter, given by name or by path, may be followed by any number of
    flag tokens and an optional bare `-` before the heredoc operator, in any flag
    order, so `python3 -u <<PY` and `python3 - <<PY` both match the same way as
    the bare `python3 <<PY`. A script file argument before the heredoc, such as
    `python3 report.py <<EOF`, runs an existing, reviewable file with the heredoc
    only feeding its stdin, and stays allowed.

    The tokens come from `_common.mask_quoted`, so a `<<` inside a quoted argument,
    such as the shift in `python3 -c 'print(1 << 3)'`, is never read as a heredoc
    operator.
    """
    tokens = _common.mask_quoted(part).split()
    if not tokens or _interpreter_token(part) is None:
        return False
    for token in tokens[1:]:
        if "<<" in token:
            return True
        if token != "-" and not token.startswith("-"):
            return False
    return False


def _reads_program_from_stdin(part: str) -> bool:
    """Whether part is an interpreter call with no script file argument, so the
    program it runs can only come from its stdin. `python3 -` and `python3 -u`
    qualify, `python3 analyze.py` does not."""
    tokens = _common.mask_quoted(part).split()
    if not tokens or _interpreter_token(part) is None:
        return False
    return all(token == "-" or token.startswith("-") for token in tokens[1:])


def _real_lines(command: str, masked: str) -> list:
    """Splits command into its own newline separated source lines, wherever masked
    has an unquoted newline, slicing the real text so a newline inside a quoted
    span is never mistaken for a line break."""
    parts = []
    start = 0
    for index, char in enumerate(masked):
        if char == "\n":
            parts.append(command[start:index])
            start = index + 1
    parts.append(command[start:])
    return parts


def _real_pipe_stages(line: str, masked_line: str) -> list:
    """Splits line into pipeline stages on a single unquoted `|`, leaving a doubled
    `||` in place, slicing the real text so quoted content is preserved verbatim."""
    parts = []
    start = 0
    index = 0
    length = len(masked_line)
    while index < length:
        if masked_line[index] == "|":
            if masked_line[index + 1 : index + 2] == "|":
                index += 2
                continue
            parts.append(line[start:index])
            start = index = index + 1
            continue
        index += 1
    parts.append(line[start:])
    return parts


def heredoc_piped_to_interpreter(command: str) -> bool:
    """Whether a line of command sends a heredoc through a pipe into an
    interpreter, such as `cat <<'PY' | python3`.

    Lines are matched on a copy of command with quoted spans masked, so a heredoc
    operator or a pipe mentioned only inside a quoted string, such as the `-m`
    argument of a `git commit`, is never mistaken for the real operator. A line
    counts when it carries a heredoc operator and any later pipeline stage, after
    stripping a wrapper prefix such as `mise exec --` or `env FOO=1`, is an
    interpreter that reads its program from stdin. A stage that names a script
    file, such as `python3 analyze.py`, runs a reviewable file and does not count.
    """
    masked = _common.mask_quoted(command)
    for line, masked_line in zip(_real_lines(command, masked), masked.split("\n")):
        if "<<" not in masked_line:
            continue
        stages = _real_pipe_stages(line, masked_line)
        for stage in stages[1:]:
            if _reads_program_from_stdin(_common.strip_wrappers(stage.strip())):
                return True
    return False


def _in_place_family(token: str) -> Optional[str]:
    """The tool family token names, "sed" or "perl", or None when token is no
    command word of either. Reads the name through `command_word`, so a path, a
    subshell paren, a command substitution and a `g` prefixed `gsed` or version
    suffixed `perl5.34` spelling all resolve to the family."""
    name = command_word(token)
    if not IN_PLACE_COMMAND.match(name):
        return None
    return "sed" if name.endswith("sed") else "perl"


def _is_in_place_long(token: str) -> bool:
    """Whether token is `--in-place`, `--in-place=<suffix>` or an unambiguous
    abbreviation of it, which GNU's option parser accepts the same way."""
    name = token.split("=", 1)[0]
    return len(name) >= 4 and IN_PLACE_LONG.startswith(name)


def _scans_to_in_place(args: list, family: str) -> bool:
    """Whether the argument list of a sed or perl call carries an in place edit
    flag: `-i`, `-i<suffix>`, `-I` for sed, `--in-place[=<suffix>]`, or a combined
    short group holding one of those, such as `-0pi`.

    A flag that takes a value swallows it: the rest of its own token when
    something is attached, as in `perl -Ilib`, and the next token otherwise, as in
    `sed -e 's/a/b/' -i x.go`, so neither is read as a flag or as an operand. `--`
    ends the options. `sed` permutes its options, so every token is scanned and
    `sed 's/a/b/' x.go -i` is caught. `perl` stops reading options at its first
    operand, so a later `-i` belongs to the script and the scan stops there.
    """
    in_place = IN_PLACE_CHARS[family]
    values = VALUE_CHARS[family]
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            return False
        if token == "-" or not token.startswith("-"):
            if family == "perl":
                return False
            continue
        if token.startswith("--"):
            if _is_in_place_long(token):
                return True
            continue
        body = token[1:]
        for position, char in enumerate(body):
            if char in in_place:
                return True
            if char in values:
                skip_next = position == len(body) - 1
                break
    return False


def has_in_place_flag(part: str) -> bool:
    """Whether part holds a `sed` or `perl` call that edits a file in place.

    Every token of part is a candidate command word, not only the first, so a
    call behind `xargs`, inside a loop body, after a `then`, or in a subshell is
    found too. The tokens come from `shell_tokens`, so a quoted flag such as
    `sed '-i'` reads as the flag it is, while a quoted sentence, such as the
    `--body` of a comment that mentions `sed -i`, stays one word and matches
    nothing.
    """
    tokens = shell_tokens(part)
    for index, token in enumerate(tokens):
        family = _in_place_family(token)
        if family and _scans_to_in_place(tokens[index + 1 :], family):
            return True
    return False


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


MODULE_OPEN_RECEIVERS = {"io", "codecs", "gzip", "bz2", "lzma"}
RECEIVER_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.$")


def _bound_receiver(code: str, start: int) -> bool:
    """Whether the call at start in code is a bound `.open(mode)` method on an
    object that already carries a path, such as `Path('a').open(`, `p.open(` or
    `self.path.open(`, rather than a module level free function such as
    `io.open(` that takes the path as its first argument.

    Not dotted at all, a bare `open(`, is never a bound receiver. Dotted and
    immediately preceded by a bare name that names one of the standard library
    modules exposing a free `open` function is the free function, not a bound
    method. Anything else immediately before the dot, a different bare name or the
    closing paren or bracket of a call or a subscript, is a bound method call.
    """
    if start == 0 or code[start - 1] != ".":
        return False
    receiver = RECEIVER_NAME.search(code[:start])
    return not (receiver and receiver.group(1) in MODULE_OPEN_RECEIVERS)


def _open_call_writes(code: str, call: str) -> bool:
    """Whether a call such as open( or File.open( in code opens a file for writing,
    from its second positional argument, a mode= keyword argument, or the sole
    positional argument of a bound `.open(mode)` method call.

    The lookbehind only excludes a preceding identifier character, not a preceding
    dot, so a dotted receiver such as `io.open(` or `Path('a').open(` is caught too,
    alongside the bare `open(` call it is written to also match. The mode is read
    from the first argument only for a bound method call, `_bound_receiver`, so a
    module level free function with a single argument, such as `io.open('ab')`,
    where that argument is a path rather than a mode, is never mistaken for a
    write.
    """
    pattern = re.compile(r"(?<!\w)" + re.escape(call) + r"\s*\(([^()]*)\)")
    for match in pattern.finditer(code):
        args = _split_args(match.group(1))
        if len(args) >= 2 and _is_write_mode(args[1]):
            return True
        if len(args) == 1 and _bound_receiver(code, match.start()) and _is_write_mode(args[0]):
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


def is_scratch_path(target: str, directory: Optional[str], tainted: bool = False) -> bool:
    """Whether target, read against directory when relative, lands inside $TMPDIR, /tmp or
    /private/tmp once resolved. A target that holds a variable, a substitution or a glob,
    or is relative while directory is unknown, is not scratch. When tainted, the command
    can move $TMPDIR or link a path, so $TMPDIR is no scratch root for it."""
    resolved = _common.resolve_dir(target, directory)
    if resolved is None:
        return False
    roots = [os.path.realpath(root) for root in FIXED_SCRATCH_ROOTS]
    if not tainted:
        roots = [*_common.scratch_roots(), *roots]
    return any(os.path.commonpath([root, resolved]) == root for root in roots)


def is_allowed_target(target: str, directory: Optional[str] = None, tainted: bool = False) -> bool:
    """Whether a redirect or tee target is one of the allowed scratch destinations.

    directory is where the command runs, used to read a relative target. It is the
    session scratch directory or a fixture below it when a relative target is allowed.
    """
    stripped = target.strip("'\"")
    if stripped in ("&1", "&2"):
        return True
    if ALLOWED_TARGETS.match(stripped):
        return True
    return is_scratch_path(stripped, directory, tainted)


def command_directory(command: str, cwd: Optional[str]) -> Optional[str]:
    """The one directory every part of command runs in, None when a `cd` or anything
    else moves it part way through or it is unknown."""
    directories = {directory for _, directory in _common.part_dirs(command, cwd)}
    return directories.pop() if len(directories) == 1 else None


def offending_redirect(
    command: str, directory: Optional[str] = None, tainted: bool = False
) -> Optional[str]:
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
        if not is_allowed_target(target, directory, tainted):
            return target.strip("'\"")
    return None


def tee_target(part: str) -> Optional[str]:
    """The file tee writes to in a stripped command part, or None when tee is absent
    or the target is a flag."""
    match = TEE.search(part)
    if not match:
        return None
    for token in part[match.end() :].split():
        if token.startswith("-"):
            continue
        return token
    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    stripped_parts = scan_parts(command)
    nested_codes = [code for code in map(nested_shell_code, stripped_parts) if code]

    feeds_a_program = any(consumes_script_via_stdin(part) for part in stripped_parts)
    pipes_a_program = any(heredoc_piped_to_interpreter(text) for text in [command, *nested_codes])
    if feeds_a_program or pipes_a_program:
        return _common.deny(
            EVENT,
            "This feeds a program to an interpreter through a heredoc, directly or "
            "through a pipe, which cannot be reviewed in an approval prompt. "
            f"{USE_FILE_TOOLS} {SCRIPT_FILE}",
        )

    if any(has_in_place_flag(part) for part in stripped_parts):
        return _common.deny(
            EVENT,
            "sed -i and perl -i, in any flag order or spelling, edit a file in place "
            f"through the shell. {USE_FILE_TOOLS}",
        )

    directory = command_directory(command, payload.get("cwd") or os.getcwd())
    tainted = _common.scope_tainted(command)

    for part in stripped_parts:
        target = tee_target(part)
        if target and not is_allowed_target(target, directory, tainted):
            return _common.deny(
                EVENT, f"tee writes {target} through the shell. {SCOPE_NOTE} {USE_FILE_TOOLS}"
            )

    redirect = offending_redirect(command, directory, tainted)
    if redirect:
        if HEREDOC.search(_common.mask_quoted(command)):
            return _common.deny(
                EVENT,
                f"This writes {redirect} from a heredoc, which is file authoring "
                f"through the shell. {SCOPE_NOTE} {USE_FILE_TOOLS}",
            )
        return _common.deny(
            EVENT,
            f"This redirects output into {redirect} through the shell. "
            f"{SCOPE_NOTE} {USE_FILE_TOOLS}",
        )

    for interpreter, code in inline_calls(command):
        if inline_writes_file(interpreter, code):
            return _common.deny(
                EVENT,
                "This inline interpreter one liner opens a file for writing, which is "
                f"file authoring through the shell. {USE_FILE_TOOLS}",
            )

    inline = any(INLINE_FLAG.search(part) for part in stripped_parts)
    if inline and ("\n" in command or len(command) > INLINE_LIMIT):
        return _common.deny(
            EVENT,
            "This inline interpreter one liner spans multiple lines or is too long to "
            f"review in an approval prompt. {SCRIPT_FILE} {USE_FILE_TOOLS}",
        )

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
