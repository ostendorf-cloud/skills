# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the skills repository hooks.

Covers reading the hook payload, splitting a shell command into parts, finding the
subcommand behind the flags in front of it, denying a policed command whose own
quoting does not parse, stripping fenced and inline code from text, finding the
repository root and its default branch, reading
`.agent-skills.json`, and emitting the deny or context JSON the hook protocol
expects.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Collection
from typing import Any, Optional


def read_payload() -> dict[str, Any]:
    """Reads the hook JSON payload from stdin. Returns {} on any failure."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def command_parts(command: str) -> list[str]:
    """Splits a shell command into parts on &&, ||, ;, | and newlines.

    Quoted sections are kept intact so an operator inside a string does not split the
    command. Empty parts are dropped and the rest are stripped of surrounding whitespace.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    length = len(command)

    while index < length:
        char = command[index]

        if quote:
            current.append(char)
            if char == quote and (index == 0 or command[index - 1] != "\\"):
                quote = ""
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            continue

        if char == "\n":
            parts.append("".join(current))
            current = []
            index += 1
            continue

        if char == "|" and command[index + 1 : index + 2] == "|":
            parts.append("".join(current))
            current = []
            index += 2
            continue

        if char == "&" and command[index + 1 : index + 2] == "&":
            parts.append("".join(current))
            current = []
            index += 2
            continue

        if char in (";", "|"):
            parts.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def mask_quoted(command: str) -> str:
    """Returns command with the interior of every quoted span replaced by "x".

    Quote delimiters themselves are kept in place, so the result has the same length
    and the same indices as command. Used to scan for a shell operator such as a
    redirect or a heredoc marker without matching one that only appears inside a
    string. Uses the same quote tracking as command_parts.
    """
    chars = list(command)
    quote = ""
    for index, char in enumerate(command):
        if quote:
            if char == quote and (index == 0 or command[index - 1] != "\\"):
                quote = ""
            else:
                chars[index] = "x"
            continue
        if char in ("'", '"'):
            quote = char
    return "".join(chars)


FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
BACKTICK_RUN = re.compile(r"`+")


def strip_code(text: str) -> str:
    """Removes fenced code blocks and inline code spans from text.

    A fenced block opens on a line that, after leading whitespace, starts with three
    or more backticks or tildes, an info string allowed after the marker. It closes
    on the next line holding nothing but at least that many of the same character,
    surrounding whitespace allowed. An opening fence with no matching close is left
    as plain text. Fenced lines, open through close, are blanked, which keeps the
    line structure intact for the text around them.

    An inline code span opens with a run of one or more backticks and closes only
    with the next run of exactly the same length later on the same line, a shorter
    or longer run encountered in between is content, not a delimiter. A span never
    crosses a line break: a trailer or a marker lives on its own line, so a stray
    backtick on one line can never pair with a stray backtick on another to swallow
    it, at the cost of also denying a deliberate quotation wrapped across a line
    break. A backtick run with no same-length closing run later on its line is left
    as plain text, it strips nothing. A matched span, delimiters and content, is
    replaced by a single space, so the text before and after it can never glue into
    a new match. Two stray backticks on one line around a pattern on that same line
    form a span by this rule and hide it. That is a quotation by the Markdown rules
    and an accepted limit: a trailer or a marker on its own line is never affected.

    Returns the text with every matched span removed this way.
    """
    lines = text.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        opening = FENCE_OPEN.match(line)
        if opening:
            fence_char = opening.group(1)[0]
            fence_len = len(opening.group(1))
            closing = _find_fence_close(lines, index + 1, fence_char, fence_len)
            if closing is not None:
                kept.extend([""] * (closing - index + 1))
                index = closing + 1
                continue
        kept.append(_strip_inline_spans(line))
        index += 1
    return "\n".join(kept)


def _find_fence_close(
    lines: list[str], start: int, fence_char: str, fence_len: int
) -> Optional[int]:
    """The index, at or after start, of the line in lines that closes a fence opened
    with fence_len copies of fence_char. None when no such line exists."""
    for index in range(start, len(lines)):
        body = lines[index].strip(" \t")
        if body and len(body) >= fence_len and set(body) == {fence_char}:
            return index
    return None


def _strip_inline_spans(text: str) -> str:
    """Replaces every inline code span in text with a single space.

    Scans left to right. A backtick run that reaches no run of the exact same
    length anywhere later in text is literal and is kept; a run of a different
    length encountered while looking for that close is skipped over as span
    content, the way CommonMark treats a shorter or longer run inside a span.
    """
    pieces: list[str] = []
    position = 0
    length = len(text)
    while position < length:
        opening = BACKTICK_RUN.search(text, position)
        if not opening:
            pieces.append(text[position:])
            break
        pieces.append(text[position : opening.start()])
        closing = _find_closing_run(text, opening.end(), opening.end() - opening.start())
        if closing is None:
            pieces.append(text[opening.start() : opening.end()])
            position = opening.end()
            continue
        pieces.append(" ")
        position = closing[1]
    return "".join(pieces)


def _find_closing_run(text: str, start: int, run_length: int) -> Optional[tuple[int, int]]:
    """The span, at or after start, of the next backtick run in text whose length is
    exactly run_length. None when no such run exists."""
    position = start
    while True:
        run = BACKTICK_RUN.search(text, position)
        if not run:
            return None
        if run.end() - run.start() == run_length:
            return run.start(), run.end()
        position = run.end()


def shell_words(part: str) -> list[str]:
    """part split into words on the whitespace a shell splits on, the quoting left in
    place, so each word still reads as it was written and rejoining them gives the
    command back.

    Whitespace inside quotes or behind a backslash does not split a word, so
    `FOO="a b" git push` is three words and `"/usr/bin/git" push` is two. Falls back to
    a plain whitespace split when a quote is left open, so a caller gets the words it
    got before and never has to guard the split itself.

    shlex cannot do this: its posix mode resolves the quoting away, which a caller that
    rebuilds the command needs kept, and its non-posix mode only honours a quote that
    opens a word, so it splits `FOO="a b"` in two.
    """
    words: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for char in part:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            current.append(char)
            quote = char
        elif char.isspace():
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(char)
    if quote:
        return part.split()
    if current:
        words.append("".join(current))
    return words


def unquote_word(word: str) -> str:
    """word with its own quoting resolved, so `"/usr/bin/git"` and `'git'` both read as
    the binary they name.

    A command whose first word is quoted still runs that binary, so a check that
    compares the word to a tool name resolves it through this first. The quote
    characters are removed outright when the word does not parse on its own, so an
    unbalanced quote resolves to a name rather than to nothing a check can match.

    A word without a quote, a backslash or whitespace is returned as it is, which is
    what shlex gives for it, without reading it character by character.
    """
    if (
        word
        and not any(char in word for char in "'\"\\")
        and not any(char.isspace() for char in word)
    ):
        return word
    try:
        resolved = shlex.split(word)
    except ValueError:
        return word.replace('"', "").replace("'", "")
    return resolved[0] if resolved else ""


def strip_env_prefix(part: str) -> str:
    """Removes leading environment assignments ("VAR=value") from a command part."""
    tokens = shell_words(part)
    while tokens and _looks_like_assignment(tokens[0]):
        tokens = tokens[1:]
    return " ".join(tokens)


def _looks_like_assignment(token: str) -> bool:
    name, sep, _ = token.partition("=")
    if not sep:
        return False
    return (
        bool(name)
        and (name[0].isalpha() or name[0] == "_")
        and all(char.isalnum() or char == "_" for char in name)
    )


# The wrappers that run another command, each with the flags it takes its own value
# for in front of that command, short and long. The flag walk follows getopt: a short
# flag listed here swallows the following word when it is the last letter of its
# cluster and takes the rest of the cluster as its value otherwise, a long flag
# swallows the following word unless it carries `--name=value` or resolves to one of
# the wrapper's boolean long flags in WRAPPER_BOOLEAN_FLAGS, a word starting with
# `-` that names no listed flag is skipped alone, and a `--` ends the wrapper's flags.
#
# Every table follows the tool's upstream manual rather than one build of it, because
# these hooks run on both a laptop and a Linux runner:
#
# - `nice [-n increment] utility`, plus GNU's `--adjustment=N` and its obsolete `-N`.
# - `nohup [--] utility`, no flags of its own on either BSD or GNU.
# - `sudo`'s thirteen value options from <https://www.sudo.ws/docs/man/sudo.man/>. The
#   macOS page carries nine because the SELinux and BSD authentication options are
#   build conditional, so `-a`, `-c`, `-r` and `-t` are listed from upstream.
# - `doas [-Lns] [-a style] [-C config] [-u user] command`, the OpenBSD manual.
# - `time`, whichever of the three a session reaches: BSD `time [-al] [-h | -p] [-o
#   file]`, GNU time's `-f FORMAT` with `--output=` and `--format=`, and the shell
#   keyword `time [-p]` with no value flag at all. The union is listed.
# - `exec [-cl] [-a name] [command]`, the shell builtin.
# - `command [-pVv] command`, which genuinely takes no value flag.
#
# A letter can be both. `sudo -h` is `--help` without a value and `-h host` with one,
# and it is listed here as value taking. Nothing follows from the choice: on either
# reading `sudo -h git push --force origin main` ends with sudo printing its usage or
# treating `git` as a host name, never with the push running.
#
# `sudo` and `doas` sit here as ordinary wrappers rather than as a category of their
# own: these hooks police what a command does, not who runs it, so a deny that applies
# to `git push --force origin main` has to apply to the same push behind a privilege
# escalation prefix. Whether the escalation itself is allowed at all is a permission
# question and belongs in the settings allow list, not in a hook.
WRAPPER_VALUE_FLAGS: dict[str, tuple[str, ...]] = {
    "time": ("-f", "-o", "--format", "--output"),
    "command": (),
    "exec": ("-a",),
    "nohup": (),
    "nice": ("-n", "--adjustment"),
    "sudo": (
        "-a",
        "-C",
        "-c",
        "-D",
        "-g",
        "-h",
        "-p",
        "-R",
        "-r",
        "-T",
        "-t",
        "-u",
        "-U",
        "--auth-type",
        "--chdir",
        "--chroot",
        "--close-from",
        "--command-timeout",
        "--group",
        "--host",
        "--login-class",
        "--other-user",
        "--prompt",
        "--role",
        "--type",
        "--user",
    ),
    "doas": ("-a", "-C", "-u"),
}

# The long flags each wrapper takes no value for, the counterpart of
# WRAPPER_VALUE_FLAGS and the other half of what the abbreviation rule needs.
#
# getopt_long resolves a `--name` token against every option the tool declares at
# once and prefers an exact match over any longer option the token also abbreviates.
# `sudo --login` is the long form of `-i` and takes no value, even though it is also
# a unique prefix of the value flag `--login-class`, so real sudo runs the command
# behind it. Matching the token against the value flags alone read `--login` as
# `--login-class`, swallowed the first word of the wrapped command and hid it from
# every check: `sudo --login git push --force origin main` resolved to `push --force
# origin main`, which names no git command at all.
#
# `--login` and `--login-class` are the only pair among these wrappers where one long
# flag is a prefix of another with a different arity. A prefix that matches several
# flags across both tables names none of them, which is what the tool itself reports,
# and the token is then skipped alone rather than swallowing a word.
#
# Only the long forms are listed. A boolean short letter needs no entry, because the
# cluster walk already treats every letter outside the value table as taking no value.
#
# Sources are the same manuals as above: sudo's options from
# <https://www.sudo.ws/docs/man/sudo.man/>, GNU `nice` and `nohup` with `--help` and
# `--version` from coreutils, GNU `time`'s six boolean long options, and `doas` with
# no long option at all. `sudo --preserve-env` sits here because it takes its list
# only in the `--preserve-env=list` form, which the `=` branch handles.
WRAPPER_BOOLEAN_FLAGS: dict[str, tuple[str, ...]] = {
    "time": (
        "--append",
        "--help",
        "--portability",
        "--quiet",
        "--verbose",
        "--version",
    ),
    "command": (),
    "exec": (),
    "nohup": ("--help", "--version"),
    "nice": ("--help", "--version"),
    "sudo": (
        "--askpass",
        "--background",
        "--bell",
        "--edit",
        "--help",
        "--list",
        "--login",
        "--no-update",
        "--non-interactive",
        "--preserve-env",
        "--preserve-groups",
        "--remove-timestamp",
        "--reset-timestamp",
        "--set-home",
        "--shell",
        "--stdin",
        "--validate",
        "--version",
    ),
    "doas": (),
}

# The flags that turn a wrapper into something that runs no command at all, so the
# words behind them are not a command line. `sudo -e` is sudoedit: the trailing words
# are files to edit, and reading the first of them as a command name would name a tool
# nothing runs. A wrapper carrying one of these strips to the empty string, the same
# result `sudo -V` already reaches, and every hook treats that as no command.
WRAPPER_NO_COMMAND_FLAGS: dict[str, tuple[str, ...]] = {
    "sudo": ("-e", "--edit"),
}


def strip_wrappers(part: str) -> str:
    """Removes leading wrapper prefixes from a command part, repeatedly, until none
    apply.

    Strips, in any combination and order: bare leading assignments through
    strip_env_prefix, `mise exec --`, `mise x --`, `mise exec <tool> --` where the
    tool spec is a single token with no spaces, `env` followed by zero or more
    `NAME=value` assignments, and every wrapper in WRAPPER_VALUE_FLAGS together with
    the flags it takes of its own, so `nice -n 10`, `sudo -u ci`, the clustered
    `sudo -nu ci` and the abbreviated `nice --adj 10` are stripped as well as the bare
    names. A wrapper not listed there, such as `timeout 5`, is left in place.

    Each wrapper name is read through unquote_word and its basename, so `"sudo"` and
    `/usr/bin/nice` are recognised the same as the bare names.

    Returns the empty string when nothing is left behind the wrapper, either because
    the part is only the wrapper and its flags or because a flag in
    WRAPPER_NO_COMMAND_FLAGS says it runs no command at all.
    """
    previous = None
    current = part
    while current != previous:
        previous = current
        current = strip_env_prefix(current)
        current = _strip_mise_exec(current)
        current = _strip_env_command(current)
        current = _strip_flagged_wrapper(current)
    return current


def _strip_mise_exec(part: str) -> str:
    """Removes a leading `mise exec --`, `mise x --` or `mise exec <tool> --` from
    part, the tool a single token with no spaces."""
    tokens = shell_words(part)
    if len(tokens) < 2 or _resolved_name(tokens[0]) != "mise":
        return part
    if tokens[1] in ("exec", "x") and len(tokens) >= 3 and tokens[2] == "--":
        return " ".join(tokens[3:])
    if tokens[1] == "exec" and len(tokens) >= 4 and tokens[3] == "--":
        return " ".join(tokens[4:])
    return part


def _strip_env_command(part: str) -> str:
    """Removes a leading `env` together with any `NAME=value` assignments that
    follow it from part."""
    tokens = shell_words(part)
    if not tokens or _resolved_name(tokens[0]) != "env":
        return part
    index = 1
    while index < len(tokens) and _looks_like_assignment(tokens[index]):
        index += 1
    return " ".join(tokens[index:])


def _strip_flagged_wrapper(part: str) -> str:
    """Removes a single leading wrapper named in WRAPPER_VALUE_FLAGS from part,
    together with the flags that wrapper takes of its own, so `nice -n 10 git push`
    and `sudo -nu ci git push` both leave `git push` and the bare `nice git push`
    leaves it too.

    Returns the empty string when the wrapper carries a flag from
    WRAPPER_NO_COMMAND_FLAGS, because then no wrapped command follows it."""
    tokens = shell_words(part)
    if not tokens:
        return part
    name = _resolved_name(tokens[0])
    value_flags = WRAPPER_VALUE_FLAGS.get(name)
    if value_flags is None:
        return part
    short_values = {flag[1] for flag in value_flags if len(flag) == 2}
    long_values = tuple(flag for flag in value_flags if flag.startswith("--"))
    long_flags = long_values + WRAPPER_BOOLEAN_FLAGS.get(name, ())
    no_command = WRAPPER_NO_COMMAND_FLAGS.get(name, ())

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-") or token == "-":
            break
        if _runs_no_command(token, no_command, short_values, long_flags):
            return ""
        index += 2 if _takes_following_word(token, short_values, long_values, long_flags) else 1
    return " ".join(tokens[index:])


def _takes_following_word(
    token: str,
    short_values: set[str],
    long_values: tuple[str, ...],
    long_flags: tuple[str, ...],
) -> bool:
    """Whether a flag token carries its value in the next word.

    A long flag does when it resolves to a listed value flag and no `=` holds the
    value in the same word. A cluster of short flags does when the first listed value
    flag in it is its last letter, because getopt reads anything after that letter
    inside the same word as the value instead, so `-nu ci` takes `ci` and `-nuci` does
    not."""
    if token.startswith("--"):
        flag, separator, _ = token.partition("=")
        if separator:
            return False
        return _resolve_long_flag(flag, long_flags) in long_values
    for position, char in enumerate(token[1:], start=1):
        if char in short_values:
            return position == len(token) - 1
    return False


def _resolve_long_flag(flag: str, long_flags: tuple[str, ...]) -> Optional[str]:
    """The single long flag a `--name` token names, by its full spelling or by an
    unambiguous abbreviation of it, or None when it names none of them.

    long_flags holds the wrapper's value and boolean long flags together, because
    getopt_long resolves a token against every option the tool declares at once. An
    exact match wins over any longer option the token also abbreviates, so `sudo
    --login` is the boolean long form of `-i` rather than an abbreviation of
    `--login-class`. Otherwise any prefix matching a single option names that option,
    so `nice --adj` is `--adjustment`, and a prefix matching several names none of
    them, which is what the tool itself reports."""
    if flag in long_flags:
        return flag
    if len(flag) <= 2:
        return None
    matches = [candidate for candidate in long_flags if candidate.startswith(flag)]
    return matches[0] if len(matches) == 1 else None


def _runs_no_command(
    token: str,
    no_command: tuple[str, ...],
    short_values: set[str],
    long_flags: tuple[str, ...],
) -> bool:
    """Whether a flag token is one of the wrapper's flags that run no command.

    A short flag counts anywhere in its cluster up to the first value flag, because
    the letters behind that one are its value rather than further flags. A long flag
    counts through the same abbreviation rule as the rest of the walk, so `sudo --edi`
    is `--edit`."""
    if not no_command:
        return False
    short = {flag[1] for flag in no_command if len(flag) == 2}
    if token.startswith("--"):
        return _resolve_long_flag(token.partition("=")[0], long_flags) in no_command
    for char in token[1:]:
        if char in short:
            return True
        if char in short_values:
            break
    return False


def _resolved_name(token: str) -> str:
    """The plain command name a single command word names, its quoting resolved and
    its path removed, so `"/usr/bin/nice"` reads as `nice`."""
    return token_name(unquote_word(token))


def token_name(token: str) -> str:
    """The basename of an already split command token, so `/opt/homebrew/bin/gh` and
    `gh` both resolve to "gh".

    A check that compares the first token of a command to a tool name resolves it
    through this, or through command_name when it still holds the raw string, so an
    absolute path does not bypass it. Every hook that gates on a tool name now does,
    secret_guard's own commit credential scan through strip_global_git_options
    included: strip_global_git_options resolves the git basename itself, and
    secret_guard's main also runs every part through normalize_command_part before
    any check, so a wrapper prefix never reaches that scan either."""
    return os.path.basename(token)


def command_name(part: str) -> str:
    """The plain name of the command part runs, so `/opt/homebrew/bin/gh`, `gh` and
    `"/opt/homebrew/bin/gh"` all resolve to "gh".

    The first word is taken with the quoting respected and then resolved through
    unquote_word, because a quoted binary name runs the same binary as the bare one
    and every check that gates on this name has to see it."""
    tokens = shell_words(part)
    if not tokens:
        return ""
    return _resolved_name(tokens[0])


def normalize_command_part(part: str) -> str:
    """part with its wrapper prefixes removed and its command name reduced to the plain
    basename, so `mise exec -- /usr/bin/git push --force origin main` becomes
    `git push --force origin main` and a check anchored on the tool name matches it.

    strip_wrappers removes the leading `NAME=value` assignments, `env`, `mise exec --`
    and the wrappers it lists, their own flags included. The first word of what remains
    is replaced by the plain command name through command_name, its quoting resolved,
    so `"/usr/bin/git" push` normalises like the bare spelling.

    Only the first word is rewritten and no argument loses a character, but the part is
    rebuilt from its words, so a run of whitespace between two of them collapses to a
    single space. A caller that needs the original spacing reads the raw part instead.

    A hook whose checks expect the literal tool name calls this once in front of them
    rather than resolving the name again in every rule.
    """
    stripped = strip_wrappers(part)
    tokens = shell_words(stripped)
    if not tokens:
        return stripped
    return " ".join([command_name(stripped), *tokens[1:]])


def shell_tokens(part: str) -> list[str]:
    """part split into tokens the way a shell splits it, quotes resolved. [] when the
    quoting does not parse, so a caller never has to guard the split itself."""
    try:
        return shlex.split(part)
    except ValueError:
        return []


# Tools these hooks police closely enough that malformed quoting around their
# arguments must not silently pass the command through unexamined.
POLICED_COMMANDS = frozenset(
    {
        "gh",
        "tofu",
        "bao",
        "vault",
        "bws",
        "bw",
        "kubectl",
        "git",
        "cat",
        "head",
        "tail",
        "less",
        "grep",
        "echo",
        "printf",
        "printenv",
        "env",
    }
)


def malformed_quoting_violation(part: str) -> Optional[str]:
    """The deny reason when part names a policed command but its own quoting does not
    parse, so none of the tokenised checks that police that command can see what it
    actually runs.

    shell_tokens returns [] on a ValueError the same way it does for an empty or flag
    only command, so a caller that only checks "did a specific violation match" would
    silently let a malformed, unparseable command through unexamined. This runs first,
    before any of those checks, and catches that case instead.
    """
    if command_name(part) not in POLICED_COMMANDS:
        return None
    try:
        shlex.split(part)
    except ValueError:
        return (
            f"{part!r} does not parse as a shell command, the quoting is unbalanced, "
            "so this hook cannot verify it is safe. Fix the quoting."
        )
    return None


def subcommand_tokens(
    tokens: list[str],
    value_flags: Collection[str] = (),
    space_form_takes_value: bool = False,
) -> list[str]:
    """tokens from the subcommand onwards, the flags placed in front of it skipped.

    tokens are the arguments after the command name or its noun, so `gh label -R
    owner/repo create bug` passes ["-R", "owner/repo", "create", "bug"] and the result
    starts at "create". Returns [] when tokens name no subcommand at all.

    A check anchored on `<tool> <noun> <subcommand>` misses the command entirely when
    the tool accepts a flag in between, which most of them do. Which flags take a
    value is part of each tool's own grammar, so the caller passes it in:

    value_flags are the flags that take the next token as their value. They are
    skipped together with that token. Any other flag is skipped alone, `--flag=value`
    included, because it carries its value in the same token.

    space_form_takes_value says a `--flag` or `-x` that is not in value_flags takes
    the next token as its value as well. cobra based tools such as `gh` look up the
    subcommand that way: a flag they do not know at the noun level swallows the
    following token, which is how a flag of the target subcommand can sit in front of
    it.

    The grammar is generic, so a boolean flag that takes no value in this mode
    swallows the token behind it. kubectl has exactly four such global flags,
    `--disable-compression`, `--insecure-skip-tls-verify`, `--match-server-version`
    and `--warnings-as-errors`, all of them presence-only booleans that default to
    false, so their absence rather than their presence is the secure default. No
    caller can tell this walk that a particular flag never takes a value: value_flags
    records the opposite. A caller that needs one of them walked correctly drops it
    from the tokens before calling, and a case that bites in practice is the point to
    add a boolean_flags collection here instead.

    Everything after `--` is an operand rather than a subcommand, so a `--` ends the
    search.
    """
    values = set(value_flags)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return []
        if not token.startswith("-"):
            return tokens[index:]
        takes_value = token in values or (
            space_form_takes_value
            and "=" not in token
            and (token.startswith("--") or len(token) == 2)
        )
        index += 2 if takes_value else 1
    return []


def subcommand_after(
    tokens: list[str],
    value_flags: Collection[str] = (),
    space_form_takes_value: bool = False,
) -> str:
    """The subcommand in tokens, the flags in front of it skipped. "" when tokens name
    none. See subcommand_tokens for the flag grammar the arguments describe."""
    found = subcommand_tokens(tokens, value_flags, space_form_takes_value)
    return found[0] if found else ""


def gh_dispatch(tokens: list[str]) -> list[str]:
    """tokens from gh's own subcommand onwards, a noun such as "pr" or "label" or a
    command such as "api", the flags placed in front of it skipped.

    gh is built on cobra, which applies the same lookup at every level of its command
    tree, the root included: it skips the flags in front of the subcommand and treats a
    flag it does not know at that level as taking the following token as its value. So
    `gh --repo owner/repo secret list` and `gh --method PATCH api repos/o/r/rulesets/1`
    both dispatch past the flag, and the rule subcommand_tokens already applies one
    level down applies here too.

    Returns [] when tokens do not start with "gh" or name no subcommand at all. The
    first token is resolved to its basename, so `/opt/homebrew/bin/gh` dispatches like
    `gh`.
    """
    if not tokens or token_name(tokens[0]) != "gh":
        return []
    return subcommand_tokens(tokens[1:], space_form_takes_value=True)


def strip_global_git_options(part: str) -> tuple[str, Optional[str]]:
    """Normalises global git options out of a command part whose command is git.

    Strips `-C <path>`, `--git-dir=<x>`, `--git-dir <x>`, `--work-tree=<x>`,
    `--work-tree <x>` and `-c <key>=<value>`, so `git -C /path push origin main` becomes
    `git push origin main`. Returns the normalised text and the `-C` path, when one was
    given, so repository dependent checks can run against that path instead of cwd.

    The first token is resolved to its basename through token_name, for the comparison
    and in the returned text, so `/usr/bin/git commit -m x` normalises to
    `git commit -m x` and a caller anchored on the literal `git` prefix matches it.
    """
    tokens = part.split()
    if not tokens or token_name(tokens[0]) != "git":
        return part, None

    path: Optional[str] = None
    kept: list[str] = [token_name(tokens[0])]
    index = 1
    while index < len(tokens):
        token = tokens[index]

        if token == "-C":
            if index + 1 < len(tokens):
                path = tokens[index + 1]
            index += 2
            continue
        if token.startswith("-C") and len(token) > 2:
            path = token[2:]
            index += 1
            continue
        if token in ("--git-dir", "--work-tree", "-c"):
            index += 2
            continue
        if token.startswith("--git-dir=") or token.startswith("--work-tree="):
            index += 1
            continue

        kept.append(token)
        index += 1

    return " ".join(kept), path


def run_git(args: list[str], cwd: Optional[str]) -> Optional[str]:
    """Runs git with args in cwd. Returns stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_root(cwd: Optional[str]) -> Optional[str]:
    """The repository root for cwd, or None when cwd is not inside a git repository."""
    return run_git(["rev-parse", "--show-toplevel"], cwd)


def agent_skills_config(root: Optional[str]) -> dict[str, Any]:
    """Reads .agent-skills.json from the repository root. {} when absent or invalid."""
    if not root:
        return {}
    path = os.path.join(root, ".agent-skills.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def default_branch(cwd: Optional[str]) -> str:
    """The repository's default branch name, detected from the checkout in cwd.

    Tries the remote's HEAD symref first, then falls back to main or master, whichever
    exists as a local branch. Defaults to "main" when nothing can be determined.
    """
    ref = run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
    if ref:
        return ref.rsplit("/", 1)[-1]

    listing = run_git(["branch", "--list"], cwd) or ""
    names = {line.strip("* ").strip() for line in listing.splitlines()}
    for candidate in ("main", "master"):
        if candidate in names:
            return candidate
    return "main"


TMPDIR_REFERENCE = re.compile(r"\$\{TMPDIR\}|\$TMPDIR\b")
CD_WORDS = frozenset({"cd", "pushd", "popd", "chdir"})
CD_SKIPPED_FLAGS = frozenset({"--", "-P", "-L", "-e", "-@"})
DIRECTORY_REDIRECT_FLAGS = ("--git-dir", "--work-tree", "--chdir")
DIRECTORY_REDIRECT_ENV = re.compile(r"^(GIT_DIR|GIT_WORK_TREE)=")


def scratch_roots() -> list[str]:
    """The directories that count as the session scratch scope: $TMPDIR, resolved.

    The sandbox points $TMPDIR at the session scratch directory, and a throwaway
    fixture lives below it. An unset or relative $TMPDIR gives no scope, and so do the
    filesystem root and the home directory, which would swallow a real repository.
    """
    value = os.environ.get("TMPDIR", "")
    if not value or not os.path.isabs(value):
        return []
    root = os.path.realpath(value)
    if root in (os.sep, os.path.realpath(os.path.expanduser("~"))):
        return []
    return [root]


def resolve_dir(path: str, base: Optional[str]) -> Optional[str]:
    """The absolute, symlink free path that path names, a relative one read against
    base. A leading `$TMPDIR` or `${TMPDIR}` is expanded. None when the path holds
    anything else a shell expands (a variable, a command substitution, `~`, a glob) or
    is relative while base is unknown, because then the real location is not known.
    """
    text = path.strip().strip("'\"")
    if not text:
        return None
    tmpdir = os.environ.get("TMPDIR", "")
    if tmpdir:
        text = TMPDIR_REFERENCE.sub(tmpdir, text)
    if any(char in text for char in "$`~*?[{"):
        return None
    if not os.path.isabs(text):
        if base is None:
            return None
        text = os.path.join(base, text)
    return os.path.realpath(text)


def in_scratch(path: Optional[str]) -> bool:
    """Whether path, already resolved, lies inside the session scratch scope."""
    if not path:
        return False
    real = os.path.realpath(path)
    return any(os.path.commonpath([root, real]) == root for root in scratch_roots())


def part_dirs(command: str, cwd: Optional[str]) -> list[tuple[str, Optional[str]]]:
    """Each command part of command with the directory it runs in, None when that is
    not known.

    The directory starts at cwd and follows a leading `cd <literal path>` through the
    parts in order, so `cd $TMPDIR/fixture && git commit` runs the commit in the
    fixture. It becomes unknown, and stays unknown, after a `cd` the walk cannot
    resolve (a variable, `cd -`, no operand), a `pushd`, `popd` or `chdir`, a `cd`
    that is not the first word of its part such as a subshell or a group, and a
    `GIT_DIR` or `GIT_WORK_TREE` assignment, which points git elsewhere. Unknown never
    counts as scratch, so every such command is policed as it was.

    The scope fails closed. A `cd` target that does not exist when the hook runs leaves
    the directory unknown, because the command may create it or a link first. A command
    that fails scope_tainted has no known directory in any of its parts.
    """
    current: Optional[str] = os.path.realpath(cwd) if cwd else None
    result: list[tuple[str, Optional[str]]] = []
    tainted = scope_tainted(command)
    for raw in command_parts(command):
        if tainted:
            result.append((raw, None))
            continue
        words = shell_words(raw)
        names = [unquote_word(word).strip("(){}!") for word in words]
        leading = unquote_word(words[0]) if words else ""
        if any(DIRECTORY_REDIRECT_ENV.match(name) for name in names):
            current = None
        elif leading == "cd":
            operands = [word for word in words[1:] if unquote_word(word) not in CD_SKIPPED_FLAGS]
            if len(operands) == 1 and unquote_word(operands[0]) != "-":
                current = existing_dir(resolve_dir(unquote_word(operands[0]), current))
            else:
                current = None
        elif any(name in CD_WORDS for name in names):
            current = None
        result.append((raw, current))
    return result


def git_part_dir(raw_part: str, directory: Optional[str], git_path: Optional[str]) -> Optional[str]:
    """The directory a git command part acts on: its `-C` path read against directory,
    else directory. None when the part points git somewhere this cannot follow: a
    second `-C`, `--git-dir`, `--work-tree`, `--chdir`, `sudo -D`, `-c core.worktree` or a
    `GIT_DIR` or `GIT_WORK_TREE` assignment.
    """
    if directory is None:
        return None
    tokens = [unquote_word(token) for token in shell_words(raw_part)]
    for token in tokens:
        if (
            token in ("-D", *DIRECTORY_REDIRECT_FLAGS)
            or token.startswith(tuple(flag + "=" for flag in DIRECTORY_REDIRECT_FLAGS))
            or DIRECTORY_REDIRECT_ENV.match(token)
            or token.lower().startswith("core.worktree")
        ):
            return None
    if sum(1 for token in tokens if token == "-C" or token.startswith("-C")) > 1:
        return None
    if git_path is not None:
        return existing_dir(resolve_dir(git_path, directory))
    return directory


def existing_dir(path: Optional[str]) -> Optional[str]:
    """path when it names a directory that exists now, else None, so a target the
    command itself may create or link later never counts as a known location."""
    return path if path is not None and os.path.isdir(path) else None


SYMLINK_COMMANDS = frozenset({"ln", "link"})
TMPDIR_WRITE = re.compile(r"(?<![${\w])TMPDIR\b|\$\{TMPDIR[^}]")


def scope_tainted(command: str) -> bool:
    """Whether command can change what the session scratch scope means while it runs,
    so no part of it may rely on that scope.

    True for a part that does not parse as shell words, one that creates a symbolic
    link (`ln`, `link`, anything naming a symlink), and one that names `TMPDIR` other
    than as a plain `$TMPDIR` or `${TMPDIR}` read, such as `TMPDIR=x`, `export TMPDIR`
    or `${TMPDIR:=x}`. Callers then apply the repository rules as before.
    """
    for raw in command_parts(command):
        try:
            shlex.split(raw)
        except ValueError:
            return True
        if TMPDIR_WRITE.search(raw) or "symlink" in raw.lower():
            return True
        for word in shell_words(raw):
            if os.path.basename(unquote_word(word).strip("(){}!")) in SYMLINK_COMMANDS:
                return True
    return False


def run_main(main_func: Any) -> int:
    """Runs main_func. Prints {} and returns 0 on any unexpected exception, so a hook
    never blocks by accident on malformed input or a bug."""
    try:
        return main_func()
    except Exception:
        return emit_empty()


def emit(payload: dict[str, Any]) -> int:
    """Prints payload as the hook's JSON response. Always returns 0."""
    print(json.dumps(payload))
    return 0


def emit_empty() -> int:
    """Prints the empty response: nothing to say, never blocks."""
    print("{}")
    return 0


def deny(event: str, reason: str) -> int:
    """Emits a PreToolUse deny decision with the given reason."""
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def context(event: str, message: str) -> int:
    """Emits additional context for the given hook event."""
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": message,
            }
        }
    )
