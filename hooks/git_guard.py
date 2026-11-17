#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a push to the default branch, unless the remote
carries no branch at all yet, a force push without `--force-with-lease` or one onto the
default branch, `git push --all` or `--mirror`, a command that bypasses hooks or commit
signing, and deletion of the default branch, local or remote. On macOS it also denies
a `git fetch`, `git pull` or `git push` that does not stand alone in its call, because
only a lone command leaves the sandbox (ADR 0005).

These rules apply to every git call in the command: behind global options, wrappers or
grouping, inside a command substitution, and in a string handed to a shell or `eval`.
"""

import os
import re
import shlex
import subprocess
import sys
from typing import NamedTuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GIT_PUSH = re.compile(r"^git\s+push\b")
GIT_BRANCH = re.compile(r"^git\s+branch\s+")
BYPASS_FLAGS = re.compile(r"--no-verify\b|--no-gpg-sign\b|-c\s+commit\.gpgsign=false")

USE_FEATURE_BRANCH = "Push a feature branch and open a pull request instead."
USE_FORCE_WITH_LEASE = (
    "Use --force-with-lease on a feature branch, it fails when the remote moved since "
    "the last fetch."
)

LS_REMOTE_TIMEOUT = 5

# Caches remote_is_empty by (remote, cwd) for the duration of one hook run, so a
# command chaining several pushes to the default branch against the same remote asks
# it once. The caller creates one of these per invocation and threads it through,
# rather than a module level cache, so nothing needs resetting between hook runs or
# between tests that call these functions directly.
RemoteCache = dict[tuple[str, Optional[str]], Optional[bool]]


def current_branch(cwd: Optional[str]) -> str:
    """The checked out branch in cwd, or "" when it cannot be determined."""
    return _common.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd) or ""


def refspec_target(token: str, cwd: Optional[str]) -> tuple[str, bool]:
    """Resolves one push refspec token to its destination branch name and whether a
    leading "+" marks it as a force push to that target."""
    forced = token.startswith("+")
    if forced:
        token = token[1:]

    if ":" in token:
        src, dst = token.split(":", 1)
    else:
        src, dst = token, ""

    if not dst:
        dst = current_branch(cwd) if src in ("", "HEAD", "@") else src

    dst = dst[len("refs/heads/") :] if dst.startswith("refs/heads/") else dst
    return dst, forced


def has_forced_refspec(tokens: list[str]) -> bool:
    """Whether any refspec (after the remote name) carries a leading "+", git's own
    force push marker."""
    non_flag = [token for token in tokens if not token.startswith("-")]
    return any(token.startswith("+") for token in non_flag[1:])


def remote_is_empty(remote: str, cwd: Optional[str], cache: RemoteCache) -> Optional[bool]:
    """Whether remote carries no branch at all, checked with `git ls-remote --heads`.

    True or False when the remote answered. None when the check itself failed, timed
    out or could not reach the remote, so a caller falls back to denying rather than
    treat an error as "empty" and open the gate.

    Checks every branch on the remote, not only the default one: a remote already
    holding some other branch is not the brand new, empty remote the exemption is for,
    even when the default branch itself is still absent from it.

    Sets GIT_TERMINAL_PROMPT=0 and an empty GIT_ASKPASS so a remote that would ask for
    credentials fails fast instead of prompting from inside a hook.

    cache holds the result per (remote, cwd) for the rest of this call: a command that
    names the same remote more than once asks it only the first time.
    """
    key = (remote, cwd)
    if key in cache:
        return cache[key]

    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="")
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", remote],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT,
            env=env,
        )
        empty = None if result.returncode != 0 else not result.stdout.strip()
    except Exception:
        empty = None

    cache[key] = empty
    return empty


def push_remote(tokens: list[str], cwd: Optional[str]) -> str:
    """The remote a `git push` with these tokens (after "push") reaches.

    The first non flag token when one is given, a URL included. Otherwise git's own
    resolution order for the current branch: `branch.<name>.pushRemote`, then
    `remote.pushDefault`, then `branch.<name>.remote`, then "origin".
    """
    non_flag = [token for token in tokens if not token.startswith("-")]
    if non_flag:
        return non_flag[0]

    branch = current_branch(cwd)
    if branch:
        push_remote_cfg = _common.run_git(["config", f"branch.{branch}.pushRemote"], cwd)
        if push_remote_cfg:
            return push_remote_cfg

    push_default = _common.run_git(["config", "remote.pushDefault"], cwd)
    if push_default:
        return push_default

    if branch:
        configured = _common.run_git(["config", f"branch.{branch}.remote"], cwd)
        if configured:
            return configured

    return "origin"


def push_targets_default(tokens: list[str], cwd: Optional[str], default: str) -> bool:
    """Whether a `git push` with these tokens (after "push") reaches the default branch."""
    non_flag = [token for token in tokens if not token.startswith("-")]

    for token in non_flag[1:]:
        target, _ = refspec_target(token, cwd)
        if target == default:
            return True

    if len(non_flag) <= 1:
        return current_branch(cwd) == default

    return False


SCP_LIKE_URL = re.compile(r"^[^/]*:")


def remote_is_scratch_local(remote: str, directory: str) -> bool:
    """Whether remote, as seen from the repository in directory, is a local path inside
    the session scratch scope.

    A configured remote name is read through `git remote get-url --push`, so a
    `pushurl` and an `insteadOf` rewrite count. A network URL, an scp style address and
    a transport helper never qualify. A relative path is read against the repository
    root, and the path is resolved, so a symlink or `..` out of the scratch scope does
    not qualify either.
    """
    url = _common.run_git(["remote", "get-url", "--push", remote], directory) or remote
    if url.startswith("file://"):
        url = url[len("file://") :]
    elif "://" in url or SCP_LIKE_URL.match(url):
        return False
    base = _common.run_git(["rev-parse", "--show-toplevel"], directory) or directory
    return _common.in_scratch(_common.resolve_dir(url, base))


REMOTE_CONFIG_PREFIXES = ("remote.", "url.", "-cremote.", "-curl.", "git_config", "--config-env")


def changes_remote_config(command: str) -> bool:
    """Whether command, anywhere in it, can change where a push goes: a `git remote` or
    `git config` call, a `-c remote.*` or `-c url.*` option, `--config-env`, a
    `GIT_CONFIG*` variable or a mention of `.git/config`.

    The scratch exemption reads the remote before the command runs, so a command that
    rewrites it first would be judged on the old value. Such a command gets the
    repository rule instead. A part that does not parse counts as changing it."""
    for call in git_calls(command, None):
        sub_index = git_subcommand_index(call.words, 0)
        if sub_index is not None and call.words[sub_index] in ("remote", "config"):
            return True
    for raw in _common.command_parts(command):
        tokens = _common.shell_tokens(raw)
        if not tokens and raw.strip():
            return True
        normalized, _ = _common.strip_global_git_options(_common.normalize_command_part(raw))
        if normalized.startswith(("git remote", "git config")):
            return True
        if ".git/config" in raw:
            return True
        if any(token.lower().startswith(REMOTE_CONFIG_PREFIXES) for token in tokens):
            return True
    return False


def push_violation(
    part: str,
    cwd: Optional[str],
    default: str,
    remote_cache: RemoteCache,
    scratch_dir: Optional[str] = None,
) -> Optional[str]:
    """The deny reason for a `git push` part, or None when it is fine."""
    if not GIT_PUSH.match(part):
        return None

    tokens = part.split()[2:]

    if "--all" in tokens:
        return f"This pushes every local branch, including {default}. {USE_FEATURE_BRANCH}"

    if "--mirror" in tokens:
        return f"This mirrors every ref to the remote, including {default}. {USE_FEATURE_BRANCH}"

    non_flag = [token for token in tokens if not token.startswith("-")]
    if "--delete" in tokens and default in non_flag:
        return f"This deletes {default} on the remote. The default branch is never deleted."

    # The force and lease checks never depend on the default branch exemption below:
    # a plain force push is denied outright, whatever ref it also names, so a command
    # that forces one branch while also naming the still-missing default branch (for
    # example "git push --force origin feature main") is still caught here.
    has_plain_force = any(token in ("--force", "-f") for token in tokens) or has_forced_refspec(
        tokens
    )
    if has_plain_force:
        return f"This force pushes without --force-with-lease. {USE_FORCE_WITH_LEASE}"

    if push_targets_default(tokens, cwd, default):
        remote = push_remote(tokens, cwd)
        # A fixture repository under the session scratch scope pushing to a bare remote
        # in that same scope is outside the rule. A remote anywhere else is not.
        if scratch_dir and remote_is_scratch_local(remote, scratch_dir):
            return None
        empty = remote_is_empty(remote, cwd, remote_cache)
        if empty is True:
            return None
        detail = (
            "the first push exemption needs a remote with no branch at all"
            if empty is False
            else "the first push exemption could not be checked"
        )
        return (
            f"Inside a repository this pushes to {default}, the default branch, and "
            f"{detail}. {USE_FEATURE_BRANCH}"
        )

    return None


def branch_delete_violation(part: str, default: str) -> Optional[str]:
    """The deny reason for a `git branch` part that deletes the default branch."""
    if not GIT_BRANCH.match(part):
        return None

    tokens = part.split()[2:]
    if not any(token in ("-D", "-d", "--delete") for token in tokens):
        return None

    names = [token for token in tokens if not token.startswith("-")]
    if default in names:
        return f"This deletes the local branch {default}, the default branch. It is never deleted."

    return None


def bypass_violation(part: str) -> Optional[str]:
    """The deny reason when part skips hooks or commit signing."""
    if BYPASS_FLAGS.search(part):
        return (
            "This bypasses git hooks or commit signing. Run the command without "
            "--no-verify, --no-gpg-sign or -c commit.gpgsign=false."
        )
    return None


NETWORK_SUBCOMMANDS = ("fetch", "pull", "push")
SHELL_OPERATOR = re.compile(r"[<>&]")
# The only redirections that keep the call outside the sandbox, measured.
KEPT_REDIRECTION = re.compile(r"(?<=\s)(2>&1|>&2)(?=\s|$)")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")

RUN_NETWORK_ALONE = (
    "A git fetch, pull or push leaves the sandbox only when it stands alone in the call, "
    "without a pipe, chain, cd, -C, env prefix, global option before the subcommand or "
    "redirection other than 2>&1. Otherwise it runs inside the sandbox and fails with a "
    "host key error, so run it alone from the worktree directory."
)


def network_shape_violation(
    command: str,
    raw_part: str,
    normalized: str,
    git_path: Optional[str],
    scratch_dir: Optional[str] = None,
) -> Optional[str]:
    """The deny reason when a `git fetch`, `git pull` or `git push` does not stand alone
    in its call, None when it does or when the check does not apply.

    The sandbox exclusion that lets these commands reach an SSH remote exists only on
    macOS (ADR 0005), so the check is gated on it. On Linux and in CI nothing is lost
    by a pipe or a chain.

    Alone means, measured: one command part (no pipe, chain, newline or leading cd), no
    `-C` path, no env assignment or `env` before git, no global option between git and
    the subcommand, and no redirection or `&` outside quotes except a trailing `2>&1`
    or `>&2`. A `time` prefix is fine.

    A command in the session scratch scope whose remote is itself scratch local is
    exempt: such a push is a local file copy and works in the sandbox.

    Accepted false positives: an unquoted heredoc body line starting with `git push`
    reads as a command part, and an escaped `\\&` in an argument reads as an operator.
    """
    if sys.platform != "darwin":
        return None

    words = shell_words_of(raw_part)
    git_index = next((i for i, w in enumerate(words) if _common.token_name(w) == "git"), None)
    if git_index is None:
        return None
    sub_index = git_subcommand_index(words, git_index)
    if sub_index is None or words[sub_index] not in NETWORK_SUBCOMMANDS:
        return None

    if scratch_dir:
        tokens = words[sub_index + 1 :]
        if remote_is_scratch_local(push_remote(tokens, scratch_dir), scratch_dir):
            return None

    prefix_ok = not any(
        ENV_ASSIGNMENT.match(word) or _common.token_name(word) == "env"
        for word in words[:git_index]
    )
    subcommand_next = sub_index == git_index + 1
    masked = KEPT_REDIRECTION.sub("", _common.mask_quoted(command))
    alone = (
        len(_common.command_parts(command)) == 1
        and git_path is None
        and prefix_ok
        and subcommand_next
        and not SHELL_OPERATOR.search(masked)
    )
    return None if alone else RUN_NETWORK_ALONE


# The global options git reads its value for from the next word, measured against
# git's own option parser: `-C`, `-c`, `--git-dir`, `--work-tree`, `--namespace`,
# `--config-env` and `--attr-source`. Every other global option is a single word.
# `--exec-path` without `=` prints a path and runs no subcommand.
GLOBAL_OPTIONS_WITH_VALUE = (
    "-c",
    "-C",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
    "--attr-source",
)


def git_subcommand_index(words: list[str], git_index: int) -> Optional[int]:
    """The index of the git subcommand in words, skipping the global options after the
    git word and the value of those that take one in a separate word."""
    index = git_index + 1
    while index < len(words):
        word = words[index]
        if not word.startswith("-"):
            return index
        index += 2 if word in GLOBAL_OPTIONS_WITH_VALUE else 1
    return None


def shell_words_of(part: str) -> list[str]:
    """The words of part with their quoting resolved."""
    return [_common.unquote_word(word) for word in _common.shell_words(part)]


GUARDED_SUBCOMMANDS = ("push", "branch")
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "su"})
SHELL_VALUE_FLAGS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
SHELL_COMMAND_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
NESTING_LIMIT = 8
# Characters a shell reads as grouping or substitution in front of a command word.
COMMAND_PREFIX_CHARS = "({!$<>`"
WORD_END = re.compile(r"[<>&)`]")
OPERATOR_ONLY = re.compile(r"\d*[<>&]+")
REDIRECTION = re.compile(r"^\d*(?:[<>]|&>)")
HEREDOC_OPERATOR = re.compile(r"(?<!<)<<(?!<)")
HEREDOC_WORD = re.compile(r"(-?)[ \t]*([^\s;&|<>()]+)")

XARGS_PUSH = (
    "A git push behind xargs takes refs this hook cannot check. Run git push with its "
    "refs written out in the command."
)


class GitCall(NamedTuple):
    """One git call found in a command.

    words: the words from git on, quoting resolved, with a `-c alias.*` expanded.
    raw: the command part the call was found in.
    directory: the directory that part runs in, None when not known.
    behind_xargs: whether xargs runs it, so stdin may add arguments.
    """

    words: list[str]
    raw: str
    directory: Optional[str]
    behind_xargs: bool


def git_calls(command: str, cwd: Optional[str]) -> list[GitCall]:
    """Every git call command makes, wherever git stands in it.

    A word naming git counts in any position of a command part, so a wrapper, a group,
    a subshell or a control keyword in front of it does not hide the call. Command
    substitutions, a string after a shell's `-c`, the arguments of `eval` and a `-c
    alias.*` starting with `!` are read as commands of their own. When the command runs
    a shell that reads its commands from stdin, every word and heredoc body of the
    command is read as one too. A backslash newline joins two lines, as in the shell.

    Accepted false positives: a word `git` that is an argument, such as in `echo git push
    --force`, reads as a call.
    """
    return _calls_in(command.replace("\\\n", ""), cwd, 0, set())


def _calls_in(text: str, cwd: Optional[str], depth: int, seen: set[str]) -> list[GitCall]:
    """The git calls in text. cwd is the directory text runs in, None when not known."""
    if depth > NESTING_LIMIT or text in seen:
        return []
    seen.add(text)
    text, bodies = split_heredocs(text)
    if depth == 0:
        pairs = _common.part_dirs(text, cwd)
    else:
        pairs = [(part, None) for part in _common.command_parts(text)]

    calls: list[GitCall] = []
    nested: list[str] = []
    reads_stdin = False
    for raw, directory in pairs:
        words = _common.shell_words(raw)
        for index, word in enumerate(words):
            if command_word_name(word) != "git":
                continue
            behind_xargs = any(command_word_name(before) == "xargs" for before in words[:index])
            call_words, alias_command = git_call_words(words[index + 1 :])
            calls.append(GitCall(call_words, raw, directory, behind_xargs))
            if alias_command:
                nested.append(alias_command)
        inner, stdin = inner_commands(raw, words)
        nested.extend(inner)
        reads_stdin = reads_stdin or stdin

    for body, quoted in bodies:
        if not quoted:
            nested.extend(substitutions(body))
    if reads_stdin:
        nested.extend(body for body, _ in bodies)
        for raw, _ in pairs:
            nested.extend(shell_words_of(raw))

    for inner_text in nested:
        calls.extend(_calls_in(inner_text, None, depth + 1, seen))
    return calls


def command_word_name(word: str) -> str:
    """The command name word names, its quoting resolved and any grouping or
    substitution characters in front of it removed, so `(git` and `$(git` read as git."""
    return _common.token_name(_common.unquote_word(word).lstrip(COMMAND_PREFIX_CHARS))


def git_call_words(after: list[str]) -> tuple[list[str], Optional[str]]:
    """The words of a git call, from the words after the git word, and the command a
    `-c alias.*` starting with `!` runs instead, None when there is none.

    Quoting is resolved. The call ends at a word holding an unquoted `)` or backtick,
    which closes the group or substitution it runs in, and at a lone `&`. A redirection
    and its target are dropped, so `main>/dev/null` reads as `main`.
    """
    words = ["git"]
    skip_next = False
    for word in after:
        if skip_next:
            skip_next = False
            continue
        end = WORD_END.search(_common.mask_quoted(word))
        if end is None:
            words.append(_common.unquote_word(word))
            continue
        prefix, rest = word[: end.start()], word[end.start() :]
        if prefix and not (prefix.isdigit() and rest[0] in "<>"):
            words.append(_common.unquote_word(prefix))
        if rest[0] in ")`" or (rest[0] == "&" and not rest.startswith("&>")):
            break
        skip_next = bool(OPERATOR_ONLY.fullmatch(rest))
    return expand_alias(words)


def expand_alias(words: list[str]) -> tuple[list[str], Optional[str]]:
    """words with a subcommand that a `-c alias.<name>=<value>` in front of it defines
    replaced by that value, and the shell command an alias starting with `!` runs."""
    sub_index = git_subcommand_index(words, 0)
    if sub_index is None:
        return words, None
    aliases: dict[str, str] = {}
    index = 1
    while index < sub_index:
        if words[index] == "-c" and index + 1 < sub_index:
            key, separator, value = words[index + 1].partition("=")
            if separator and key.lower().startswith("alias."):
                aliases[key[len("alias.") :].lower()] = value
        index += 2 if words[index] in GLOBAL_OPTIONS_WITH_VALUE else 1
    value = aliases.get(words[sub_index].lower())
    if value is None:
        return words, None
    arguments = words[sub_index + 1 :]
    if value.startswith("!"):
        return words, " ".join([value[1:], *(shlex.quote(word) for word in arguments)])
    return [*words[:sub_index], *value.split(), *arguments], None


def inner_commands(raw: str, words: list[str]) -> tuple[list[str], bool]:
    """The command strings raw runs inside itself, and whether it runs a shell that
    reads its commands from stdin.

    Inner commands are the command substitutions, the words after a shell's `-c` and
    the arguments of `eval`, joined."""
    inner = substitutions(raw)
    reads_stdin = False
    for index, word in enumerate(words):
        name = command_word_name(word)
        later = [_common.unquote_word(other) for other in words[index + 1 :]]
        if name == "eval":
            inner.append(" ".join(later))
        elif name in SHELLS:
            if any(SHELL_COMMAND_FLAG.match(other) for other in later):
                inner.extend(later)
            elif shell_reads_stdin(later):
                reads_stdin = True
    return inner, reads_stdin


def shell_reads_stdin(arguments: list[str]) -> bool:
    """Whether a shell with these arguments reads its commands from stdin: no script
    operand, `-s`, or `-` or `/dev/stdin` as the operand."""
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument in SHELL_VALUE_FLAGS:
            skip_next = True
            continue
        if REDIRECTION.match(argument):
            skip_next = bool(OPERATOR_ONLY.fullmatch(argument))
            continue
        if argument == "-s":
            return True
        if argument.startswith(("-", "+")) and argument != "-":
            continue
        return argument in ("-", "/dev/stdin")
    return True


def substitutions(text: str) -> list[str]:
    """The commands inside the `$(...)`, `<(...)`, `>(...)` and backtick substitutions of
    text, outside single quotes. One left open runs to the end of text."""
    found: list[str] = []
    index = 0
    single = double = False
    while index < len(text):
        char = text[index]
        if single:
            single = char != "'"
            index += 1
        elif char == "\\":
            index += 2
        elif char == "'" and not double:
            single = True
            index += 1
        elif char == '"':
            double = not double
            index += 1
        elif char in "$<>" and text[index + 1 : index + 2] == "(":
            end = _substitution_end(text, index + 2)
            found.append(text[index + 2 : end])
            index = end + 1
        elif char == "`":
            end = _backtick_end(text, index + 1)
            found.append(text[index + 1 : end])
            index = end + 1
        else:
            index += 1
    return found


def _substitution_end(text: str, start: int) -> int:
    """The index of the `)` that closes a substitution whose command starts at start,
    quotes and nested substitutions respected. len(text) when it stays open."""
    depth = 1
    index = start
    single = double = False
    while index < len(text):
        char = text[index]
        if single:
            single = char != "'"
        elif char == "\\":
            index += 2
            continue
        elif char == "`":
            index = _backtick_end(text, index + 1) + 1
            continue
        elif char == "$" and text[index + 1 : index + 2] == "(":
            index = _substitution_end(text, index + 2) + 1
            continue
        elif double:
            double = char != '"'
        elif char == "'":
            single = True
        elif char == '"':
            double = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text)


def _backtick_end(text: str, start: int) -> int:
    """The index of the backtick that closes one opened before start, len(text) when
    none does."""
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            return index
        index += 1
    return len(text)


def split_heredocs(text: str) -> tuple[str, list[tuple[str, bool]]]:
    """text without its heredoc bodies, and each body with whether its delimiter is
    quoted, which makes the body literal text without substitutions.

    A body starts on the line after its `<<` and ends at the line holding only the
    delimiter, leading tabs removed for `<<-`. One without that line runs to the end.
    """
    kept: list[str] = []
    bodies: list[tuple[str, bool]] = []
    rest = text
    while rest:
        masked = _common.mask_quoted(rest)
        operator = HEREDOC_OPERATOR.search(masked)
        word = HEREDOC_WORD.match(rest, operator.end()) if operator else None
        if operator is None:
            kept.append(rest)
            break
        if word is None:
            kept.append(rest[: operator.end()])
            rest = rest[operator.end() :]
            continue
        newline = masked.find("\n", word.end())
        if newline < 0:
            kept.append(rest)
            break
        kept.append(rest[: newline + 1])
        strip_tabs = word.group(1) == "-"
        raw_delimiter = word.group(2)
        delimiter = re.sub(r"[\"'\\]", "", raw_delimiter)
        lines = rest[newline + 1 :].split("\n")
        end = next(
            (
                index
                for index, line in enumerate(lines)
                if (line.lstrip("\t") if strip_tabs else line) == delimiter
            ),
            len(lines),
        )
        bodies.append(("\n".join(lines[:end]), raw_delimiter != delimiter))
        rest = "\n".join(lines[end + 1 :])
    return "".join(kept), bodies


def call_violation(
    call: GitCall, cwd: str, rewrites_remote: bool, remote_cache: RemoteCache
) -> Optional[str]:
    """The deny reason for one git call, or None when it is fine."""
    reason = bypass_violation(" ".join(call.words))
    if reason:
        return reason
    sub_index = git_subcommand_index(call.words, 0)
    if sub_index is None or call.words[sub_index] not in GUARDED_SUBCOMMANDS:
        return None
    if call.behind_xargs and call.words[sub_index] == "push":
        return XARGS_PUSH

    git_path = global_directory(call.words[1:sub_index])
    normalized = " ".join(["git", *call.words[sub_index:]])
    part_cwd = git_path or cwd
    scope_dir = _common.git_part_dir(call.raw, call.directory, git_path)
    scratch_dir = scope_dir if _common.in_scratch(scope_dir) and not rewrites_remote else None
    if scratch_dir:
        part_cwd = scratch_dir
    default = _common.default_branch(part_cwd)
    return push_violation(
        normalized, part_cwd, default, remote_cache, scratch_dir
    ) or branch_delete_violation(normalized, default)


def global_directory(options: list[str]) -> Optional[str]:
    """The directory the `-C` options among git's global options point at, each one
    read against the one before, None when there is none."""
    path: Optional[str] = None
    index = 0
    while index < len(options):
        if options[index] == "-C" and index + 1 < len(options):
            value = options[index + 1]
            path = value if path is None else os.path.join(path, value)
        index += 2 if options[index] in GLOBAL_OPTIONS_WITH_VALUE else 1
    return path


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    remote_cache: RemoteCache = {}

    rewrites_remote = changes_remote_config(command)
    for call in git_calls(command, cwd):
        reason = call_violation(call, cwd, rewrites_remote, remote_cache)
        if reason:
            return _common.deny(EVENT, reason)

    for raw_part, directory in _common.part_dirs(command, cwd):
        part = _common.normalize_command_part(raw_part)
        if part.split(" ", 1)[0] != "git":
            continue

        normalized, git_path = _common.strip_global_git_options(part)
        scope_dir = _common.git_part_dir(raw_part, directory, git_path)
        scratch_dir = scope_dir if _common.in_scratch(scope_dir) else None
        if scratch_dir and rewrites_remote:
            scratch_dir = None

        reason = network_shape_violation(command, raw_part, normalized, git_path, scratch_dir)
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
