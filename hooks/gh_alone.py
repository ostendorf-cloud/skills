#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. On macOS, denies a Bash command that runs `gh` and is not
exactly one `gh` call.

In the macOS sandbox a `gh` call works only when the whole command is that call. Behind
`cd <dir> &&`, in a chain, next to a pipe, in a loop, behind a command substitution or
with a redirection, it fails with `open ~/.config/gh/config.yml: operation not
permitted`, or returns nothing inside a loop. The git_guard rule for `git fetch`, `git
pull` and `git push` has the same shape and the same macOS gate, and this hook follows
it: the command is split into parts with _common.command_parts, a redirection or `&`
outside quotes is read from the quote masked text, and Linux and CI are left alone.

Alone means one command part, no redirection or `&` outside quotes other than a trailing
`2>&1` or `>&2`, and nothing in front of `gh` but `time`, a path and environment
assignments. `env` or another wrapper in front of it is denied.

Leading environment assignments (`GH_TOKEN=... gh api ...`) are allowed. That is
deliberately more lenient than the git rule, which denies an env prefix: the work-review
skill reads the review token into GH_TOKEN for the review call only, and that shape was
never observed to fail.

ASSUMPTION, not verified: the failure was observed with the sandbox profile of this
repository's laptop settings. Whether every listed shape fails was not tested one by
one. Redirection and command substitution are denied on the same reasoning as the chain,
not on an observed failure.

Precision, the same as the other hooks: `gh` counts when it is the command word of a
part, behind loop keywords such as `do` and `then`, or the command word of a `$(...)`,
backtick or `(...)` group. `gh` as text in a quoted argument, a word such as
`./gh-helper` or an argument such as `--grep gh` does not count. Not read: `gh` inside
`bash -c '...'`, behind `xargs`, or inside a quoted `"$(...)"`, and the body of a heredoc
is read as command parts, so a body line that starts with `gh` next to a redirection is a
false positive.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

DENY_REASON = (
    "A gh call works in the sandbox only as the one command of its call, without cd, "
    "chain, pipe, loop, env command, command substitution or redirection. Run gh alone, "
    "use --repo <owner>/<name> instead of cd, --jq instead of a pipe and --body-file "
    "for a multi line body."
)

# The only redirections that keep a call alone, as in git_guard.
KEPT_REDIRECTION = re.compile(r"(?<=\s)(2>&1|>&2)(?=\s|$)")
SHELL_OPERATOR = re.compile(r"[<>&]")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# The keywords that precede a command word without being a command themselves.
LEADING_KEYWORDS = frozenset({"do", "then", "else", "elif", "if", "while", "until", "!", "{"})
# A command word opening a `$(...)`, backtick or `(...)` group, behind assignments.
GROUPED_GH = re.compile(r"[(`]\s*(?:\w+=\S*\s+)*(?:[^\s()`]*/)?gh(?=[\s)`;|&]|$)")


def words_of(part: str) -> list[str]:
    return [_common.unquote_word(word) for word in _common.shell_words(part)]


def without_keywords(part: str) -> str:
    """part without the loop and condition keywords in front of its command word."""
    words = _common.shell_words(part)
    while words and words[0] in LEADING_KEYWORDS:
        words = words[1:]
    return " ".join(words)


def runs_gh(part: str) -> bool:
    """Whether part runs gh as its command, or in a group it opens."""
    if GROUPED_GH.search(_common.mask_quoted(part)):
        return True
    rest = without_keywords(part)
    if not rest:
        return False
    return _common.command_name(_common.normalize_command_part(rest)) == "gh"


def is_plain_gh_call(part: str) -> bool:
    """Whether the first word of part, behind `time` and environment assignments, is gh."""
    words = words_of(part)
    while words and (words[0] == "time" or ENV_ASSIGNMENT.match(words[0])):
        words = words[1:]
    return bool(words) and _common.token_name(words[0]) == "gh"


def stands_alone(command: str, parts: list[str]) -> bool:
    if len(parts) != 1:
        return False
    masked = KEPT_REDIRECTION.sub("", _common.mask_quoted(command))
    if SHELL_OPERATOR.search(masked) or GROUPED_GH.search(masked):
        return False
    return is_plain_gh_call(parts[0])


def main() -> int:
    if sys.platform != "darwin":
        return _common.emit_empty()
    payload = _common.read_payload()
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return _common.emit_empty()

    parts = _common.command_parts(command)
    if not any(runs_gh(part) for part in parts):
        return _common.emit_empty()
    if stands_alone(command, parts):
        return _common.emit_empty()
    return _common.deny(EVENT, DENY_REASON)


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
