#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a push to the default branch, unless the remote
carries no branch at all yet, a force push without `--force-with-lease` or one onto the
default branch, `git push --all` or `--mirror`, a command that bypasses hooks or commit
signing, and deletion of the default branch, local or remote.
"""

import os
import re
import subprocess
import sys
from typing import Optional

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


GIT_NETWORK = re.compile(r"^git\s+(fetch|pull|push)\b")
SHELL_OPERATOR = re.compile(r"[<>&]")

RUN_NETWORK_ALONE = (
    "A git fetch, pull or push leaves the sandbox only when it stands alone in the call. "
    "With a pipe, redirection, chain, -C or cd it runs inside the sandbox and fails with a "
    "host key error. Run it alone, from the worktree directory."
)


def network_shape_violation(
    command: str, normalized: str, git_path: Optional[str]
) -> Optional[str]:
    """The deny reason when a `git fetch`, `git pull` or `git push` part shares its call
    with anything else: another part (pipe, chain, newline), a redirection or `&`
    outside quotes, or a `-C` path. A leading `cd` is another part, so it is covered."""
    if not GIT_NETWORK.match(normalized):
        return None
    alone = (
        len(_common.command_parts(command)) == 1
        and git_path is None
        and not SHELL_OPERATOR.search(_common.mask_quoted(command))
    )
    return None if alone else RUN_NETWORK_ALONE


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    remote_cache: RemoteCache = {}

    rewrites_remote = changes_remote_config(command)
    for raw_part, directory in _common.part_dirs(command, cwd):
        part = _common.normalize_command_part(raw_part)
        if part.split(" ", 1)[0] != "git":
            continue

        normalized, git_path = _common.strip_global_git_options(part)
        part_cwd = git_path or cwd
        scope_dir = _common.git_part_dir(raw_part, directory, git_path)
        scratch_dir = scope_dir if _common.in_scratch(scope_dir) else None
        if scratch_dir and rewrites_remote:
            scratch_dir = None
        if scratch_dir:
            part_cwd = scratch_dir
        default = _common.default_branch(part_cwd)

        reason = (
            bypass_violation(part)
            or push_violation(normalized, part_cwd, default, remote_cache, scratch_dir)
            or branch_delete_violation(normalized, default)
            or (None if scratch_dir else network_shape_violation(command, normalized, git_path))
        )
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
