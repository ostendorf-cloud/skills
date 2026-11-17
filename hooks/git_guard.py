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

The command is read within fixed bounds on its size, its nesting and the time spent.
When a command that mentions git goes past a bound, or reading it fails, the hook
denies it. Hook input that is not a payload at all still gets the empty answer.

Options and config keys are read the way git reads them: short flag clusters, unique
prefixes of long options, config keys without case and git's boolean values.

Limits: the hook reads the shell text of the command. It does not follow another
interpreter, a sourced file, a git binary named through a variable or a glob, an alias
from a config file, or `--git-dir` pointing at another repository. Branch protection
on the remote is the backstop. This hook stops mistakes early.
"""

import os
import re
import shlex
import subprocess
import sys
import time
from typing import NamedTuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GIT_PUSH = re.compile(r"^git\s+push\b")
GIT_BRANCH = re.compile(r"^git\s+branch\s+")
BYPASS_WORDS = ("--no-verify", "--no-gpg-sign")
BYPASS = (
    "This bypasses git hooks or commit signing. Run the command without --no-verify, -n, "
    "--no-gpg-sign or -c commit.gpgsign=false."
)
CONFIG_BYPASS = (
    "This sets git config that skips hooks or signing: core.hooksPath, or commit.gpgsign "
    "or tag.gpgsign other than true. Leave that config as it is."
)
CONFIG_PUSH = (
    "This sets push config, push.default, remote.<name>.push or remote.<name>.mirror, "
    "that can move the default branch or many refs at once. Push named refs from a "
    "feature branch instead."
)
# Characters that leave a ref to the shell: an expansion, a substitution or a brace list.
SHELL_BUILT = "$`{"
SHELL_BUILT_REF = (
    "This push names a ref the shell builds when it runs, so this hook cannot check it. "
    "Write the branch name out."
)
# Substitutions that name the checked out branch, read as HEAD.
CURRENT_BRANCH_SUBSTITUTIONS = frozenset(
    {
        "$(git branch --show-current)",
        "$(git rev-parse --abbrev-ref HEAD)",
        "$(git symbolic-ref --short HEAD)",
        "`git branch --show-current`",
        "`git rev-parse --abbrev-ref HEAD`",
    }
)


def _long_options(negatable: str, plain: str) -> tuple[str, ...]:
    """Long option names: every negatable name with its `--no-` form, and the plain
    names as they are."""
    names = [f"--{prefix}{name}" for name in negatable.split() for prefix in ("", "no-")]
    return tuple(names + [f"--{name}" for name in plain.split()])


class OptionGrammar(NamedTuple):
    """How a git subcommand reads its options, as its `-h` output lists them.

    long_names: every long option, negated forms included, for prefix resolution.
    long_values: the long options that take a value, from the next word when no `=`.
    short_values: short letters that take a value, each with its long name.
    short_optional: short letters whose value can only be attached, with the long name.
    """

    long_names: tuple[str, ...]
    long_values: tuple[str, ...]
    short_values: dict[str, str]
    short_optional: dict[str, str]


# Taken from `git push -h` and `git commit -h` of git 2.56.
OPTION_GRAMMARS = {
    "push": OptionGrammar(
        _long_options(
            "all atomic branches delete dry-run exec follow-tags force force-if-includes "
            "force-with-lease mirror porcelain progress prune push-option quiet receive-pack "
            "recurse-submodules repo set-upstream signed tags thin verbose",
            "ipv4 ipv6 verify no-verify",
        ),
        ("--exec", "--receive-pack", "--repo", "--push-option", "--recurse-submodules"),
        {"o": "--push-option"},
        {},
    ),
    "commit": OptionGrammar(
        _long_options(
            "ahead-behind all amend author branch cleanup date dry-run edit file fixup "
            "gpg-sign include interactive long message null only patch pathspec-file-nul "
            "pathspec-from-file porcelain quiet reedit-message reset-author reuse-message "
            "short signoff squash status template trailer untracked-files verbose",
            "allow-empty allow-empty-message inter-hunk-context no-post-rewrite "
            "post-rewrite unified verify no-verify",
        ),
        (
            "--author",
            "--cleanup",
            "--date",
            "--file",
            "--fixup",
            "--inter-hunk-context",
            "--message",
            "--pathspec-from-file",
            "--reedit-message",
            "--reuse-message",
            "--squash",
            "--template",
            "--trailer",
            "--unified",
        ),
        {
            "F": "--file",
            "m": "--message",
            "c": "--reedit-message",
            "C": "--reuse-message",
            "t": "--template",
            "U": "--unified",
        },
        {"S": "--gpg-sign", "u": "--untracked-files"},
    ),
}

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

    for prefix in ("refs/heads/", "heads/"):
        if dst.startswith(prefix):
            dst = dst[len(prefix) :]
            break
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


def changes_remote_config(command: str, calls: list["GitCall"]) -> bool:
    """Whether command, anywhere in it, can change where a push goes: a `git remote` or
    `git config` call among calls, a `-c remote.*` or `-c url.*` option, `--config-env`,
    a `GIT_CONFIG*` variable or a mention of `.git/config`.

    The scratch exemption reads the remote before the command runs, so a command that
    rewrites it first would be judged on the old value. Such a command gets the
    repository rule instead. A part that does not parse counts as changing it."""
    for call in calls:
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
    return push_tokens_violation(part.split()[2:], cwd, default, remote_cache, scratch_dir)


def push_tokens_violation(
    tokens: list[str],
    cwd: Optional[str],
    default: str,
    remote_cache: RemoteCache,
    scratch_dir: Optional[str] = None,
) -> Optional[str]:
    """The deny reason for a `git push` with these arguments, or None when it is fine.

    tokens are the words after "push", options already read the way git reads them,
    see normalize_options."""
    if "--all" in tokens:
        return f"This pushes every local branch, including {default}. {USE_FEATURE_BRANCH}"

    if "--mirror" in tokens:
        return f"This mirrors every ref to the remote, including {default}. {USE_FEATURE_BRANCH}"

    non_flag = [token for token in tokens if not token.startswith("-")]
    if "--delete" in tokens and default in non_flag:
        return f"This deletes {default} on the remote. The default branch is never deleted."

    for refspec in non_flag[1:]:
        if any(char in refspec for char in SHELL_BUILT):
            return SHELL_BUILT_REF
        if "*" in refspec or refspec in (":", "+:"):
            return (
                f"This pushes every ref that matches, which can include {default}. "
                f"{USE_FEATURE_BRANCH}"
            )

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


def bypass_violation(subcommand: str, arguments: list[str]) -> Optional[str]:
    """The deny reason when a git subcommand with these arguments skips hooks or commit
    signing.

    Whole words are compared, so a message or a search argument that only mentions a
    flag is not read as the flag: `--no-verify` or `--no-gpg-sign` as an argument of any
    subcommand, and `-n` as an argument of `git commit`. For push and commit the
    arguments are read the way git reads them first, see normalize_options."""
    if any(word in BYPASS_WORDS for word in arguments):
        return BYPASS
    if subcommand == "commit" and "-n" in arguments:
        return BYPASS
    return None


def normalize_options(arguments: list[str], grammar: OptionGrammar) -> list[str]:
    """arguments with each option written the way git reads it.

    A unique prefix of a long option becomes its full name, an exact name winning over
    a longer one, through _common._resolve_long_flag. A prefix that names several
    options stays as it is, git refuses it. A cluster of short flags becomes one flag
    each, up to a letter that takes a value. An option that takes a value becomes one
    `--name=value` word, so its value never reads as a remote or a ref. Everything from
    `--` on stays as it is."""
    out: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument == "--":
            out.extend(arguments[index - 1 :])
            break
        if argument.startswith("--"):
            name, separator, value = argument.partition("=")
            full = _common._resolve_long_flag(name, grammar.long_names) or name
            if full in grammar.long_values and not separator and index < len(arguments):
                out.append(f"{full}={arguments[index]}")
                index += 1
            else:
                out.append(full + separator + value)
        elif argument.startswith("-") and len(argument) > 1:
            for position, letter in enumerate(argument[1:], start=1):
                tail = argument[position + 1 :]
                if letter in grammar.short_values:
                    long_name = grammar.short_values[letter]
                    if tail:
                        out.append(f"{long_name}={tail}")
                    elif index < len(arguments):
                        out.append(f"{long_name}={arguments[index]}")
                        index += 1
                    else:
                        out.append(long_name)
                    break
                if letter in grammar.short_optional:
                    long_name = grammar.short_optional[letter]
                    out.append(f"{long_name}={tail}" if tail else long_name)
                    break
                out.append(f"-{letter}")
        else:
            out.append(argument)
    return out


def config_entries(options: list[str]) -> list[tuple[str, Optional[str]]]:
    """The key and value of every config entry among git's global options.

    `-c <key>=<value>` gives its value, a bare `-c <key>` means true, as in git, and
    `--config-env` gives None, the value coming from a variable this hook cannot read."""
    found: list[tuple[str, Optional[str]]] = []
    index = 0
    while index < len(options):
        option = options[index]
        if option in ("-c", "--config-env") and index + 1 < len(options):
            key, separator, value = options[index + 1].partition("=")
            if option == "-c":
                found.append((key, value if separator else "true"))
            else:
                found.append((key, None))
        elif option.startswith("--config-env="):
            found.append((option[len("--config-env=") :].partition("=")[0], None))
        index += 2 if option in GLOBAL_OPTIONS_WITH_VALUE else 1
    return found


def git_bool(value: str) -> bool:
    """value read as a git boolean: true, yes, on or a nonzero number."""
    text = value.strip().lower()
    if text in ("true", "yes", "on"):
        return True
    try:
        return int(text) != 0
    except ValueError:
        return False


def config_violation(key: str, value: Optional[str]) -> Optional[str]:
    """The deny reason when setting config key to value skips hooks or signing or widens
    a push. value None means it cannot be read. Keys compare without case, as in git."""
    key = key.lower()
    if key == "core.hookspath":
        return CONFIG_BYPASS
    if key in ("commit.gpgsign", "tag.gpgsign") and (value is None or not git_bool(value)):
        return CONFIG_BYPASS
    if key == "push.default" or (
        key.startswith("remote.") and key.rsplit(".", 1)[-1] in ("push", "mirror")
    ):
        return CONFIG_PUSH
    return None


ENV_CONFIG = re.compile(r"^GIT_CONFIG_(KEY|VALUE)_(\d+)=(.*)$", re.DOTALL)
CONFIG_PARAMETER = re.compile(r"'([^']*)'(?:='([^']*)')?")


def env_config_violation(parts: list[str]) -> Optional[str]:
    """The deny reason when the command parts set config through the environment,
    `GIT_CONFIG_KEY_<n>` with `GIT_CONFIG_VALUE_<n>` or `GIT_CONFIG_PARAMETERS`, that
    config_violation denies."""
    keys: dict[str, str] = {}
    values: dict[str, str] = {}
    for part in parts:
        for word in shell_words_of(part):
            match = ENV_CONFIG.match(word)
            if match:
                (keys if match.group(1) == "KEY" else values)[match.group(2)] = match.group(3)
            elif word.startswith("GIT_CONFIG_PARAMETERS="):
                for key, value in CONFIG_PARAMETER.findall(word.partition("=")[2]):
                    reason = config_violation(key, value or "true")
                    if reason:
                        return reason
    for number, key in keys.items():
        reason = config_violation(key, values.get(number))
        if reason:
            return reason
    return None


CONFIG_VALUE_FLAGS = frozenset({"-f", "--file", "--blob", "--type", "--default", "--value"})
CONFIG_READ_FLAGS = frozenset(
    {
        "--get",
        "--get-all",
        "--get-regexp",
        "--get-urlmatch",
        "--get-color",
        "--get-colorbool",
        "-l",
        "--list",
        "-e",
        "--edit",
    }
)
CONFIG_OTHER_MODES = frozenset({"get", "list", "edit", "rename-section", "remove-section"})


def config_write_violation(arguments: list[str]) -> Optional[str]:
    """The deny reason when a `git config` call with these arguments writes config that
    config_violation denies, or unsets commit.gpgsign or tag.gpgsign. A read is fine."""
    positional: list[str] = []
    unset = read = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if argument in CONFIG_VALUE_FLAGS:
            index += 1
        elif argument in ("--unset", "--unset-all"):
            unset = True
        elif argument in CONFIG_READ_FLAGS:
            read = True
        elif not argument.startswith("-"):
            positional.append(argument)
    if positional and positional[0] in CONFIG_OTHER_MODES:
        return None
    if positional and positional[0] in ("set", "unset"):
        unset = unset or positional[0] == "unset"
        positional = positional[1:]
    if read or not positional:
        return None
    key = positional[0]
    if unset:
        return config_violation(key, "false") if key.lower().endswith(".gpgsign") else None
    if len(positional) < 2:
        return None
    return config_violation(key, positional[1])


def branch_force_delete(arguments: list[str]) -> bool:
    """Whether `git branch` with these arguments deletes by force: `-D`, also inside a
    cluster, or `--delete` with `--force`."""
    short = [a for a in arguments if a.startswith("-") and not a.startswith("--")]
    if any("D" in argument for argument in short):
        return True
    deletes = "--delete" in arguments or any("d" in argument for argument in short)
    forces = "--force" in arguments or any("f" in argument for argument in short)
    return deletes and forces


def send_pack_violation(arguments: list[str], cwd: Optional[str], default: str) -> Optional[str]:
    """The deny reason for `git send-pack` with these arguments: every ref, matching
    refs when it names none, refs from stdin, a forced update, or the default branch."""
    non_flag = [argument for argument in arguments if not argument.startswith("-")]
    refs = non_flag[1:]
    if not refs or any(flag in arguments for flag in ("--all", "--mirror", "--stdin")):
        return f"This sends every matching ref, which can include {default}. {USE_FEATURE_BRANCH}"
    if "--force" in arguments or any(ref.startswith("+") for ref in refs):
        return f"This force pushes without --force-with-lease. {USE_FORCE_WITH_LEASE}"
    for ref in refs:
        if any(char in ref for char in SHELL_BUILT):
            return SHELL_BUILT_REF
        if "*" in ref or refspec_target(ref, cwd)[0] == default:
            return f"This pushes to {default}, the default branch. {USE_FEATURE_BRANCH}"
    return None


def update_ref_violation(arguments: list[str], default: str) -> Optional[str]:
    """The deny reason for `git update-ref` with these arguments: updates read from
    stdin, which this hook cannot check, or a delete of the default branch."""
    if "--stdin" in arguments:
        return (
            "This reads ref updates from stdin, so this hook cannot check them. Use git "
            "branch or git push on named refs instead."
        )
    if "-d" in arguments and f"refs/heads/{default}" in arguments:
        return f"This deletes the local branch {default}, the default branch. It is never deleted."
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
    command_alone: bool,
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

    command_alone says whether the whole command, heredoc bodies removed, is one part
    without a pipe, chain or redirection, see command_stands_alone.

    A command in the session scratch scope whose remote is itself scratch local is
    exempt: such a push is a local file copy and works in the sandbox.

    Accepted false positive: an escaped `\\&` in an argument reads as an operator.
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
    alone = command_alone and git_path is None and prefix_ok and subcommand_next
    return None if alone else RUN_NETWORK_ALONE


def command_stands_alone(command: str) -> bool:
    """Whether command is one part, without a redirection or `&` outside quotes other
    than a trailing `2>&1` or `>&2`. Read once per command, not once per part."""
    masked = KEPT_REDIRECTION.sub("", _common.mask_quoted(command))
    return len(_common.command_parts(command)) == 1 and not SHELL_OPERATOR.search(masked)


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


GUARDED_SUBCOMMANDS = ("push", "branch", "send-pack", "update-ref")
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "su"})
SHELL_VALUE_FLAGS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
SHELL_COMMAND_FLAG = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
NESTING_LIMIT = 8
# Characters a shell reads as grouping or substitution in front of a command word.
COMMAND_PREFIX_CHARS = "({!$<>`"
WORD_END = re.compile(r"[<>&)`]")
CALL_WORD_SPECIAL = re.compile(r"[<>&()`]")
OPERATOR_ONLY = re.compile(r"\d*[<>&]+")
REDIRECTION = re.compile(r"^\d*(?:[<>]|&>)")
HEREDOC_WORD = re.compile(r"(-?)[ \t]*([A-Za-z_'\"\\][^\s;&|<>()]*)")
# A program receives each argument cut at its first NUL byte.
NUL_TAIL = re.compile(r"\x00\S*")
# A word holding one of these is read as a command of its own when a shell is fed.
NESTED_WORD_HINTS = ("git", "'", '"', "\\", "$", "`")

# The bounds within which a command is read. A command that mentions git and goes
# past one of them is denied, see UNREADABLE.
MAX_TEXTS = 500
MAX_CHARS = 100000
MAX_PARTS = 2000
MAX_WORDS = 50000
MAX_GIT_CALLS = 200
MAX_CALL_WORDS = 2000
MAX_HEREDOCS = 100
READ_SECONDS = 2.0

XARGS_PUSH = (
    "A git push behind xargs takes refs this hook cannot check. Run git push with its "
    "refs written out in the command."
)
XARGS_ARGUMENTS = (
    "A git commit or a git branch -D behind xargs takes arguments this hook cannot check. "
    "Run it with its arguments written out in the command."
)
UNREADABLE = (
    "This command mentions git in a form this hook cannot read in full. Run each git "
    "command on its own, with its arguments written out."
)


class ReadLimitError(Exception):
    """A command goes past one of the bounds it is read within."""


class Budget:
    """What reading one command may still spend: counts per kind and a deadline."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.deadline = time.monotonic() + READ_SECONDS

    def spend(self, kind: str, limit: int, amount: int = 1) -> None:
        """Counts amount of kind. Raises ReadLimitError past limit or past the deadline."""
        total = self.counts.get(kind, 0) + amount
        self.counts[kind] = total
        if total > limit:
            raise ReadLimitError(kind)
        if time.monotonic() > self.deadline:
            raise ReadLimitError("time")


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


def cut_at_nul(command: str) -> str:
    """command with every word cut at its first NUL byte, the way a program receives
    it as an argument."""
    return NUL_TAIL.sub("", command)


def git_calls(command: str, cwd: Optional[str], budget: Optional[Budget] = None) -> list[GitCall]:
    """Every git call command makes, wherever git stands in it.

    A word naming git counts in any position of a command part, so a wrapper, a group,
    a subshell or a control keyword in front of it does not hide the call. Command
    substitutions, a string after a shell's `-c`, the arguments of `eval` and a `-c
    alias.*` starting with `!` are read as commands of their own. When the command feeds
    a shell its commands through a pipe, a here-string or a heredoc, every word and
    heredoc body of the command is read as one too. A backslash newline joins two
    lines, as in the shell.

    Raises ReadLimitError when the command goes past a bound of budget, or holds git inside
    more than NESTING_LIMIT levels of nesting.

    Accepted false positives: a word `git` that is an argument, such as in `echo git push
    --force`, reads as a call.
    """
    text = cut_at_nul(command).replace("\\\n", "")
    return _calls_in(text, cwd, 0, set(), budget or Budget())


def _calls_in(
    text: str, cwd: Optional[str], depth: int, seen: set[str], budget: Budget
) -> list[GitCall]:
    """The git calls in text. cwd is the directory text runs in, None when not known."""
    if text in seen:
        return []
    if depth > NESTING_LIMIT:
        if "git" in text:
            raise ReadLimitError("nesting")
        return []
    seen.add(text)
    budget.spend("texts", MAX_TEXTS)
    text, bodies = split_heredocs(text, budget)
    budget.spend("chars", MAX_CHARS, len(text))
    parts = command_parts_with_pipes(text)
    budget.spend("parts", MAX_PARTS, len(parts))
    directories: list[Optional[str]] = [None] * len(parts)
    if depth == 0:
        pairs = _common.part_dirs(text, cwd)
        if len(pairs) == len(parts):
            directories = [directory for _, directory in pairs]

    calls: list[GitCall] = []
    nested: list[str] = []
    fed_shell = False
    for (raw, piped), directory in zip(parts, directories):
        words = _common.shell_words(raw)
        budget.spend("words", MAX_WORDS, len(words))
        resolved = [_common.unquote_word(word) for word in words]
        names = [_common.token_name(word.lstrip(COMMAND_PREFIX_CHARS)) for word in resolved]
        behind_xargs = False
        for index, name in enumerate(names):
            if name == "xargs":
                behind_xargs = True
            elif name == "git":
                budget.spend("calls", MAX_GIT_CALLS)
                in_backtick = "`" in words[index].partition("git")[0]
                call_words, alias_command = git_call_words(words, resolved, index + 1, in_backtick)
                calls.append(GitCall(call_words, raw, directory, behind_xargs))
                if alias_command:
                    nested.append(alias_command)
        inner, fed = inner_commands(raw, resolved, names, piped)
        nested.extend(inner)
        fed_shell = fed_shell or fed

    for body, quoted in bodies:
        if not quoted:
            nested.extend(substitutions(body))
    if fed_shell:
        nested.extend(body for body, _ in bodies)
        for raw, _ in parts:
            nested.extend(
                word
                for word in shell_words_of(raw)
                if any(hint in word for hint in NESTED_WORD_HINTS)
            )

    for inner_text in nested:
        calls.extend(_calls_in(inner_text, None, depth + 1, seen, budget))
    return calls


def command_word_name(word: str) -> str:
    """The command name word names, its quoting resolved and any grouping or
    substitution characters in front of it removed, so `(git` and `$(git` read as git."""
    return _common.token_name(_common.unquote_word(word).lstrip(COMMAND_PREFIX_CHARS))


def command_parts_with_pipes(command: str) -> list[tuple[str, bool]]:
    """The parts _common.command_parts splits command into, each with whether a single
    `|` feeds it. Follows the same quote tracking and separators, so the parts match."""
    parts: list[tuple[str, bool]] = []
    current: list[str] = []
    piped = False
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
        separator = ""
        if char == "\n":
            separator = "\n"
        elif char in "|&" and command[index + 1 : index + 2] == char:
            separator = char * 2
        elif char in (";", "|"):
            separator = char
        if separator:
            parts.append(("".join(current), piped))
            current = []
            piped = separator == "|"
            index += len(separator)
            continue
        current.append(char)
        index += 1
    parts.append(("".join(current), piped))
    return [(part.strip(), feeds) for part, feeds in parts if part.strip()]


def git_call_words(
    words: list[str], resolved: list[str], start: int, in_backtick: bool = False
) -> tuple[list[str], Optional[str]]:
    """The words of a git call whose arguments start at index start of words, and the
    command a `-c alias.*` starting with `!` runs instead, None when there is none.

    resolved holds words with their quoting resolved. in_backtick says the call runs
    inside a backtick substitution, so the next backtick closes it.

    A substitution that opens inside an argument, `$(`, `<(` or a backtick, stays part
    of that argument until it closes, so `$(echo main)` is one argument that still
    shows its `$`. Otherwise the call ends at an unquoted `)` or backtick, which closes
    the group or substitution it runs in, and at a lone `&`. A redirection and its
    target are dropped, so `main>/dev/null` reads as `main`. Raises ReadLimitError past
    MAX_CALL_WORDS words.
    """
    call = ["git"]
    skip_next = False
    opened = 0
    ticked = False
    pending: list[str] = []
    for index in range(start, len(words)):
        if len(call) > MAX_CALL_WORDS:
            raise ReadLimitError("call")
        if skip_next:
            skip_next = False
            continue
        word = words[index]
        if not CALL_WORD_SPECIAL.search(word) and not opened and not ticked:
            call.append(resolved[index])
            continue
        cut = None
        for position, char in enumerate(_common.mask_quoted(word)):
            if char == "(":
                opened += 1
            elif char == ")":
                if not opened:
                    cut = position
                    break
                opened -= 1
            elif char == "`":
                if ticked:
                    ticked = False
                elif in_backtick:
                    cut = position
                    break
                else:
                    ticked = True
            elif char in "<>&" and not opened and not ticked:
                cut = position
                break
        if cut is None:
            pending.append(word)
            if not opened and not ticked:
                call.append(_join_argument(pending))
                pending = []
            continue
        prefix, rest = word[:cut], word[cut:]
        if prefix and prefix.isdigit() and rest[0] in "<>":
            prefix = ""
        if prefix or pending:
            call.append(_join_argument([part for part in (*pending, prefix) if part]))
            pending = []
        if rest[0] in ")`" or (rest[0] == "&" and not rest.startswith("&>")):
            break
        skip_next = bool(OPERATOR_ONLY.fullmatch(rest))
    if pending:
        call.append(_join_argument(pending))
    return expand_alias(call)


def _join_argument(words: list[str]) -> str:
    """One argument made of words that a substitution held together, with the quoting
    of each resolved. A single plain word stays as it is."""
    if len(words) == 1:
        return _common.unquote_word(words[0])
    return " ".join(_common.unquote_word(word) for word in words)


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


def inner_commands(
    raw: str, resolved: list[str], names: list[str], piped: bool
) -> tuple[list[str], bool]:
    """The command strings raw runs inside itself, and whether it feeds a shell its
    commands.

    resolved holds the words of raw with their quoting resolved, names the command name
    each of them reads as. Inner commands are the command substitutions, the words after
    a shell's `-c` and the arguments of `eval`, joined. A shell is fed when it is the
    command of raw, wrappers aside, reads stdin, and piped says a `|` feeds raw or raw
    holds a here-string or heredoc. A shell name elsewhere, such as in `which sh`, is an
    argument."""
    inner = substitutions(raw)
    first_eval = next((i for i, name in enumerate(names) if name == "eval"), None)
    if first_eval is not None:
        inner.append(" ".join(resolved[first_eval + 1 :]))
    first_shell = next((i for i, name in enumerate(names) if name in SHELLS), None)
    if first_shell is None:
        return inner, False
    later = resolved[first_shell + 1 :]
    if any(SHELL_COMMAND_FLAG.match(word) for word in later):
        inner.extend(later)
        return inner, False
    return inner, feeds_shell(raw, piped)


def feeds_shell(raw: str, piped: bool) -> bool:
    """Whether raw runs a shell as its command, wrappers aside, that reads stdin, while
    a pipe, a here-string or a heredoc gives it that stdin."""
    if not piped and "<<" not in _common.mask_quoted(raw):
        return False
    words = _common.shell_words(_common.normalize_command_part(raw))
    if not words or command_word_name(words[0]) not in SHELLS:
        return False
    return shell_reads_stdin([_common.unquote_word(word) for word in words[1:]])


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
    quotes and nested substitutions respected. len(text) when it stays open.

    Each nested `$(` gets a frame of its own with its parenthesis depth and quote
    state, on a list rather than the call stack, so any depth of nesting is read in one
    pass."""
    frames = [[1, False, False]]
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        frame = frames[-1]
        if frame[1]:
            frame[1] = char != "'"
        elif char == "\\":
            index += 2
            continue
        elif char == "`":
            index = _backtick_end(text, index + 1) + 1
            continue
        elif char == "$" and text[index + 1 : index + 2] == "(":
            frames.append([1, False, False])
            index += 2
            continue
        elif frame[2]:
            frame[2] = char != '"'
        elif char == "'":
            frame[1] = True
        elif char == '"':
            frame[2] = True
        elif char == "(":
            frame[0] += 1
        elif char == ")":
            frame[0] -= 1
            if frame[0] == 0:
                frames.pop()
                if not frames:
                    return index
        index += 1
    return length


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


def split_heredocs(
    text: str, budget: Optional[Budget] = None
) -> tuple[str, list[tuple[str, bool]]]:
    """text without its heredoc bodies, and each body with whether its delimiter is
    quoted, which makes the body literal text without substitutions.

    One pass over text. Every unquoted `<<` names a delimiter, several on one line
    included. At the end of that line the bodies follow in order: each starts on the
    next line and ends at the line holding only its delimiter, leading tabs removed for
    `<<-`. One without that line runs to the end. A `$(...)` inside double quotes is
    skipped whole, so a heredoc inside it belongs to that inner command. Raises
    ReadLimitError past MAX_HEREDOCS when a budget is given.
    """
    kept: list[str] = []
    bodies: list[tuple[str, bool]] = []
    pending: list[tuple[bool, str, bool]] = []
    single = double = False
    copied = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if single:
            single = char != "'"
            index += 1
            continue
        if char == "\\":
            index += 2
            continue
        if double:
            if char == '"':
                double = False
            elif char == "$" and text[index + 1 : index + 2] == "(":
                index = _substitution_end(text, index + 2)
            index += 1
            continue
        if char == "'":
            single = True
        elif char == '"':
            double = True
        elif text.startswith("$((", index):
            index = _substitution_end(text, index + 2) + 1
            continue
        elif text.startswith("<<", index) and not text.startswith("<<<", index):
            word = HEREDOC_WORD.match(text, index + 2)
            if word:
                if budget is not None:
                    budget.spend("heredocs", MAX_HEREDOCS)
                raw_delimiter = word.group(2)
                delimiter = re.sub(r"[\"'\\]", "", raw_delimiter)
                pending.append((word.group(1) == "-", delimiter, raw_delimiter != delimiter))
                index = word.end()
                continue
            index += 2
            continue
        elif text.startswith("<<<", index):
            index += 3
            continue
        elif char == "\n" and pending:
            kept.append(text[copied : index + 1])
            position = index + 1
            for strip_tabs, delimiter, quoted in pending:
                lines: list[str] = []
                while position < length:
                    end = text.find("\n", position)
                    end = length if end < 0 else end
                    line = text[position:end]
                    position = end + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
                    lines.append(line)
                bodies.append(("\n".join(lines), quoted))
            pending = []
            copied = index = min(position, length)
            continue
        index += 1
    kept.append(text[copied:])
    return "".join(kept), bodies


def call_violation(
    call: GitCall, cwd: str, rewrites_remote: bool, remote_cache: RemoteCache
) -> Optional[str]:
    """The deny reason for one git call, or None when it is fine."""
    sub_index = git_subcommand_index(call.words, 0)
    options = call.words[1:sub_index] if sub_index is not None else call.words[1:]
    for key, value in config_entries(options):
        reason = config_violation(key, value)
        if reason:
            return reason
    if sub_index is None:
        return None

    subcommand = call.words[sub_index]
    arguments = call.words[sub_index + 1 :]
    grammar = OPTION_GRAMMARS.get(subcommand)
    if grammar:
        arguments = normalize_options(arguments, grammar)
    reason = bypass_violation(subcommand, arguments)
    if reason:
        return reason
    if subcommand == "config":
        return config_write_violation(arguments)
    if call.behind_xargs:
        if subcommand == "push":
            return XARGS_PUSH
        if subcommand == "commit" or (subcommand == "branch" and branch_force_delete(arguments)):
            return XARGS_ARGUMENTS
    if subcommand not in GUARDED_SUBCOMMANDS:
        return None

    git_path = global_directory(options)
    part_cwd = git_path or cwd
    scope_dir = _common.git_part_dir(call.raw, call.directory, git_path)
    scratch_dir = scope_dir if _common.in_scratch(scope_dir) and not rewrites_remote else None
    if scratch_dir:
        part_cwd = scratch_dir
    default = _common.default_branch(part_cwd)
    if subcommand == "push":
        tokens = [
            "HEAD" if " ".join(argument.split()) in CURRENT_BRANCH_SUBSTITUTIONS else argument
            for argument in arguments
        ]
        return push_tokens_violation(tokens, part_cwd, default, remote_cache, scratch_dir)
    if subcommand == "send-pack":
        return send_pack_violation(arguments, part_cwd, default)
    if subcommand == "update-ref":
        return update_ref_violation(arguments, default)
    return branch_delete_violation(" ".join(["git", "branch", *arguments]), default)


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


def command_violation(command: str, cwd: str) -> Optional[str]:
    """The deny reason for command, or None when it is fine. Raises ReadLimitError, or any
    other error, when the command cannot be read in full."""
    command = cut_at_nul(command)
    remote_cache: RemoteCache = {}
    calls = git_calls(command, cwd)
    shape_text, _ = split_heredocs(command, Budget())
    if calls:
        parts = {call.raw for call in calls} | set(_common.command_parts(shape_text))
        reason = env_config_violation(sorted(parts))
        if reason:
            return reason
    rewrites_remote = changes_remote_config(shape_text, calls)
    for call in calls:
        reason = call_violation(call, cwd, rewrites_remote, remote_cache)
        if reason:
            return reason

    command_alone = command_stands_alone(shape_text)
    for raw_part, directory in _common.part_dirs(shape_text, cwd):
        part = _common.normalize_command_part(raw_part)
        if part.split(" ", 1)[0] != "git":
            continue

        normalized, git_path = _common.strip_global_git_options(part)
        scope_dir = _common.git_part_dir(raw_part, directory, git_path)
        scratch_dir = scope_dir if _common.in_scratch(scope_dir) else None
        if scratch_dir and rewrites_remote:
            scratch_dir = None

        reason = network_shape_violation(command_alone, raw_part, normalized, git_path, scratch_dir)
        if reason:
            return reason
    return None


def main() -> int:
    payload = _common.read_payload()
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return _common.emit_empty()
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()

    # Only the reading of a command fails closed. A command that mentions git and
    # cannot be read in full is denied rather than let through unread.
    try:
        reason = command_violation(command, cwd)
    except Exception:
        reason = UNREADABLE if "git" in command else None
    return _common.deny(EVENT, reason) if reason else _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
