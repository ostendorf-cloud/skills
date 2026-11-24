# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for git_guard.py."""

import contextlib
import io
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Any, Optional
from unittest import mock

from helper import (
    HOOKS_DIR,
    NO_SCRATCH,
    bash_payload,
    context,
    decision,
    reason,
    run_hook,
    scratch_env,
)

# The hook is imported in process for the tests that need to fake sys.platform or to
# watch one run's cache. Importing it adds the hooks directory to sys.path, so the
# path is put back right after.
_saved_path = list(sys.path)
sys.path.insert(0, HOOKS_DIR)
import git_guard  # noqa: E402

sys.path[:] = _saved_path


def run_main_in_process(
    command: str,
    cwd: str,
    platform: str,
    tmpdir: str = NO_SCRATCH,
    path: Optional[str] = None,
) -> dict[str, Any]:
    """Runs git_guard.main() in this process with sys.platform faked as platform and
    $TMPDIR (the session scratch scope) as tmpdir. Returns the parsed response."""
    payload = json.dumps(bash_payload(command, cwd))
    out = io.StringIO()
    env = {"TMPDIR": tmpdir}
    if path is not None:
        env["PATH"] = path
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "platform", platform))
        stack.enter_context(mock.patch.dict(os.environ, env))
        stack.enter_context(mock.patch.object(sys, "stdin", io.StringIO(payload)))
        stack.enter_context(contextlib.redirect_stdout(out))
        git_guard.main()
    return json.loads(out.getvalue())


# How long the slow-remote fixture sleeps on ls-remote. Longer than git_guard's own
# LS_REMOTE_TIMEOUT (5 seconds), so the hook's subprocess call times out first.
SLOW_REMOTE_SECONDS = 8


def git_repo(with_remote: bool = True) -> str:
    """A temporary repository on branch main with one commit.

    with_remote, the default, gives it an origin remote that already carries that
    commit, the way a real clone of an existing repository would. A test that needs a
    different remote, or none at all, passes with_remote=False and sets one up itself.
    """
    path = tempfile.mkdtemp(prefix="git-guard-")
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "dev@example.com"],
        ["config", "user.name", "dev"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    with open(path + "/README.md", "w", encoding="utf-8") as handle:
        handle.write("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "chore: init"], cwd=path, check=True, capture_output=True
    )
    if with_remote:
        add_remote(path, bare_remote())
        push_branch(path, "origin", "main")
    return path


def checkout_feature(path: str) -> None:
    subprocess.run(
        ["git", "checkout", "-q", "-b", "feat/thing"], cwd=path, check=True, capture_output=True
    )


def bare_remote() -> str:
    """A temporary bare repository with no branches, usable as a remote that nothing
    has been pushed to yet."""
    path = tempfile.mkdtemp(prefix="git-guard-remote-")
    subprocess.run(["git", "init", "-q", "--bare", path], check=True, capture_output=True)
    return path


def add_remote(repo: str, remote: str, name: str = "origin") -> None:
    subprocess.run(
        ["git", "remote", "add", name, remote], cwd=repo, check=True, capture_output=True
    )


def push_branch(repo: str, remote: str, branch: str) -> None:
    """Pushes branch to remote for real, setting up fixture state. Never goes through
    the hook: this is the test's own git, not a Bash command Claude would run."""
    subprocess.run(["git", "push", "-q", remote, branch], cwd=repo, check=True, capture_output=True)


def set_config(repo: str, key: str, value: str) -> None:
    subprocess.run(["git", "config", key, value], cwd=repo, check=True, capture_output=True)


def slow_git_env() -> dict:
    """An environment whose PATH resolves "git" to a wrapper that sleeps past
    git_guard's ls-remote timeout before delegating to the real git for ls-remote, and
    runs the real git immediately for every other subcommand.

    Used to test the timeout path without any network: the delay is a local sleep.
    """
    real_git = shutil.which("git")
    shim_dir = tempfile.mkdtemp(prefix="git-guard-slow-git-")
    shim_path = os.path.join(shim_dir, "git")
    with open(shim_path, "w", encoding="utf-8") as handle:
        handle.write(
            "#!/bin/sh\n"
            f'if [ "$1" = "ls-remote" ]; then sleep {SLOW_REMOTE_SECONDS}; fi\n'
            f'exec "{real_git}" "$@"\n'
        )
    os.chmod(shim_path, 0o755)
    env = scratch_env(NO_SCRATCH)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    return env


def counting_git_env() -> tuple[dict, str]:
    """An environment whose PATH resolves "git" to a wrapper that appends a line to a
    log file every time it is run with ls-remote, then delegates to the real git.

    Used to assert how many times the hook actually asked a remote: a count from a
    log file stays deterministic and fast, a wall clock measurement would not.
    """
    real_git = shutil.which("git")
    shim_dir = tempfile.mkdtemp(prefix="git-guard-count-git-")
    log_path = os.path.join(shim_dir, "ls-remote.log")
    shim_path = os.path.join(shim_dir, "git")
    with open(shim_path, "w", encoding="utf-8") as handle:
        handle.write(
            "#!/bin/sh\n"
            f'if [ "$1" = "ls-remote" ]; then echo x >> "{log_path}"; fi\n'
            f'exec "{real_git}" "$@"\n'
        )
    os.chmod(shim_path, 0o755)
    env = scratch_env(NO_SCRATCH)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    return env, log_path


class GitGuardTest(unittest.TestCase):
    def test_allows_ordinary_commands(self):
        repo = git_repo()
        for command in [
            "git status",
            "git log --oneline",
            "git fetch origin",
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_allows_push_from_feature_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin feat/thing",
            "git push",
            "git push --force-with-lease origin feat/thing",
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_denies_push_to_default_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin main",
            "git push origin HEAD:main",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_bare_push_while_on_default_branch(self):
        repo = git_repo()
        self.assertEqual(decision(run_hook("git_guard.py", bash_payload("git push", repo))), "deny")

    def test_denies_plain_force_push(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push --force origin feat/thing",
            "git push -f origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_force_with_lease_on_feature_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        self.assertIsNone(
            decision(
                run_hook(
                    "git_guard.py",
                    bash_payload("git push --force-with-lease origin feat/thing", repo),
                )
            )
        )

    def test_denies_force_with_lease_on_default_branch(self):
        repo = git_repo()
        self.assertEqual(
            decision(
                run_hook(
                    "git_guard.py",
                    bash_payload("git push --force-with-lease origin main", repo),
                )
            ),
            "deny",
        )

    def test_denies_hook_and_signing_bypass(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git commit --no-verify -m 'fix: thing'",
            "git commit --no-gpg-sign -m 'fix: thing'",
            "git -c commit.gpgsign=false commit -m 'fix: thing'",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_deleting_the_default_branch_locally(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in ["git branch -D main", "git branch -d main"]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_deleting_a_feature_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True, capture_output=True)
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload("git branch -D feat/thing", repo)))
        )

    def test_denies_deleting_the_default_branch_on_the_remote(self):
        repo = git_repo()
        checkout_feature(repo)
        output = run_hook("git_guard.py", bash_payload("git push origin --delete main", repo))
        self.assertEqual(decision(output), "deny")
        self.assertIn("deletes", reason(output))

    def test_denies_plus_prefixed_force_refspec_to_default_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        self.assertEqual(
            decision(run_hook("git_guard.py", bash_payload("git push origin +main", repo))),
            "deny",
        )

    def test_denies_plus_prefixed_force_refspec_on_feature_branch_without_lease(self):
        repo = git_repo()
        checkout_feature(repo)
        self.assertEqual(
            decision(run_hook("git_guard.py", bash_payload("git push origin +feat/thing", repo))),
            "deny",
        )

    def test_denies_bare_head_push_while_on_default_branch(self):
        repo = git_repo()
        self.assertEqual(
            decision(run_hook("git_guard.py", bash_payload("git push origin HEAD", repo))), "deny"
        )

    def test_denies_at_push_while_on_default_branch(self):
        repo = git_repo()
        self.assertEqual(
            decision(run_hook("git_guard.py", bash_payload("git push origin @", repo))), "deny"
        )

    def test_allows_head_push_from_feature_branch(self):
        repo = git_repo()
        checkout_feature(repo)
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload("git push origin HEAD", repo)))
        )

    def test_denies_push_all_and_mirror(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in ["git push --all origin", "git push --mirror origin"]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_delete_reason_wins_over_target_reason(self):
        repo = git_repo()
        checkout_feature(repo)
        output = run_hook("git_guard.py", bash_payload("git push origin --delete main", repo))
        self.assertEqual(decision(output), "deny")
        self.assertIn("never deleted", reason(output))

    def test_denies_push_to_default_branch_when_git_is_called_by_absolute_path(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin main",
            "/usr/bin/git push origin main",
            "/opt/homebrew/bin/git push origin main",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_plain_force_push_when_git_is_called_by_absolute_path(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "/usr/bin/git push --force origin feat/thing",
            "/usr/bin/git push --all origin",
            "/usr/bin/git push --mirror origin",
            "/usr/bin/git branch -D main",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_push_to_default_branch_by_absolute_path_through_dash_c_path(self):
        repo = git_repo()
        checkout_feature(repo)
        other = tempfile.mkdtemp(prefix="git-guard-other-")
        self.assertEqual(
            decision(
                run_hook(
                    "git_guard.py",
                    bash_payload(f"/usr/bin/git -C {repo} push origin main", other),
                )
            ),
            "deny",
        )

    def test_allows_a_feature_branch_push_by_absolute_path(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "/usr/bin/git push origin feat/thing",
            "/usr/bin/git push --force-with-lease origin feat/thing",
            "/usr/bin/git status",
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_denies_a_force_push_behind_a_wrapper_prefix(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "time git push --force origin feat/thing",
            "command git push --force origin feat/thing",
            "env git push --force origin feat/thing",
            "exec /usr/bin/git push --force origin feat/thing",
            "nohup git push --force origin feat/thing",
            "nice git push --force origin feat/thing",
            "mise exec -- git push --force origin feat/thing",
            "mise exec git@latest -- git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_default_branch_push_and_delete_behind_a_wrapper_prefix(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "time git push origin main",
            "env git push --force-with-lease origin main",
            "mise exec -- git branch -D main",
            "nohup git push --mirror origin",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_hook_bypass_behind_a_wrapper_prefix(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "time git commit --no-verify -m 'feat: add valkey module'",
            "command git commit --no-gpg-sign -m 'feat: add valkey module'",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_a_feature_branch_push_behind_a_wrapper_prefix(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "time git push origin feat/thing",
            "command git push --force-with-lease origin feat/thing",
            "mise exec -- git status",
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_denies_a_force_push_when_git_is_quoted(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            '"git" push --force origin feat/thing',
            "'git' push --force origin feat/thing",
            '"/usr/bin/git" push --force origin feat/thing',
            "exec \"/usr/bin/git\" commit --no-verify -m 'feat: add valkey module'",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_privilege_escalation_prefix(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "sudo git push --force origin feat/thing",
            "sudo -u ci git push --force origin feat/thing",
            "doas git push --force origin feat/thing",
            "doas -u ci git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_wrapper_carrying_its_own_flags(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "nice -n 10 git push --force origin feat/thing",
            "nice --adjustment=10 git push --force origin feat/thing",
            "nohup -- git push --force origin feat/thing",
            "/usr/bin/nice -n 10 git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_cluster_of_short_wrapper_flags(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "sudo -nu ci git push --force origin feat/thing",
            "sudo -Enu ci git push --force origin feat/thing",
            "sudo -nuci git push --force origin feat/thing",
            "doas -nu ci git push --force origin feat/thing",
            "exec -la foo git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_sudo_option_that_is_build_conditional(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "sudo -r sysadm_r git push --force origin feat/thing",
            "sudo -t unconfined_t git push --force origin feat/thing",
            "sudo -a pam git push --force origin feat/thing",
            "sudo -c daemon git push --force origin feat/thing",
            "sudo --role sysadm_r git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_time_or_exec_value_flag(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "/usr/bin/time -o /var/log/push.log git push --force origin feat/thing",
            "time -f %e git push --force origin feat/thing",
            "time --output /var/log/push.log git push --force origin feat/thing",
            "exec -a foo git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_an_abbreviated_long_wrapper_flag(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "nice --adj 10 git push --force origin feat/thing",
            "sudo --us ci git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_a_boolean_long_wrapper_flag(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "sudo --login git push --force origin feat/thing",
            "sudo --list git push --force origin feat/thing",
            "sudo --preserve-env git push --force origin feat/thing",
            "nice --help git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_a_force_push_behind_the_value_flag_a_boolean_flag_abbreviates(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "sudo --login-class admin git push --force origin feat/thing",
            "sudo --login-class=admin git push --force origin feat/thing",
        ]:
            self.assertEqual(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_a_wrapper_that_runs_no_command(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in ["sudo -V", "sudo -nu", "nice -n", "sudo -e /etc/sudoers", "sudoedit"]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_allows_a_feature_branch_push_behind_a_flagged_wrapper(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "nice -n 10 git push origin feat/thing",
            "sudo git status",
            '"git" push --force-with-lease origin feat/thing',
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_allows_another_command_whose_name_ends_in_git(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "legit push --force origin main",
            "/usr/local/bin/mygit push --force origin main",
            "gitless push --force origin main",
            "git-crypt unlock",
            "git-town sync",
            "nice -n 10 legit push --force origin main",
            "sudo mygit push --force origin main",
            '"gitless" push --force origin main',
        ]:
            self.assertIsNone(
                decision(run_hook("git_guard.py", bash_payload(command, repo))), command
            )

    def test_denies_push_to_default_branch_through_dash_c_path(self):
        repo = git_repo()
        checkout_feature(repo)
        other = tempfile.mkdtemp(prefix="git-guard-other-")
        self.assertEqual(
            decision(
                run_hook(
                    "git_guard.py",
                    bash_payload(f"git -C {repo} push origin main", other),
                )
            ),
            "deny",
        )

    def test_allows_first_push_to_missing_default_branch(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload("git push origin main", repo)))
        )

    def test_denies_push_to_default_branch_that_already_exists_on_remote(self):
        repo = git_repo()
        checkout_feature(repo)
        output = run_hook("git_guard.py", bash_payload("git push origin main", repo))
        self.assertEqual(decision(output), "deny")
        self.assertIn("needs a remote with no branch at all", reason(output))

    def test_denies_push_to_missing_default_branch_when_remote_holds_another_branch(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        push_branch(repo, "origin", "feat/thing")
        output = run_hook("git_guard.py", bash_payload("git push origin main", repo))
        self.assertEqual(decision(output), "deny")
        self.assertIn("needs a remote with no branch at all", reason(output))

    def test_denies_force_push_naming_an_existing_branch_and_the_missing_default_branch(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        push_branch(repo, "origin", "feat/thing")
        output = run_hook(
            "git_guard.py", bash_payload("git push --force origin feat/thing main", repo)
        )
        self.assertEqual(decision(output), "deny")
        self.assertIn("--force-with-lease", reason(output))

    def test_denies_push_to_default_branch_when_the_remote_check_fails(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        for remote in [
            "/nonexistent/git-guard-remote-path",
            tempfile.mkdtemp(prefix="git-guard-not-a-repo-"),
        ]:
            add_remote(repo, remote)
            output = run_hook("git_guard.py", bash_payload("git push origin main", repo))
            self.assertEqual(decision(output), "deny", remote)
            self.assertIn("could not be checked", reason(output), remote)
            subprocess.run(
                ["git", "remote", "remove", "origin"], cwd=repo, check=True, capture_output=True
            )

    def test_denies_push_to_default_branch_when_the_remote_check_times_out(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        output = run_hook(
            "git_guard.py", bash_payload("git push origin main", repo), env=slow_git_env()
        )
        self.assertEqual(decision(output), "deny")
        self.assertIn("could not be checked", reason(output))

    def test_asks_the_remote_at_most_once_for_several_pushes_to_the_default_branch(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        env, log_path = counting_git_env()
        cache: git_guard.RemoteCache = {}
        with mock.patch.dict(os.environ, {"PATH": env["PATH"]}):
            for _ in range(3):
                self.assertIsNone(
                    git_guard.push_violation("git push origin main", repo, "main", cache)
                )
        with open(log_path, encoding="utf-8") as handle:
            calls = handle.read().splitlines()
        self.assertEqual(len(calls), 1)

    def test_main_shares_one_remote_cache_across_a_chain_of_default_branch_pushes(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, bare_remote())
        env, log_path = counting_git_env()
        command = "git push origin main; git push origin main; git push origin main"
        output = run_main_in_process(command, repo, "linux", path=env["PATH"])
        self.assertIsNone(decision(output))
        with open(log_path, encoding="utf-8") as handle:
            calls = handle.read().splitlines()
        self.assertEqual(len(calls), 1)

    def test_force_with_lease_onto_the_default_branch_follows_the_remote_state(self):
        denied = git_repo()
        output = run_hook(
            "git_guard.py", bash_payload("git push --force-with-lease origin main", denied)
        )
        self.assertEqual(decision(output), "deny")

        allowed = git_repo(with_remote=False)
        add_remote(allowed, bare_remote())
        self.assertIsNone(
            decision(
                run_hook(
                    "git_guard.py",
                    bash_payload("git push --force-with-lease origin main", allowed),
                )
            )
        )

    def test_push_remote_prefers_the_explicit_remote_with_dash_u(self):
        repo = git_repo(with_remote=False)
        decoy = bare_remote()
        add_remote(repo, decoy, name="decoy")
        push_branch(repo, "decoy", "main")
        set_config(repo, "branch.main.remote", "decoy")
        add_remote(repo, bare_remote())
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload("git push -u origin main", repo)))
        )

    def test_push_remote_resolves_a_url(self):
        repo = git_repo(with_remote=False)
        remote = bare_remote()
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload(f"git push file://{remote} main", repo)))
        )

    def test_push_remote_falls_back_to_the_configured_branch_remote(self):
        repo = git_repo(with_remote=False)
        wrong_default = bare_remote()
        add_remote(repo, wrong_default, name="origin")
        push_branch(repo, "origin", "main")
        upstream = bare_remote()
        add_remote(repo, upstream, name="upstream")
        set_config(repo, "branch.main.remote", "upstream")
        self.assertIsNone(decision(run_hook("git_guard.py", bash_payload("git push", repo))))

    def test_push_remote_prefers_branch_push_remote_over_branch_remote(self):
        repo = git_repo(with_remote=False)
        decoy = bare_remote()
        add_remote(repo, decoy, name="origin")
        push_branch(repo, "origin", "main")
        upstream = bare_remote()
        add_remote(repo, upstream, name="upstream")
        set_config(repo, "branch.main.remote", "origin")
        set_config(repo, "branch.main.pushRemote", "upstream")
        self.assertIsNone(decision(run_hook("git_guard.py", bash_payload("git push", repo))))

    def test_push_remote_prefers_remote_push_default_over_branch_remote(self):
        repo = git_repo(with_remote=False)
        decoy = bare_remote()
        add_remote(repo, decoy, name="origin")
        push_branch(repo, "origin", "main")
        upstream = bare_remote()
        add_remote(repo, upstream, name="upstream")
        set_config(repo, "branch.main.remote", "origin")
        set_config(repo, "remote.pushDefault", "upstream")
        self.assertIsNone(decision(run_hook("git_guard.py", bash_payload("git push", repo))))


class CommandShapeTest(unittest.TestCase):
    """The push, branch and bypass rules apply wherever git runs in the command, not only
    when git is its first word. Runs on linux, where the macOS only network shape rule
    stays out of the way, so each case shows the guard rule on its own."""

    def setUp(self):
        self.repo = git_repo()
        checkout_feature(self.repo)

    def check(self, command: str) -> Optional[str]:
        return decision(run_main_in_process(command, self.repo, "linux"))

    def assert_denied(self, commands: list[str]):
        for command in commands:
            self.assertEqual(self.check(command), "deny", command)

    def assert_allowed(self, commands: list[str]):
        for command in commands:
            self.assertIsNone(self.check(command), command)

    def test_denies_push_to_default_branch_after_a_global_option(self):
        self.assert_denied(
            [
                "git --no-pager push origin main",
                "git -P push origin main",
                "git -p push origin main",
                "git --paginate push origin main",
                "git --bare push origin main",
                "git --no-replace-objects push origin main",
                "git --no-lazy-fetch push origin main",
                "git --no-optional-locks push origin main",
                "git --no-advice push origin main",
                "git --literal-pathspecs push origin main",
                "git --glob-pathspecs push origin main",
                "git --noglob-pathspecs push origin main",
                "git --icase-pathspecs push origin main",
                "git --exec-path=/usr/libexec/git-core push origin main",
                "git --namespace=team push origin main",
                "git --namespace team push origin main",
                "git --config-env=core.pager=PAGER push origin main",
                "git --attr-source=HEAD push origin main",
                "git --no-pager -c color.ui=never push origin main",
            ]
        )

    def test_denies_push_to_default_branch_after_a_global_option_with_a_separate_value(self):
        self.assert_denied(
            [
                "git --config-env core.pager=PAGER push origin main",
                "git --attr-source HEAD push origin main",
            ]
        )

    def test_denies_force_push_and_default_branch_delete_after_a_global_option(self):
        self.assert_denied(
            [
                "git --no-pager push --force origin feat/thing",
                "git -P push origin +feat/thing",
                "git --no-pager push --mirror origin",
                "git --no-pager branch -D main",
            ]
        )

    def test_denies_push_to_default_branch_inside_a_subshell_or_group(self):
        self.assert_denied(
            [
                "(git push origin main)",
                "( git push origin main )",
                "{ git push origin main; }",
                "! git push origin main",
                "git status && (git push origin main)",
                "git status; (git push origin main)",
                f"(cd {self.repo} && git push origin main)",
                "if true; then git push origin main; fi",
            ]
        )

    def test_denies_force_push_and_hook_bypass_inside_a_subshell_or_group(self):
        self.assert_denied(
            [
                "(git push --force origin feat/thing)",
                "{ git push -f origin feat/thing; }",
                "(git commit --no-verify -m 'fix: thing')",
                "(git branch -D main)",
            ]
        )

    def test_denies_push_to_default_branch_inside_a_command_substitution(self):
        self.assert_denied(
            [
                "$(git push origin main)",
                'echo "$(git push origin main)"',
                "result=$(git push origin main)",
                "`git push origin main`",
                'echo "`git push origin main`"',
                'echo "$(echo ")"; git push origin main)"',
                "cat <(git push origin main)",
            ]
        )

    def test_denies_push_to_default_branch_passed_to_a_shell_or_eval(self):
        self.assert_denied(
            [
                "bash -c 'git push origin main'",
                'sh -c "git push origin main"',
                "bash -lc 'git status && git push origin main'",
                "bash -o pipefail -c 'git push --force origin feat/thing'",
                'sh -c "git push origin \\"main\\""',
                "eval 'git push origin main'",
                "eval git push origin main",
                "sudo sh -c 'git commit --no-verify -m x'",
            ]
        )

    def test_denies_push_to_default_branch_piped_into_a_shell(self):
        self.assert_denied(
            [
                "echo 'git push origin main' | sh",
                "printf '%s\\n' 'git push --force origin feat/thing' | bash",
                "bash <<< 'git push origin main'",
                "bash <<'EOF'\ngit push origin main\nEOF",
            ]
        )

    def test_denies_push_to_default_branch_behind_any_command_prefix(self):
        self.assert_denied(
            [
                "timeout 60 git push origin main",
                "echo done | xargs git push origin main",
                "watch -n 5 git push --force origin feat/thing",
                "sudo -u git git push origin main",
            ]
        )

    def test_denies_a_push_whose_refs_come_from_xargs(self):
        self.assert_denied(
            [
                "echo main | xargs git push origin",
                "printf 'main' | xargs -I{} git push origin {}",
            ]
        )

    def test_denies_push_to_default_branch_split_by_a_line_continuation(self):
        self.assert_denied(
            [
                "git push origin \\\nmain",
                "git commit \\\n  --no-verify -m 'fix: thing'",
                "git branch -D \\\nmain",
            ]
        )

    def test_denies_push_to_default_branch_with_a_quoted_or_attached_refspec(self):
        self.assert_denied(
            [
                'git push origin "main"',
                "git push origin 'HEAD:main'",
                "git push origin ma\\in",
                'git push "--force" origin feat/thing',
                "git push origin main>/dev/null",
                "git push origin main&",
                "git branch -D 'main'",
            ]
        )

    def test_denies_push_to_default_branch_through_a_command_line_alias(self):
        self.assert_denied(
            [
                "git -c alias.p=push p origin main",
                "git -c alias.p=push p --force origin feat/thing",
                "git -c 'alias.p=!git push origin main' p",
                "git -c 'alias.c=commit --no-verify' c -m x",
            ]
        )

    def test_allows_feature_branch_pushes_in_the_same_shapes(self):
        self.assert_allowed(
            [
                "git --no-pager push origin feat/thing",
                "git --config-env core.pager=PAGER push origin feat/thing",
                "(git push origin feat/thing)",
                "{ git push --force-with-lease origin feat/thing; }",
                'echo "$(git push origin feat/thing)"',
                "bash -c 'git push origin feat/thing'",
                "eval 'git push -u origin feat/thing'",
                "timeout 60 git push origin feat/thing",
                "git push origin \\\nfeat/thing",
                "git push origin feat/thing>/dev/null",
                "git -c alias.p=push p origin feat/thing",
                "(git status) && git log --oneline",
                "echo 'git push origin main'",
            ]
        )

    def test_allows_a_quoted_heredoc_that_mentions_a_guarded_command(self):
        self.assert_allowed(
            [
                "git commit -m \"$(cat <<'EOF'\nfix: stop git push origin main\n\n"
                'Never git push --force or git branch -D main.\nEOF\n)"',
                "cat <<'EOF' > notes.txt\ngit push origin main\ngit branch -D main\nEOF",
                "cat <<-EOF > notes.txt\n\tgit push origin main\n\tEOF",
                "cat <<'EOF' > notes.md\nThe hook reads $(git push origin main) as a call.\nEOF",
                "cat <<'A' <<'B' > notes.txt\ngit push origin main\nA\n"
                "git push --force origin feat/thing\nB",
                "echo $((1 << shift))\ngit status",
            ]
        )

    def test_denies_a_substitution_inside_an_unquoted_heredoc(self):
        self.assert_denied(
            [
                "cat <<EOF > notes.txt\n$(git push origin main)\nEOF",
                "cat <<'A' <<B > notes.txt\nplain\nA\n$(git push origin main)\nB",
                "echo $((1 << shift))\ngit push origin main\nshift",
            ]
        )

    def test_allows_a_shell_name_that_is_not_fed_commands(self):
        self.assert_allowed(
            [
                "echo 'git push --force origin feat/thing' > notes.txt; which sh",
                "echo 'git push origin main' > notes.txt && command -v bash",
                "shfmt -ln bash -d scripts && echo 'git push --force origin feat/thing'",
                "chsh -s /bin/zsh; echo 'git branch -D main' > notes.txt",
                "pgrep bash; echo 'git push origin main'",
                "bash; echo 'git push --force origin feat/thing' > notes.txt",
                "echo 'git push origin main' | cat > sh",
                "command -v bash && cat <<'EOF' > notes.md\n"
                "git push --force origin feat/thing\nEOF",
            ]
        )

    def test_allows_a_bypass_flag_inside_a_message_or_search_argument(self):
        self.assert_allowed(
            [
                "git commit -m 'feat: deny --no-verify behind a subshell'",
                "git log -S'--no-verify' --oneline",
                "git commit -m 'chore: drop -c commit.gpgsign=false from docs'",
                "git log --grep='--no-gpg-sign' --oneline",
                "git commit -s -m \"$(cat <<'EOF'\nfix(hooks): read options\n\n"
                'Never use git push --force or --no-verify.\nEOF\n)"',
                "git push -n origin feat/thing",
            ]
        )

    def test_denies_a_bypass_flag_that_stands_as_its_own_word(self):
        self.assert_denied(
            [
                "git commit -n -m 'fix: thing'",
                "git -c COMMIT.GPGSIGN=false commit -m 'fix: thing'",
                "git push --no-verify origin feat/thing",
                "git rebase --no-verify main",
                "git commit -m 'fix: thing' --no-gpg-sign",
            ]
        )

    def test_denies_a_force_flag_inside_a_cluster_of_short_push_flags(self):
        self.assert_denied(
            [
                "git push -uf origin feat/thing",
                "git push -fu origin feat/thing",
                "git push -vf origin feat/thing",
                "git push -fo ci.skip origin feat/thing",
            ]
        )
        self.assert_allowed(
            [
                "git push -of origin feat/thing",
                "git push -uo ci.skip origin feat/thing",
                "git push -uv origin feat/thing",
            ]
        )

    def test_denies_a_hook_bypass_inside_a_cluster_of_short_commit_flags(self):
        self.assert_denied(
            [
                "git commit -an -m 'fix: thing'",
                "git commit -nm 'fix: thing'",
                "git commit -anm 'fix: thing'",
            ]
        )
        self.assert_allowed(
            [
                "git commit -mn",
                "git commit -am 'fix: thing'",
                "git commit -sm 'fix: thing'",
                "git commit -m -n",
            ]
        )

    def test_denies_an_abbreviated_long_option_of_push_or_commit(self):
        self.assert_denied(
            [
                "git push --mirr origin",
                "git push --al origin",
                "git commit --no-veri -m 'fix: thing'",
                "git commit --no-gpg -m 'fix: thing'",
                "git push --no-verif origin feat/thing",
            ]
        )
        self.assert_allowed(
            [
                "git push --forc origin feat/thing",
                "git push --force-with origin feat/thing",
                "git push --set-up origin feat/thing",
                "git commit --amen --no-edit",
            ]
        )

    def test_denies_config_that_skips_hooks_or_signing(self):
        self.assert_denied(
            [
                "git -c core.hooksPath=/dev/null commit -m 'fix: thing'",
                "git -c commit.gpgsign=0 commit -m 'fix: thing'",
                "git -c commit.gpgsign=no commit -m 'fix: thing'",
                "git -c commit.gpgsign=off commit -m 'fix: thing'",
                "git -c commit.gpgsign= commit -m 'fix: thing'",
                "git -c tag.gpgSign=false tag -a v1.2.3 -m v1.2.3",
                "git --config-env=core.hooksPath=HOOKS commit -m 'fix: thing'",
                "git --config-env commit.gpgsign=SIGN commit -m 'fix: thing'",
                "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null "
                "git commit -m 'fix: thing'",
                "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign "
                "GIT_CONFIG_VALUE_0=false; git commit -m 'fix: thing'",
                "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\" git commit -m 'fix: thing'",
            ]
        )
        self.assert_allowed(
            [
                "git -c commit.gpgsign=true commit -m 'fix: thing'",
                "git -c commit.gpgsign commit -m 'fix: thing'",
                "git -c commit.gpgsign=yes commit -m 'fix: thing'",
                "git -c core.pager=cat log -1",
                "git -c color.ui=always diff",
                "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=true "
                "git commit -m 'fix: thing'",
            ]
        )

    def test_denies_config_that_widens_a_push(self):
        self.assert_denied(
            [
                "git -c push.default=matching push origin",
                "git -c remote.origin.mirror=true push origin",
                "git -c remote.origin.push=HEAD:refs/heads/main push origin",
                "git -c Remote.Origin.Push=HEAD:refs/heads/main push",
            ]
        )

    def test_denies_a_config_write_that_skips_hooks_or_signing_or_widens_a_push(self):
        self.assert_denied(
            [
                "git config core.hooksPath /dev/null",
                "git config commit.gpgsign false",
                "git config --global commit.gpgsign false",
                "git config set core.hooksPath /dev/null",
                "git config --bool tag.gpgsign off",
                "git config --global --unset commit.gpgsign",
                "git config remote.origin.push HEAD:refs/heads/main",
                "git config --add remote.origin.push HEAD:refs/heads/main",
                "git config remote.origin.mirror true",
                "git config push.default matching",
            ]
        )
        self.assert_allowed(
            [
                "git config --get remote.origin.url",
                "git config --get-all remote.origin.push 'refs/heads/.*'",
                "git config core.hooksPath",
                "git config get core.hooksPath",
                "git config --list",
                "git config commit.gpgsign true",
                "git config user.name 'dev'",
                "git config --unset core.hooksPath",
            ]
        )

    def test_denies_a_push_whose_destination_is_the_default_branch_or_a_pattern(self):
        self.assert_denied(
            [
                "git push origin heads/main",
                "git push origin HEAD:heads/main",
                "git push origin 'refs/heads/*:refs/heads/*'",
                "git push origin 'feat/*'",
                "git push origin :",
            ]
        )
        self.assert_allowed(
            [
                "git push origin :feat/old",
                "git push origin heads/feat/thing",
                "git push origin feat/thing:feat/thing",
            ]
        )

    def test_denies_a_push_whose_ref_the_shell_builds(self):
        self.assert_denied(
            [
                "git push origin {main,}",
                "git push origin $'main'",
                'git push origin "$BRANCH"',
                "git push origin `echo main`",
                "git push origin $(echo main) --force-with-lease",
            ]
        )
        self.assert_allowed(
            [
                'git push -u origin "$(git branch --show-current)"',
                "git push -u origin $(git rev-parse --abbrev-ref HEAD)",
            ]
        )

    def test_denies_send_pack_and_update_ref_on_the_default_branch(self):
        self.assert_denied(
            [
                "git send-pack ../remote.git feat/thing:main",
                "git send-pack --all ../remote.git",
                "git send-pack ../remote.git",
                "git send-pack --force ../remote.git feat/thing",
                "git update-ref -d refs/heads/main",
                "printf 'delete refs/heads/main\\n' | git update-ref --stdin",
            ]
        )
        self.assert_allowed(
            [
                "git send-pack ../remote.git feat/thing",
                "git update-ref -d refs/heads/feat/old",
                "git update-ref refs/heads/feat/thing HEAD",
            ]
        )

    def test_denies_a_commit_or_force_delete_whose_arguments_come_from_xargs(self):
        self.assert_denied(
            [
                "echo --no-verify | xargs git commit -m 'fix: thing'",
                "echo main | xargs git branch -D",
            ]
        )
        self.assert_allowed(
            [
                "git branch --merged | grep -v main | xargs git branch -d",
                "git branch --merged main | grep -v '^\\*' | xargs -r git branch -d",
                "echo main | xargs -I{} git log --oneline {}",
            ]
        )

    def test_denies_git_named_in_another_case(self):
        self.assert_denied(
            [
                "GIT push --force origin feat/thing",
                "Git push origin main",
                "/usr/bin/GIT push origin main",
                "GIT commit --no-verify -m 'fix: thing'",
                "GIT branch -D main",
            ]
        )
        self.assert_allowed(["GIT status", "Git push origin feat/thing"])

    def test_denies_a_command_in_an_env_split_string(self):
        self.assert_denied(
            [
                "env -S 'git push origin main'",
                "env -S 'git push --force origin feat/thing'",
                "env -S'git push origin main'",
                "env --split-string='git push origin main'",
                "env --split-string 'git push origin main'",
            ]
        )
        self.assert_allowed(["env -S 'git push origin feat/thing'"])

    def test_denies_config_parameters_written_as_one_quoted_item(self):
        self.assert_denied(
            [
                "GIT_CONFIG_PARAMETERS=\"'core.hookspath=/dev/null'\" git commit -m 'fix: thing'",
                "GIT_CONFIG_PARAMETERS=\"'commit.gpgsign=false'\" git commit -m 'fix: thing'",
                "GIT_CONFIG_PARAMETERS=\"'commit.gpgsign'=''\" git commit -m 'fix: thing'",
            ]
        )
        self.assert_allowed(
            ["GIT_CONFIG_PARAMETERS=\"'commit.gpgsign=true'\" git commit -m 'fix: thing'"]
        )

    def test_denies_update_ref_whose_arguments_come_from_xargs(self):
        self.assert_denied(["echo refs/heads/main | xargs git update-ref -d"])

    def test_denies_a_subtree_push_to_the_default_branch(self):
        self.assert_denied(
            [
                "git subtree push --prefix=lib origin main",
                "git subtree push -P lib origin main",
                "git subtree push --prefix lib origin HEAD:main",
            ]
        )
        self.assert_allowed(["git subtree push --prefix=lib origin feat/thing"])

    def test_denies_only_the_push_default_values_that_widen_a_push(self):
        self.assert_denied(
            [
                "git -c push.default=matching push origin",
                "git -c push.default=upstream push",
                "git -c push.default=tracking push",
                "git config push.default matching",
            ]
        )
        self.assert_allowed(
            [
                "git -c push.default=current push",
                "git -c push.default=simple push",
                "git config push.default current",
            ]
        )

    def test_allows_help_of_send_pack_and_a_reflog_suffix_in_a_refspec(self):
        self.assert_allowed(
            [
                "git send-pack --help",
                "git send-pack -h",
                "git push origin feat/thing@{u}",
                "git push origin HEAD@{1}:feat/thing",
            ]
        )
        self.assert_denied(["git push origin {main,}", "git push origin feat/thing@{u}:main"])

    def test_allows_hooks_from_a_directory_inside_the_repository(self):
        self.assert_allowed(
            [
                "git config core.hooksPath .githooks",
                "git config core.hooksPath .husky/_",
                "git -c core.hooksPath=.githooks commit -m 'fix: thing'",
            ]
        )
        self.assert_denied(
            [
                "git config core.hooksPath /dev/null",
                "git config core.hooksPath ''",
                "git config core.hooksPath ~/hooks",
                "git config core.hooksPath ../elsewhere",
                "git config core.hooksPath .githooks/../../elsewhere",
                "git -c core.hooksPath=/tmp/hooks commit -m 'fix: thing'",
            ]
        )

    def test_allows_unsetting_signing_in_the_repository_but_not_in_a_wider_scope(self):
        self.assert_allowed(["git config --unset commit.gpgsign", "git config unset tag.gpgsign"])
        self.assert_denied(
            [
                "git config --global --unset commit.gpgsign",
                "git config --system --unset tag.gpgsign",
                "git config commit.gpgsign false",
            ]
        )

    def test_denies_a_push_fed_to_a_sourced_stdin(self):
        self.assert_denied(
            [
                "source /dev/stdin <<'EOF'\ngit push origin main\nEOF",
                ". /dev/stdin <<'EOF'\ngit push origin main\nEOF",
                "printf 'git push origin main\\n' | source /dev/stdin",
                ". /dev/stdin <<< 'git push origin main'",
                "source - <<'EOF'\ngit push --force origin feat/thing\nEOF",
            ]
        )
        self.assert_allowed(
            [
                "source ./env.sh",
                ". ~/.profile && git status",
                "source /dev/stdin <<'EOF'\ngit status\nEOF",
                "printf 'git push origin main' | source ./env.sh",
            ]
        )

    def test_denies_a_heredoc_body_that_eval_or_a_shell_runs(self):
        self.assert_denied(
            [
                "eval \"$(cat <<'EOF'\ngit push --force origin feat/thing\nEOF\n)\"",
                "bash -c \"$(cat <<'EOF'\ngit push origin main\nEOF\n)\"",
                "sh -c \"$(cat <<'EOF'\ngit push origin main\nEOF\n)\"",
                "eval \"$(printf '%s' 'git push --force origin feat/thing')\"",
                'eval "$(echo git push --force origin feat/thing)"',
            ]
        )
        self.assert_allowed(
            [
                "eval \"$(cat <<'EOF'\ngit status\nEOF\n)\"",
                "git commit -m \"$(cat <<'EOF'\nfix: git push --force\nEOF\n)\"",
                'eval "$(mise activate bash)"',
            ]
        )

    def test_denies_a_split_string_inside_a_cluster_of_env_flags(self):
        self.assert_denied(
            [
                "env -vS 'git push origin main'",
                "env -iS 'git push origin main'",
                "env -vS'git push origin main'",
                "env -u X -S 'git push origin main'",
            ]
        )
        self.assert_allowed(
            [
                "env -vS 'git push origin feat/thing'",
                "env -u S git status",
                "env -uS echo 'git push origin main'",
            ]
        )

    def test_reads_the_branch_as_unknown_after_a_switch_in_the_same_command(self):
        self.assert_denied(
            [
                "git checkout main && git push",
                "git switch main && git push origin HEAD",
                "git checkout -q main; git push -u origin HEAD",
                "git symbolic-ref HEAD refs/heads/main && git push",
                "git checkout - && git push origin HEAD",
                "git switch @{-1} && git push origin HEAD",
                'git checkout "$BRANCH" && git push origin HEAD',
                "git branch -m main && git push origin HEAD",
                "git checkout -B main && git push origin HEAD",
                "git checkout -B main feat/thing && git push origin HEAD",
            ]
        )
        self.assert_allowed(
            [
                "git checkout -- main && git push origin HEAD",
                "git switch -c feat/new && git push -u origin feat/new",
                "git checkout -b feat/new && git push -u origin HEAD",
                "git checkout main -- README.md && git push origin HEAD",
                "git checkout main && git push origin feat/thing",
                "git switch main && git pull --ff-only",
            ]
        )

    def on_default_branch(self) -> None:
        """Checks the fixture out on main, where the base reading denies a push of HEAD."""
        subprocess.run(
            ["git", "checkout", "-q", "main"], cwd=self.repo, check=True, capture_output=True
        )

    def test_reads_a_created_branch_after_a_switch_to_the_default_branch(self):
        self.assert_allowed(
            [
                "git checkout main && git checkout -b feat/new && git push -u origin HEAD",
                "git switch main && git switch -c feat/new && git push -u origin HEAD",
                "git switch main && git pull --ff-only && git switch --create feat/new && "
                "git push -q --set-upstream origin HEAD",
                "git checkout main && git checkout -q -b feat/new && git add README.md && "
                "git commit -m 'docs: fix typo; and a # sign' && git push origin HEAD",
                "git checkout main && git checkout --orphan feat/new && "
                "git commit -m 'chore: init' && git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git status && git diff && "
                "git log && git show && git push --quiet origin HEAD",
            ]
        )

    def test_reads_the_default_branch_when_the_last_switch_names_it(self):
        self.assert_denied(
            [
                "git checkout feat/thing && git checkout main && git push origin HEAD",
                "git checkout feat/thing && git checkout main && git push",
                "git switch -c feat/new && git switch main && git push -u origin HEAD",
                "git checkout -b feat/new && git checkout main && git push -u origin HEAD",
                "git checkout main && git checkout feat/thing && git checkout - && "
                "git push origin HEAD",
                "git checkout main && git checkout feat/thing && git checkout main && git push",
                "git checkout feat/thing; git checkout main\ngit push origin HEAD",
                "git checkout -b feat/new && git checkout -b main && git push origin HEAD",
                "git checkout main && git checkout -b Main && git push origin HEAD",
                "git checkout -b feat/new && git checkout main && git status && git push",
            ]
        )

    def test_keeps_the_default_branch_when_no_branch_creation_decides(self):
        self.assert_denied(
            [
                # A plain switch never decides: its word can be a path, a commit or an
                # alias of the default branch.
                "git checkout main && git checkout feat/thing && git push origin HEAD",
                "git checkout main && git switch feat/thing && git push",
                "git checkout main && git symbolic-ref HEAD refs/heads/feat/thing && git push",
                "git checkout main && git branch -m feat/renamed && git push -u origin HEAD",
                # A creation that may reset an existing branch, track a remote ref or
                # start elsewhere does not decide either.
                "git checkout main && git checkout -B feat/new && git push origin HEAD",
                "git checkout main && git switch -C feat/new && git push origin HEAD",
                "git checkout main && git switch --force-create feat/new && git push origin HEAD",
                "git checkout main && git checkout -b feat/new origin/main && git push",
                "git checkout main && git checkout -b feat/new -t origin/main && git push",
                "git checkout main && git switch -c feat/new --track origin/main && git push",
                'git checkout main && git checkout -b "$NEW" && git push origin HEAD',
                # Any separator other than && leaves the order to the shell.
                "git checkout main; git checkout -b feat/new && git push origin HEAD",
                "git checkout main\ngit checkout -b feat/new && git push origin HEAD",
                "git checkout main && git checkout -b feat/new; git push origin HEAD",
                "git checkout main && git checkout -b feat/new || true && git push origin HEAD",
                "git checkout main || git checkout -b feat/new && git push origin HEAD",
                "git checkout main && git checkout -b feat/new | git status && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new & git status && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new & sleep 1 && git push origin HEAD",
                "git checkout main && git checkout -b feat/new \\&& git push origin HEAD",
                # The shell reads `\&&` as a literal `&` and a background `&`.
                "git checkout main && git checkout -b feat/new\\&& git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git push origin HEAD # note",
                "git checkout main && git checkout -b feat/new \\\n&& git push origin HEAD",
                "git checkout main && (git checkout -b feat/new) && git push origin HEAD",
                "{ git checkout main && git checkout -b feat/new && git push origin HEAD; }",
                # A call between them that may move the branch or the repository.
                "git checkout main && git checkout -b feat/new && git stash branch main && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git rebase origin/main main && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git pull origin main && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git checkout main && git push",
                "git checkout main && git checkout -b feat/new && cd ../other && "
                "git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git -C ../other push origin HEAD",
                "git checkout main && git checkout -b feat/new && "
                "env GIT_DIR=../other/.git git push origin HEAD",
                "git checkout main && sh -c 'git checkout -b feat/new' && git push origin HEAD",
                "git checkout main && git checkout -b feat/new && "
                'git commit -m "`./to-main.sh`" && git push origin HEAD',
                "git checkout main && git checkout -b feat/new && "
                'git commit -m "$(./to-main.sh)" && git push origin HEAD',
                "git checkout main && git checkout -b feat/new && "
                "git commit -F <(git checkout main) && git push origin HEAD",
                # A failed switch leaves the branch as it was, and the push still runs.
                "git checkout main && git checkout feat/thing; git push origin HEAD",
                "git checkout main\ngit checkout feat/thing\ngit push origin HEAD",
                "git checkout main && git checkout feat/thing || true && git push origin HEAD",
                "git checkout main && true || git checkout feat/thing && git push origin HEAD",
                "git checkout main && git checkout feat/thing | cat && git push origin HEAD",
                "git checkout main && git checkout feat/thing & git push origin HEAD",
                "git checkout main && git checkout feat/thing & sleep 1 && git push origin HEAD",
                # A switch in a subshell, a group or a conditional does not lift it.
                "git checkout main && (git checkout feat/thing) && git push origin HEAD",
                "git checkout main && ( git checkout feat/thing && git push origin HEAD )",
                "git checkout main && { git checkout feat/thing; } && git push origin HEAD",
                "(git checkout main; git checkout feat/thing) && git push origin HEAD",
                "git checkout main && if git checkout feat/thing; then git push origin HEAD; fi",
                "git checkout main && sh -c 'git checkout feat/thing' && git push origin HEAD",
                "git checkout main && echo $(git checkout feat/thing) && git push origin HEAD",
                # Something between the switch and the push may move the branch or the
                # repository.
                "git checkout main && git checkout feat/thing && cd ../other && "
                "git push origin HEAD",
                "git checkout main && git checkout feat/thing && git rebase origin/main main && "
                "git push origin HEAD",
                "git checkout main && git -C ../other checkout feat/thing && git push origin HEAD",
                "git checkout feat/thing && git push origin HEAD $(git checkout main)",
                'git checkout feat/thing && git commit -m "$(git checkout main)" && '
                "git push origin HEAD",
                # A part the hook reads as two git calls has no single place in the order.
                "git checkout main && git switch feat/thing && git log git checkout main && "
                "git push origin HEAD",
                "git checkout main && git branch -m other feat/thing && git push origin HEAD",
                "git checkout -t origin/main && git push origin HEAD",
                "git checkout --track=direct origin/main && git push origin HEAD",
                "git switch origin/main --no-track && git push origin HEAD",
            ]
        )

    def test_reads_a_branch_created_from_the_default_branch(self):
        self.on_default_branch()
        self.assert_allowed(
            [
                "git checkout -b feat/new && git push -u origin HEAD",
                "git switch -c feat/new && git push -u origin HEAD",
                "git checkout -b feat/new && git commit -m x && git push origin HEAD",
                "git checkout main && git checkout -b feat/new && git push -q origin HEAD",
            ]
        )
        self.assert_denied(
            [
                "git checkout feat/thing && git push origin HEAD",
                "git checkout -B main && git push",
                "git checkout -b feat/new || git push origin HEAD",
                "git checkout -b feat/new; git push origin HEAD",
                "git checkout -b feat/new && git push origin main",
                # Without an explicit HEAD, config decides where the push goes, such as
                # push.default=upstream with branch.autoSetupMerge=inherit.
                "git checkout -b feat && git commit -q --allow-empty -m 'chore: x' && git push -q",
                "git switch -c feat && git push",
                "git checkout -b feat && git push origin",
                "git checkout -b feat && git push -u",
                "git checkout -b feat/new && git push origin",
                "git checkout -b feat/new && git push -u origin",
                "git checkout -b feat/new && git push origin @",
                "git checkout -b feat && git push --repo=origin HEAD",
                "git checkout -b feat && git push -o ci.skip origin HEAD",
                "git checkout -b feat && git push --push-option=ci.skip origin HEAD",
                "git checkout -b feat && git push --force-with-lease origin HEAD",
                "git checkout -b feat && git push origin HEAD:main",
                "git checkout -b feat && git push origin HEAD main",
                "git checkout -b feat && git push origin +HEAD",
                # `:` pushes every matching branch, the default branch among them.
                "git checkout -b feat && git push origin :",
                "git checkout -b feat && git push origin HEAD :",
                "git checkout -b feat && git send-pack origin HEAD",
                # fetch runs a command of its own with --upload-pack, so it does not
                # keep the branch.
                "git checkout -b feat && git fetch -q --upload-pack "
                "'git checkout -q main; git-upload-pack' . && "
                "git commit -q --allow-empty -m 'chore: x' && git push -q origin HEAD",
                "git checkout -b feat && git fetch "
                "--upload-pack='git checkout main; git-upload-pack' origin && "
                "git push origin HEAD",
                "git checkout -b feat && git fetch -u 'git checkout main; git-upload-pack' "
                "origin && git push origin HEAD",
                "git checkout -b feat && git fetch origin && git push origin HEAD",
                # Nested calls are checked as well.
                "git checkout -b feat/new && git status sh -c 'git branch -D main'",
                "git checkout -b feat && git log sh -c 'git push --force origin main' && "
                "git push origin HEAD",
            ]
        )

    def test_denies_what_the_base_denied_after_a_switch_that_is_no_creation(self):
        """Shapes from the review of the first ordered reading. The base reading denies
        each of them from the default branch, and so must this one."""
        self.on_default_branch()
        subprocess.run(
            ["git", "symbolic-ref", "refs/heads/trunk", "refs/heads/main"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        self.assert_denied(
            [
                "git checkout . && git push origin HEAD",
                "git checkout . && git push",
                "git checkout HEAD && git push",
                "git checkout @ && git push origin HEAD",
                "git checkout README.md && git status && git push",
                "git checkout --theirs README.md && git add README.md && "
                "git commit --no-edit && git push",
                "git checkout --ours . && git add . && git commit --no-edit && "
                "git push origin HEAD",
                "git checkout -m README.md && git push origin HEAD",
                "git checkout --merge README.md && git push origin HEAD",
                "git checkout --conflict=merge README.md && git push origin HEAD",
                "git checkout --overlay README.md && git push origin HEAD",
                "git checkout -p README.md && git push origin HEAD",
                "git checkout -f README.md && git push origin HEAD",
                "git checkout --pathspec-from-file list && git push origin HEAD",
                "git symbolic-ref HEAD refs/heads/main && git checkout . && git push origin HEAD",
                "git checkout feat/thing && git checkout . && git push origin HEAD",
                "git checkout . && git send-pack origin HEAD",
                "git checkout . && git subtree push --prefix=x origin HEAD",
                'git checkout feat/thing && git commit -m "$(git rebase origin/main main)" && '
                "git push origin HEAD",
                'git checkout feat/thing && git commit -m "`git rebase origin/main main`" && '
                "git push origin HEAD",
                'git checkout feat/thing && git status "$(git rebase origin/main main)" && '
                "git push origin HEAD",
                'git checkout feat/thing && git commit -m "$(git stash branch main)" && '
                "git push origin HEAD",
                "git checkout feat/thing && git commit -m "
                "\"$(git -c alias.x='rebase origin/main main' x)\" && git push origin HEAD",
                "git checkout main # && git checkout feat/thing &&\ngit push origin HEAD",
                "git status # && git checkout feat/thing &&\ngit push origin HEAD",
                "git branch -m old && git checkout --no-track origin/main && "
                "git commit -q --allow-empty -m 'chore: x' && git push -q origin HEAD",
                "git branch -m old && git switch origin/main --track && "
                "git commit -q --allow-empty -m 'chore: x' && git push -q origin HEAD",
                "git checkout trunk && git push origin HEAD",
            ]
        )

    def test_answers_odd_input_without_failing(self):
        for command in [
            "$(",
            "(((",
            "`",
            "bash -c",
            "eval",
            "git -c",
            "git --namespace",
            "xargs git",
            "cat <<",
            "cat <<EOF",
            "echo $(echo $(echo $(echo $(echo $(echo $(echo $(git status)))))))",
            "(" * 200 + "git status" + ")" * 200,
            "bash -c " * 50 + "'git status'",
        ]:
            output = run_main_in_process(command, self.repo, "linux")
            self.assertIsInstance(output, dict, command)


def nested_shell(command: str, levels: int) -> str:
    """command wrapped in levels of `sh -c`."""
    for _ in range(levels):
        command = "sh -c " + shlex.quote(command)
    return command


# The longest a single pathological command may take in these tests. The hook itself
# aims at well under a second, the bound leaves room for a slow runner.
TIME_BOUND_SECONDS = 3.0
FORCE_PUSH = "git push --force origin feat/thing"


class ReadLimitTest(unittest.TestCase):
    """The guard reads every command within a bounded time, and denies a command that
    mentions git when it cannot read it in full."""

    def setUp(self):
        self.repo = git_repo()
        checkout_feature(self.repo)

    def timed(self, command: str, platform: str = "linux") -> tuple[Optional[str], float]:
        start = time.monotonic()
        output = run_main_in_process(command, self.repo, platform)
        return decision(output), time.monotonic() - start

    def test_denies_a_force_push_next_to_a_deep_substitution(self):
        for command in [
            FORCE_PUSH + " # " + "$(" * 1200,
            FORCE_PUSH + '; echo "' + "$(" * 1200 + '"',
            FORCE_PUSH + "; : " + "<(" * 1200,
            FORCE_PUSH + "; echo " + "$(" * 2000 + "x" + ")" * 2000,
            FORCE_PUSH + "; echo " + "`" * 3001,
            FORCE_PUSH + "; " + "(" * 3000,
        ]:
            verdict, seconds = self.timed(command)
            self.assertEqual(verdict, "deny", command[:80])
            self.assertLess(seconds, TIME_BOUND_SECONDS, command[:80])

    def test_denies_a_force_push_next_to_random_deep_nesting(self):
        rng = random.Random(210)
        pieces = ["$(", "(", ")", "`", '"', "'", "{ ", "; ", "<(", "\\", "<<A\n", " ", "git "]
        for _ in range(20):
            noise = "".join(rng.choice(pieces) for _ in range(3000))
            verdict, seconds = self.timed(FORCE_PUSH + "; " + noise)
            self.assertEqual(verdict, "deny", noise[:80])
            self.assertLess(seconds, TIME_BOUND_SECONDS, noise[:80])

    def test_reads_any_depth_of_substitution_without_an_error(self):
        for text in ["$(" * 5000, "echo " + "$(" * 3000 + "x" + ")" * 3000]:
            self.assertEqual(len(git_guard.substitutions(text)), 1)

    def test_denies_a_command_that_mentions_git_past_the_reading_deadline(self):
        with mock.patch.object(git_guard, "READ_SECONDS", -1.0):
            self.assertEqual(self.timed("git status")[0], "deny")
            self.assertIsNone(self.timed("ls -la")[0])

    def test_denies_a_command_that_mentions_git_when_reading_it_fails(self):
        with mock.patch.object(git_guard, "git_calls", side_effect=RuntimeError("unreadable")):
            self.assertEqual(self.timed("git status")[0], "deny")
            self.assertIsNone(self.timed("ls -la")[0])

    def test_answers_a_command_field_that_is_not_text_with_an_empty_response(self):
        payload = bash_payload("git status", self.repo)
        payload["tool_input"]["command"] = ["git", "push", "--force"]
        self.assertEqual(run_hook("git_guard.py", payload), {})

    def test_denies_a_push_inside_more_shell_levels_than_the_hook_reads(self):
        for levels in (9, 10):
            command = nested_shell("git push origin main", levels)
            self.assertEqual(self.timed(command)[0], "deny", levels)

    def test_reads_pathological_commands_within_the_time_bound(self):
        quoted_words = " ".join(["'git status'"] * 2000)
        substitution_lines = "line $(echo a) `b`\n" * 2000
        cases = [
            (FORCE_PUSH + "; echo " + "git " * 2000, "deny"),
            (FORCE_PUSH + "; echo " + "$(git status) " * 1000, "deny"),
            ("xargs " * 3000 + "git push origin main", "deny"),
            ("cat " + "<<A " * 2000 + "\n" + FORCE_PUSH, "deny"),
            ("cat notes | bash; echo " + quoted_words + "; " + FORCE_PUSH, "deny"),
            ("; ".join(["git status"] * 2000) + "; " + FORCE_PUSH, "deny"),
            ("cat <<EOF > notes.txt\n" + substitution_lines + "EOF\n" + FORCE_PUSH, "deny"),
            ("echo " + "a" * 200000 + "; " + FORCE_PUSH, "deny"),
            ("echo " + "a" * 200000 + "; git status", "deny"),
            ("git add " + "notes.txt " * 2500, "deny"),
            ("bash " * 3000 + "-c 'git status'", None),
            ("cat <<'EOF' > notes.txt\n" + "git push origin main\n" * 20000 + "EOF", None),
        ]
        for command, expected in cases:
            for platform in ("linux", "darwin"):
                verdict, seconds = self.timed(command, platform)
                self.assertEqual(verdict, expected, (platform, command[:80]))
                self.assertLess(seconds, TIME_BOUND_SECONDS, (platform, command[:80]))

    def slow_git(self, delay: float):
        """A stand in for subprocess.run that answers git's queries after delay seconds,
        as a slow machine would, and records every call."""
        calls: list[list[str]] = []

        def fake(args, **kwargs):
            argv = list(args)
            calls.append(argv)
            time.sleep(delay)
            answers = {
                ("rev-parse", "--abbrev-ref", "HEAD"): "feat/thing\n",
                ("rev-parse", "--show-toplevel"): self.repo + "\n",
                ("symbolic-ref", "refs/remotes/origin/HEAD"): "refs/remotes/origin/main\n",
                ("branch", "--list"): "  main\n* feat/thing\n",
            }
            answer = answers.get(tuple(argv[1:]))
            if argv[1:2] == ["ls-remote"]:
                answer = "abc\trefs/heads/main\n"
            return subprocess.CompletedProcess(argv, 0 if answer else 1, answer or "", "")

        return fake, calls

    def test_answers_many_guarded_calls_quickly_when_git_is_slow(self):
        fake, calls = self.slow_git(0.05)
        with mock.patch.object(subprocess, "run", fake):
            for command in [
                "; ".join(["git push"] * 199),
                "; ".join(f"git branch -d feat/old-{i}" for i in range(199)),
                "; ".join(f"git push origin feat/thing-{i}" for i in range(199)),
            ]:
                del calls[:]
                verdict, seconds = self.timed(command)
                self.assertIsNone(verdict, command[:60])
                self.assertLess(seconds, 1.0, command[:60])
                self.assertLess(len(calls), 20, command[:60])

    def test_denies_a_command_whose_git_queries_go_past_their_bound(self):
        fake, _ = self.slow_git(0.02)
        command = "; ".join(f"git -C ../repo-{i} push origin feat/thing" for i in range(199))
        with mock.patch.object(subprocess, "run", fake):
            verdict, seconds = self.timed(command)
        self.assertEqual(verdict, "deny")
        self.assertLess(seconds, TIME_BOUND_SECONDS)
        fake, _ = self.slow_git(0.3)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(subprocess, "run", fake))
            stack.enter_context(mock.patch.object(git_guard, "GIT_QUERY_SECONDS", 1.0))
            verdict, seconds = self.timed("; ".join(f"git -C ../repo-{i} push" for i in range(30)))
        self.assertEqual(verdict, "deny")
        self.assertLess(seconds, 1.0 + TIME_BOUND_SECONDS)

    def test_denies_a_command_that_mentions_git_when_the_working_directory_is_gone(self):
        gone = tempfile.mkdtemp(prefix="git-guard-gone-")
        hook = os.path.join(HOOKS_DIR, "git_guard.py")
        script = (
            "import json, os, subprocess, sys\n"
            "os.chdir(sys.argv[1])\n"
            "os.rmdir(sys.argv[1])\n"
            "for command in sys.argv[3:]:\n"
            "    payload = json.dumps({'tool_input': {'command': command}})\n"
            "    result = subprocess.run([sys.executable, sys.argv[2]], input=payload,\n"
            "                            capture_output=True, text=True)\n"
            "    print(result.returncode, result.stdout.strip() or '{}')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, gone, hook, "git push --force origin feat/thing", "ls"],
            capture_output=True,
            text=True,
            env=scratch_env(NO_SCRATCH),
        )
        first, second = result.stdout.splitlines()
        self.assertTrue(first.startswith("0 "), result.stdout)
        self.assertEqual(decision(json.loads(first[2:])), "deny")
        self.assertEqual(second, "0 {}")

    def test_blocks_the_command_when_the_hook_itself_fails(self):
        with open(os.path.join(HOOKS_DIR, "hooks.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        entry = next(hook for hook in manifest["hooks"] if hook["id"] == "git-guard")
        self.assertEqual(entry.get("onFailure"), "block")

    def test_denies_a_command_that_holds_a_nul_byte_and_mentions_git(self):
        for command in [
            "git push\x00 --force origin feat/thing",
            "git push origin ma\x00in",
            "gi\x00t push origin main",
            "git branch -D ma\x00in",
        ]:
            self.assertEqual(self.timed(command)[0], "deny", repr(command))
        self.assertIsNone(self.timed("echo a\x00b")[0])

    def assert_both_platforms(self, commands: list[str], expected: Optional[str]):
        for command in commands:
            for platform in ("linux", "darwin"):
                verdict, _ = self.timed(command, platform)
                self.assertEqual(verdict, expected, (platform, command))

    def test_denies_a_command_after_a_quoted_heredoc_whose_body_line_ends_in_a_backslash(self):
        body = "cat <<'EOF' > /dev/null\nx\\\nEOF\n"
        self.assert_both_platforms(
            [
                body + "git branch -D main",
                body + "git commit --no-verify -m 'fix: thing'",
                body + "git push origin main",
                body + FORCE_PUSH,
                body + FORCE_PUSH + "\nEOF",
            ],
            "deny",
        )
        self.assert_both_platforms([body + "git status"], None)

    def test_reads_an_unquoted_heredoc_body_line_that_ends_in_a_backslash(self):
        closed = "cat <<EOF > notes.txt\nline \\\nmore\nEOF\n"
        self.assert_both_platforms([closed + FORCE_PUSH], "deny")
        self.assert_both_platforms([closed + "git status"], None)
        self.assert_both_platforms(["cat <<EOF > /dev/null\nx\\\nEOF\n" + FORCE_PUSH], "deny")
        joined = "cat <<EOF > notes.txt\nx\\\nEOF\n" + FORCE_PUSH + "\nEOF\ngit status"
        self.assert_both_platforms([joined], None)

    def test_denies_a_command_after_a_marker_that_opens_no_heredoc(self):
        self.assert_both_platforms(
            [
                "# see <<EOF\n" + FORCE_PUSH,
                "echo hi # <<EOF\ngit branch -D main",
                "(( x = 1 <<y ))\n" + FORCE_PUSH,
                "echo $[1<<y]\n" + FORCE_PUSH,
                "echo $((1 << shift))\n" + FORCE_PUSH,
                "# see <<EOF\n" + FORCE_PUSH + "\nEOF",
                "(( x = 1 <<y ))\n" + FORCE_PUSH + "\ny",
                "echo $[1<<y]\n" + FORCE_PUSH + "\ny]",
                "echo $((1 << shift))\n" + FORCE_PUSH + "\nshift",
            ],
            "deny",
        )
        self.assert_both_platforms(["# see <<EOF\ngit status", "(( x = 1 <<y ))\ngit status"], None)

    def test_reads_the_body_of_a_heredoc_that_never_closes_as_commands(self):
        self.assert_both_platforms(
            [
                "cat <<EOF\n" + FORCE_PUSH,
                'cat <<"EOF"\nbody\n"EOF"\n' + FORCE_PUSH,
                "cat <<-'EOF'\n\tbody\n  EOF\n" + FORCE_PUSH,
                "cat << 'EOF'\nbody\nEOF \n" + FORCE_PUSH,
                ": <<EOF\nEOF\n" + FORCE_PUSH,
                "cat <<E\\OF\nbody\nEOF\n" + FORCE_PUSH,
                "echo x <<EOF; " + FORCE_PUSH + "\nbody\nEOF",
            ],
            "deny",
        )

    def test_denies_an_unreadable_command_that_spells_git_with_quotes_backslashes_or_case(self):
        pad = " # " + "a" * 100001
        self.assert_both_platforms(
            [
                "g''it push --force origin feat/thing" + pad,
                "g\\it push --force origin feat/thing" + pad,
                "GIT push --force origin feat/thing" + pad,
                nested_shell("g''it push origin main", 9),
                nested_shell("g\\it push origin main", 9),
            ],
            "deny",
        )
        self.assert_both_platforms(["echo hello" + pad], None)


class NetworkShapeTest(unittest.TestCase):
    """A git fetch, pull or push leaves the sandbox only when it stands alone in the
    call. Any other shape runs inside the sandbox and fails with a host key error."""

    def check(self, command: str, repo: str, platform: str = "darwin", tmpdir: str = NO_SCRATCH):
        return run_main_in_process(command, repo, platform, tmpdir)

    def test_denies_piped_git_push(self):
        repo = git_repo()
        checkout_feature(repo)
        out = self.check("git push origin feat/thing 2>&1 | tail -3", repo)
        self.assertEqual(decision(out), "deny")
        self.assertIn("alone", reason(out))
        self.assertIn("sandbox", reason(out))

    def test_denies_piped_git_fetch_and_pull(self):
        repo = git_repo()
        for command in ["git fetch --dry-run origin | tail -3", "git pull | cat"]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_git_network_command_with_stderr_redirect(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin feat/thing 2>/dev/null",
            "git fetch origin < /dev/null",
            "git pull 2>/dev/null",
            "git fetch origin 2>&1 > fetch.log",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_a_background_git_push(self):
        repo = git_repo()
        checkout_feature(repo)
        self.assertEqual(decision(self.check("git push origin feat/thing &", repo)), "deny")

    def test_allows_the_redirections_that_keep_the_call_outside_the_sandbox(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin feat/thing 2>&1",
            "git fetch origin 2>&1",
            "git pull >&2",
            "time git fetch --dry-run origin",
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_denies_an_env_prefix_before_a_git_network_command(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "FOO=1 git fetch --dry-run origin",
            "env X=1 git push origin feat/thing",
            "GIT_SSH_COMMAND=ssh git pull",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_a_global_option_before_the_network_subcommand(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git -c http.sslVerify=false fetch origin",
            "git --no-pager pull",
            f"git --git-dir={repo}/.git fetch origin",
            f"git --work-tree={repo} push origin feat/thing",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_allows_a_quoted_heredoc_body_that_names_a_network_command(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "cat <<'EOF' > notes.txt\ngit push origin main\ngit fetch origin\nEOF",
            "tee body.md <<'EOF'\ngit push --force\nEOF",
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_denies_a_global_option_with_a_separate_value_before_the_network_subcommand(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git --config-env core.pager=PAGER push origin feat/thing",
            "git --attr-source HEAD fetch origin",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_allows_network_shapes_on_other_platforms(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin feat/thing 2>&1 | tail -3",
            "git status && git fetch origin",
            f"git -C {repo} pull",
            "FOO=1 git fetch origin",
        ]:
            self.assertIsNone(decision(self.check(command, repo, platform="linux")), command)

    def test_default_branch_push_is_denied_on_other_platforms_too(self):
        repo = git_repo()
        checkout_feature(repo)
        out = self.check("git push origin main | tail -3", repo, platform="linux")
        self.assertEqual(decision(out), "deny")

    def test_allows_a_scratch_local_remote_in_any_shape(self):
        repo = git_repo()
        checkout_feature(repo)
        scratch = os.path.dirname(repo)
        for command in [
            "git push origin feat/thing 2>/dev/null",
            "git status && git push origin feat/thing",
        ]:
            out = self.check(command, repo, tmpdir=scratch)
            self.assertIsNone(decision(out), command)

    def test_denies_a_network_remote_in_a_scratch_repository(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        add_remote(repo, "git@example.com:org/repo.git")
        scratch = os.path.dirname(repo)
        out = self.check("git status && git push origin feat/thing", repo, tmpdir=scratch)
        self.assertEqual(decision(out), "deny")

    def test_allows_a_quoted_operator_in_a_network_argument(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            'git push origin "a>b"',
            'git push origin "feat/a&&b"',
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_denies_git_network_command_redirected_to_a_file(self):
        repo = git_repo()
        for command in ["git fetch origin > fetch.log", "git pull >> pull.log"]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_git_network_command_in_an_and_chain(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git status && git push origin feat/thing",
            "git push origin feat/thing && git status",
            "git fetch origin || echo failed",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_git_network_command_in_a_semicolon_chain(self):
        repo = git_repo()
        for command in ["git status; git fetch origin", "git pull; git log --oneline"]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_git_network_command_with_dash_c(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            f"git -C {repo} push origin feat/thing",
            f"git -C {repo} fetch origin",
            f"git -C {repo} pull",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_denies_git_network_command_behind_cd(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            f"cd {repo} && git push origin feat/thing",
            f"cd {repo}; git fetch origin",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_allows_git_network_commands_that_stand_alone(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push",
            "git push origin feat/thing",
            "git push -u origin feat/thing",
            "git push --force-with-lease origin feat/thing",
            "git fetch",
            "git fetch --dry-run origin",
            "git fetch origin main",
            "git pull",
            "git pull --ff-only origin feat/thing",
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_allows_git_commands_that_are_not_network_commands(self):
        repo = git_repo()
        for command in [
            "git log --oneline | head",
            "git status 2>&1",
            f"git -C {repo} status && git diff > out.patch",
            f"cd {repo} && git log",
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_allows_network_words_inside_quotes(self):
        repo = git_repo()
        for command in [
            'git commit -m "docs: say git push alone, not git push | tail"',
            "echo 'run git fetch > log; then git pull && git push'",
            "git commit -m \"$(cat <<'EOF'\nfix: git push 2>&1 stays alone\nEOF\n)\"",
        ]:
            self.assertIsNone(decision(self.check(command, repo)), command)

    def test_default_branch_push_stays_denied_in_every_shape(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push origin main",
            "git push origin main 2>&1 | tail -3",
            f"git -C {repo} push origin main",
            f"cd {repo} && git push origin main",
        ]:
            self.assertEqual(decision(self.check(command, repo)), "deny", command)

    def test_force_push_stays_denied_in_every_shape(self):
        repo = git_repo()
        checkout_feature(repo)
        for command in [
            "git push --force origin feat/thing",
            "git push --force origin feat/thing | tail -3",
            "git status && git push -f origin feat/thing",
        ]:
            out = self.check(command, repo)
            self.assertEqual(decision(out), "deny", command)

    def test_a_default_branch_denial_names_its_own_rule_first(self):
        repo = git_repo()
        checkout_feature(repo)
        out = self.check("git push origin main | tail -3", repo)
        self.assertIn("default branch", reason(out))


def git_in(repo: str, *args: str, env: Optional[dict[str, str]] = None) -> str:
    """Runs git in the fixture repository, fails the test on an error, returns stdout."""
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )
    return result.stdout.strip()


def commit_as(repo: str, author: str, committer: str, signoff: Optional[str] = None) -> None:
    """Makes one commit in the fixture repository with the given author and committer
    emails, and a Signed-off-by line for signoff when given."""
    name = "dev"
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=author,
        GIT_COMMITTER_NAME=name,
        GIT_COMMITTER_EMAIL=committer,
    )
    message = "fix: thing"
    if signoff:
        message += f"\n\nSigned-off-by: {name} <{signoff}>"
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


class CommitIdentityTest(unittest.TestCase):
    """A commit, rebase or cherry-pick under GIT_CONFIG_GLOBAL=/dev/null needs an explicit
    committer, and a push warns about commits whose identity differs from the author."""

    SWITCH = "GIT_CONFIG_GLOBAL=/dev/null"
    COMMITTER = "GIT_COMMITTER_EMAIL=dev@example.com"
    AUTHOR = "GIT_AUTHOR_EMAIL=dev@example.com"
    IDENTITY = f"GIT_COMMITTER_NAME=dev {COMMITTER} {AUTHOR}"

    def setUp(self):
        self.repo = git_repo()
        checkout_feature(self.repo)

    def check(self, command: str) -> dict[str, Any]:
        return run_main_in_process(command, self.repo, "linux")

    def assert_denied(self, commands: list[str]):
        for command in commands:
            out = self.check(command)
            self.assertEqual(decision(out), "deny", command)
            self.assertIn("GIT_COMMITTER_EMAIL", reason(out), command)

    def assert_allowed(self, commands: list[str]):
        for command in commands:
            self.assertEqual(self.check(command), {}, command)

    def test_denies_commit_rebase_and_cherry_pick_under_the_switch(self):
        self.assert_denied(
            [
                f"{self.SWITCH} git commit --signoff -m 'fix: thing'",
                f"{self.SWITCH} git commit --amend --no-edit",
                f"{self.SWITCH} git rebase --signoff origin/main",
                f"{self.SWITCH} git rebase --continue",
                f"{self.SWITCH} git cherry-pick abc1234",
                f"{self.SWITCH} git -c core.pager=cat commit -m 'fix: thing'",
            ]
        )

    def test_denies_the_switch_in_every_shape(self):
        self.assert_denied(
            [
                f"export {self.SWITCH} && git commit -m 'fix: thing'",
                f"export {self.SWITCH}; git rebase origin/main",
                f"env {self.SWITCH} git rebase origin/main",
                f"env -i {self.SWITCH} git commit -m 'fix: thing'",
                f"cd {self.repo} && {self.SWITCH} git commit -m 'fix: thing'",
                "GIT_CONFIG_GLOBAL='/dev/null' git commit -m 'fix: thing'",
                "GIT_CONFIG_GLOBAL=\"/dev/null\" git commit -m 'fix: thing'",
                f"sh -c '{self.SWITCH} git commit -m fix'",
                f"GIT_COMMITTER_EMAIL= {self.SWITCH} git commit -m 'fix: thing'",
            ]
        )

    def test_allows_an_explicit_committer(self):
        self.assert_allowed(
            [
                f"{self.SWITCH} {self.IDENTITY} git commit --signoff -m 'fix: thing'",
                f"{self.SWITCH} GIT_COMMITTER_EMAIL=dev@example.com git rebase origin/main",
                f"export {self.SWITCH} {self.IDENTITY} && git commit --amend --no-edit",
                f"export {self.IDENTITY}; {self.SWITCH} git cherry-pick abc1234",
                f"env {self.SWITCH} {self.IDENTITY} git rebase --continue",
                f"{self.SWITCH} git -c user.email=dev@example.com commit -m 'fix: thing'",
            ]
        )

    def test_allows_a_command_without_the_switch(self):
        self.assert_allowed(
            [
                "git commit -m 'fix: thing'",
                "git rebase origin/main",
                "git cherry-pick abc1234",
                "GIT_CONFIG_SYSTEM=/dev/null git commit -m 'fix: thing'",
                "GIT_CONFIG_GLOBAL=/home/dev/.gitconfig git commit -m 'fix: thing'",
                "GIT_AUTHOR_EMAIL=dev@example.com git commit -m 'fix: thing'",
            ]
        )

    def test_allows_the_switch_for_commands_that_write_no_commit(self):
        self.assert_allowed(
            [
                f"{self.SWITCH} git status",
                f"{self.SWITCH} git log --oneline -3",
                f"{self.SWITCH} git diff --stat",
                f"{self.SWITCH} git rebase --abort",
                f"{self.SWITCH} git cherry-pick --quit",
            ]
        )

    def test_allows_a_quoted_string_that_only_names_the_switch(self):
        self.assert_allowed(
            [
                'echo "GIT_CONFIG_GLOBAL=/dev/null git commit"',
                "echo 'GIT_CONFIG_GLOBAL=/dev/null git rebase origin/main'",
                'git commit -m "docs: GIT_CONFIG_GLOBAL=/dev/null is for tests"',
                'echo "GIT_CONFIG_GLOBAL=/dev/null"; git commit -m "fix: thing"',
                "git commit -m 'fix: thing' -- GIT_CONFIG_GLOBAL=/dev/null",
            ]
        )

    def test_a_deny_names_the_remedy(self):
        out = self.check(f"{self.SWITCH} git commit -m 'fix: thing'")
        for text in ("GIT_COMMITTER_EMAIL", "GIT_AUTHOR_EMAIL", "user.email", "normal git config"):
            self.assertIn(text, reason(out))
        self.assertLessEqual(reason(out).count(". "), 1)

    def test_a_new_commit_needs_an_author_email_besides_the_committer(self):
        self.assert_denied(
            [
                f"{self.SWITCH} GIT_COMMITTER_EMAIL=me@example.com git commit --signoff -m 'x'",
                f"{self.SWITCH} GIT_AUTHOR_EMAIL=me@example.com git commit -m 'x'",
                f"{self.SWITCH} {self.COMMITTER} git commit --amend --reset-author --no-edit",
            ]
        )
        self.assert_allowed(
            [
                f"{self.SWITCH} {self.COMMITTER} {self.AUTHOR} git commit -m 'x'",
                f"{self.SWITCH} {self.COMMITTER} git commit --author='Dev <dev@example.com>' -m x",
                f"{self.SWITCH} {self.COMMITTER} git commit --auth='Dev <dev@example.com>' -m x",
                f"{self.SWITCH} {self.COMMITTER} git commit --amend --no-edit",
                f"{self.SWITCH} {self.COMMITTER} git rebase --signoff origin/main",
                f"{self.SWITCH} {self.COMMITTER} git cherry-pick abc1234",
                f"{self.SWITCH} git -c user.email=dev@example.com commit -m 'x'",
            ]
        )

    def test_denies_the_switch_behind_grouping_and_env_options(self):
        self.assert_denied(
            [
                f"( {self.SWITCH} git commit -m x )",
                f"({self.SWITCH} git commit -m x)",
                f"{{ {self.SWITCH} git commit -m x; }}",
                f"env -u HOME {self.SWITCH} git commit -m x",
                f"env -uHOME {self.SWITCH} git commit -m x",
                f"env --unset HOME {self.SWITCH} git commit -m x",
                f"env --unset=HOME {self.SWITCH} git commit -m x",
                f"env -C /tmp {self.SWITCH} git commit -m x",
                f"env --chdir=/tmp {self.SWITCH} git commit -m x",
                f"env --chdir /tmp {self.SWITCH} git commit -m x",
                f"env -i -u HOME {self.SWITCH} git commit -m x",
                f"env -S '{self.SWITCH} git commit -m x'",
                f"local {self.SWITCH}; git commit -m x",
                f"declare -x {self.SWITCH} && git commit -m x",
                f"typeset -x {self.SWITCH} && git commit -m x",
                f"readonly {self.SWITCH} && git commit -m x",
                f"{self.SWITCH}; git commit -m x",
            ]
        )

    def test_denies_every_command_that_writes_a_commit(self):
        self.assert_denied(
            [
                f"{self.SWITCH} git merge origin/main",
                f"{self.SWITCH} git pull --rebase",
                f"{self.SWITCH} git pull",
                f"{self.SWITCH} git revert abc1234",
                f"{self.SWITCH} git am patch.mbox",
                f"{self.SWITCH} git commit-tree -m x HEAD^{{tree}}",
                f"{self.SWITCH} git notes add -m x",
            ]
        )
        self.assert_allowed(
            [
                f"{self.SWITCH} git merge --abort",
                f"{self.SWITCH} git am --abort",
                f"{self.SWITCH} git revert --quit",
                f"{self.SWITCH} {self.COMMITTER} {self.AUTHOR} git merge origin/main",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase",
                f"{self.SWITCH} {self.COMMITTER} git am patch.mbox",
            ]
        )

    def test_every_command_that_writes_a_new_commit_needs_the_author_email(self):
        self.assert_denied(
            [
                f"{self.SWITCH} {self.COMMITTER} git revert --no-edit HEAD",
                f"{self.SWITCH} {self.COMMITTER} git merge --no-ff -m m main",
                f"{self.SWITCH} {self.COMMITTER} git pull",
                f"{self.SWITCH} {self.COMMITTER} git pull --no-rebase",
                f"{self.SWITCH} {self.COMMITTER} git commit-tree -m x HEAD^{{tree}}",
                f"{self.SWITCH} {self.COMMITTER} git notes add -m x HEAD",
                f"{self.SWITCH} {self.COMMITTER} git commit -C HEAD --reset-author",
                f"{self.SWITCH} {self.AUTHOR} git revert --no-edit HEAD",
            ]
        )
        self.assert_allowed(
            [
                f"{self.SWITCH} {self.IDENTITY} git revert --no-edit HEAD",
                f"{self.SWITCH} {self.IDENTITY} git merge --no-ff -m m main",
                f"{self.SWITCH} git -c user.email=dev@example.com merge main",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase",
                f"{self.SWITCH} {self.COMMITTER} git pull -r",
                f"{self.SWITCH} {self.COMMITTER} git am patch.mbox",
                f"{self.SWITCH} {self.COMMITTER} git commit -C HEAD",
                f"{self.SWITCH} {self.COMMITTER} git commit -c HEAD --no-edit",
                f"{self.SWITCH} {self.COMMITTER} git commit --reuse-message=HEAD",
            ]
        )

    def test_writes_nothing_for_a_dry_run_and_the_read_verbs_of_notes(self):
        self.assert_allowed(
            [
                f"{self.SWITCH} git commit --dry-run -m x",
                f"{self.SWITCH} git notes",
                f"{self.SWITCH} git notes list",
                f"{self.SWITCH} git notes show HEAD",
                f"{self.SWITCH} git notes --ref refs/notes/review list",
            ]
        )
        self.assert_denied(
            [
                f"{self.SWITCH} {self.COMMITTER} git notes append -m x HEAD",
                f"{self.SWITCH} {self.COMMITTER} git notes edit HEAD",
                f"{self.SWITCH} {self.COMMITTER} git notes copy HEAD~1 HEAD",
                f"{self.SWITCH} {self.COMMITTER} git notes merge review",
                f"{self.SWITCH} {self.COMMITTER} git notes remove HEAD",
                f"{self.SWITCH} {self.COMMITTER} git notes prune",
                f"{self.SWITCH} {self.COMMITTER} git notes --ref list add -m x HEAD",
            ]
        )

    def test_denies_a_commit_in_a_string_handed_to_a_shell(self):
        self.assert_denied(
            [
                f"{self.SWITCH} sh -c 'git commit -m x'",
                f"{self.SWITCH} bash -c 'git commit -m x'",
                f"{self.SWITCH} eval 'git commit -m x'",
                f"env {self.SWITCH} sh -c 'git rebase origin/main'",
                f"export {self.SWITCH}; sh -c 'git commit -m x'",
                f"sh -c '{self.SWITCH} git commit -m x'",
                f"{self.SWITCH} {self.COMMITTER} sh -c 'git commit -m x'",
                f"{self.SWITCH} sh <<'EOF'\ngit commit -m x\nEOF",
                f"echo 'git commit -m x' | {self.SWITCH} sh",
                f"printf 'git status\\ngit commit -m x' | {self.SWITCH} sh",
            ]
        )
        self.assert_allowed(
            [
                "echo 'git commit -m x' | sh",
                f"echo 'git commit -m x' | {self.SWITCH} {self.IDENTITY} sh",
                f"export {self.SWITCH} && env --unset=GIT_CONFIG_GLOBAL git commit -m x",
                f"export {self.SWITCH} && env --unset GIT_CONFIG_GLOBAL git commit -m x",
                f"{self.SWITCH} sh -c 'git status'",
                "sh -c 'git commit -m x'",
                f"{self.SWITCH} {self.IDENTITY} sh -c 'git commit -m x'",
                f"{self.SWITCH} sh -c '{self.IDENTITY} git commit -m x'",
                f"{self.SWITCH} {self.COMMITTER} sh -c 'git rebase origin/main'",
            ]
        )

    def test_reads_which_pull_options_rebase(self):
        self.assert_denied(
            [
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=false",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=0",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=no",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=off",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=False",
                f"{self.SWITCH} {self.COMMITTER} git pull --no-rebase",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase --no-rebase",
                f"{self.SWITCH} {self.COMMITTER} git pull -r --rebase=false",
            ]
        )
        self.assert_allowed(
            [
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=true",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=merges",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=interactive",
                f"{self.SWITCH} {self.COMMITTER} git pull -r origin main",
                f"{self.SWITCH} {self.COMMITTER} git pull --no-rebase --rebase",
                f"{self.SWITCH} {self.COMMITTER} git pull --rebase=false --rebase",
            ]
        )

    def test_follows_export_and_unset_inside_a_string_handed_to_a_shell(self):
        self.assert_denied(
            [
                f"sh -c 'export {self.SWITCH}; git commit -m x'",
                f"bash -c 'export {self.SWITCH} && git commit -m x'",
                f"eval 'export {self.SWITCH}; git commit -m x'",
                f"{self.COMMITTER} sh -c 'export {self.SWITCH}; git commit -m x'",
                f"{self.SWITCH} {self.IDENTITY} sh -c 'unset GIT_COMMITTER_EMAIL; git commit -m x'",
                f"{self.SWITCH} {self.IDENTITY} sh -c 'unset GIT_AUTHOR_EMAIL; git commit -m x'",
            ]
        )
        self.assert_allowed(
            [
                f"export {self.SWITCH}; sh -c 'unset GIT_CONFIG_GLOBAL; git commit -m x'",
                f"sh -c 'export {self.SWITCH}; export {self.IDENTITY}; git commit -m x'",
                f"sh -c 'export {self.SWITCH}; git status; unset GIT_CONFIG_GLOBAL; git commit'",
            ]
        )

    def test_chains_the_prefix_through_every_level_of_nesting(self):
        self.assert_denied(
            [
                f"sh -c \"{self.SWITCH} sh -c 'git commit -m x'\"",
                f"{self.SWITCH} sh -c \"sh -c 'git commit -m x'\"",
                f"export {self.SWITCH}; sh -c \"bash -c 'git commit -m x'\"",
                f"sh -c \"sh -c 'export {self.SWITCH}; git commit -m x'\"",
                f"{self.SWITCH} git -c 'alias.ci=!git commit -m x' ci",
            ]
        )
        self.assert_allowed(
            [
                "sh -c \"sh -c 'git commit -m x'\"",
                f"{self.SWITCH} {self.IDENTITY} sh -c \"sh -c 'git commit -m x'\"",
                f"{self.SWITCH} {self.IDENTITY} git -c 'alias.ci=!git commit -m x' ci",
            ]
        )

    def test_reads_the_same_string_under_each_environment(self):
        self.assert_denied(
            [
                f"sh -c 'git commit -m x'; {self.SWITCH} sh -c 'git commit -m x'",
                f"{self.COMMITTER} {self.AUTHOR} sh -c 'git commit -m x'; "
                f"{self.SWITCH} sh -c 'git commit -m x'",
                f"{self.SWITCH} {self.IDENTITY} sh -c 'git commit -m x'; "
                f"{self.SWITCH} {self.AUTHOR} sh -c 'git commit -m x'",
                f"{self.SWITCH} {self.IDENTITY} sh -c 'git commit -m x'; "
                f"{self.SWITCH} {self.COMMITTER} sh -c 'git commit -m x'",
            ]
        )

    def test_denies_the_switch_behind_coproc(self):
        self.assert_denied([f"coproc {self.SWITCH} git commit -m x"])
        self.assert_allowed([f"coproc {self.SWITCH} git status"])

    def test_denies_the_switch_behind_shell_keywords(self):
        self.assert_denied(
            [
                f"time {self.SWITCH} git commit -m x",
                f"time -p {self.SWITCH} git commit -m x",
                f"if true; then {self.SWITCH} git commit -m x; fi",
                f"if true; then :; else {self.SWITCH} git commit -m x; fi",
                f"if false; then :; elif {self.SWITCH} git commit -m x; then :; fi",
                f"if {self.SWITCH} git commit -m x; then :; fi",
                f"for i in 1; do {self.SWITCH} git commit -m x; done",
                f"while {self.SWITCH} git commit -m x; do :; done",
                f"until {self.SWITCH} git commit -m x; do :; done",
                f"case x in x) {self.SWITCH} git commit -m x;; esac",
                f"case x in a|x) {self.SWITCH} git commit -m x;; esac",
                f"if true; then export {self.SWITCH}; fi; git commit -m x",
                f"! {self.SWITCH} git commit -m x",
                f"env --unset=HOME {self.SWITCH} git commit -m x",
            ]
        )
        self.assert_allowed(
            [
                f"time {self.SWITCH} {self.IDENTITY} git commit -m x",
                f"if true; then {self.SWITCH} git status; fi; git commit -m x",
                f"for i in 1; do {self.SWITCH} git status; done",
                "case x in x) git commit -m x;; esac",
            ]
        )

    def test_reads_abort_only_as_an_option_of_a_command_that_stops(self):
        self.assert_denied(
            [
                f"{self.SWITCH} git commit -m 'x --abort'",
                f"{self.SWITCH} git commit -m --abort",
                f"{self.SWITCH} git rebase -x 'echo --abort' origin/main",
            ]
        )

    def test_reads_c_only_among_the_options_in_front_of_the_subcommand(self):
        self.assert_denied(
            [
                f"{self.SWITCH} git commit -c abc123",
                f"{self.SWITCH} git commit -c user.email=dev@example.com -m x",
                f"{self.SWITCH} git -c user.email= commit -m x",
                f"{self.SWITCH} git -c user.name=dev commit -m x",
            ]
        )
        self.assert_allowed(
            [
                f"{self.SWITCH} git -c User.Email=dev@example.com commit -m x",
                f"{self.SWITCH} git -c user.EMAIL=dev@example.com rebase origin/main",
            ]
        )

    def test_reads_the_switch_as_the_file_system_does(self):
        self.assert_denied(
            [
                "GIT_CONFIG_GLOBAL=/dev//null git commit -m x",
                "GIT_CONFIG_GLOBAL=/dev/./null git commit -m x",
                "GIT_CONFIG_GLOBAL=/dev/null/ git commit -m x",
                "GIT_CONFIG_GLOBAL=//dev/null git commit -m x",
            ]
        )
        self.assert_allowed(
            [
                "GIT_CONFIG_GLOBAL=/dev/nullx git commit -m x",
                "GIT_CONFIG_GLOBAL=dev/null git commit -m x",
                "GIT_CONFIG_GLOBAL=/dev git commit -m x",
                "GIT_CONFIG_GLOBAL= git commit -m x",
            ]
        )

    def test_reads_each_part_with_its_own_variables(self):
        self.assert_denied(
            [
                f"{self.COMMITTER} git status && {self.SWITCH} git commit -m x",
                f"export {self.COMMITTER} GIT_AUTHOR_EMAIL=dev@example.com && unset "
                f"GIT_COMMITTER_EMAIL && {self.SWITCH} git commit -m x",
                f"export {self.SWITCH}; git status; git commit -m x",
                f"export {self.SWITCH} && git commit -m x | cat",
                f"export {self.SWITCH} && declare {self.IDENTITY} && git commit -m x",
                f"export {self.SWITCH} && declare -r {self.IDENTITY} && git commit -m x",
            ]
        )
        self.assert_allowed(
            [
                f"export {self.SWITCH} && declare -x {self.IDENTITY} && git commit -m x",
                f"git commit -m x && export {self.SWITCH}",
                f"{self.SWITCH} git status && git commit -m x",
                f"{self.SWITCH} git log --oneline | head -3; git commit -m x",
                f"export {self.SWITCH} && unset GIT_CONFIG_GLOBAL && git commit -m x",
                f"export {self.SWITCH} && env -u GIT_CONFIG_GLOBAL git commit -m x",
                f"export {self.SWITCH} && env -i git commit -m x",
                f"export {self.SWITCH} | cat; git commit -m x",
                f"export {self.SWITCH} && export {self.IDENTITY} && git commit -m x",
            ]
        )

    def test_the_hook_process_answers_the_deny_over_stdin(self):
        payload = bash_payload(f"{self.SWITCH} git commit -m 'fix: thing'", self.repo)
        self.assertEqual(decision(run_hook("git_guard.py", payload)), "deny")

    def test_warns_before_a_push_with_a_committer_other_than_the_author(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        out = self.check("git push origin feat/thing")
        self.assertIsNone(decision(out))
        self.assertIn("dev@host.local", context(out))
        self.assertIn("committer", context(out))

    def test_warns_before_a_push_with_a_sign_off_other_than_the_author(self):
        commit_as(self.repo, "dev@example.com", "dev@example.com", signoff="dev@host.local")
        out = self.check("git push origin feat/thing")
        self.assertIn("Signed-off-by dev@host.local", context(out))

    def test_warns_for_a_push_through_c_and_in_a_chain(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        for command in (
            f"git -C {self.repo} push origin feat/thing",
            "git status && git push origin feat/thing",
        ):
            self.assertIn("dev@host.local", context(self.check(command)), command)

    def test_warns_for_a_push_in_another_directory_given_with_c(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        outside = tempfile.mkdtemp(prefix="git-guard-plain-")
        out = run_main_in_process(f"git -C {self.repo} push origin feat/thing", outside, "linux")
        self.assertIn("dev@host.local", context(out))

    def test_warns_only_about_commits_the_upstream_lacks(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        push_branch(self.repo, "origin", "feat/thing")
        set_config(self.repo, "branch.feat/thing.remote", "origin")
        set_config(self.repo, "branch.feat/thing.merge", "refs/heads/feat/thing")
        commit_as(self.repo, "dev@example.com", "dev@example.com")
        self.assertEqual(self.check("git push origin feat/thing"), {})

    def test_a_quoted_word_is_no_assignment_in_front_of_a_command(self):
        self.assert_allowed(["\"GIT_CONFIG_GLOBAL=/dev/null\" git commit -m 'fix: thing'"])

    def test_no_warning_when_every_identity_matches(self):
        commit_as(self.repo, "dev@example.com", "DEV@example.com", signoff="dev@example.com")
        self.assertEqual(self.check("git push origin feat/thing"), {})

    def test_no_warning_for_a_command_that_pushes_nothing(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        for command in (
            "git status",
            "git log --oneline",
            "echo 'git push origin feat/thing'",
        ):
            self.assertEqual(self.check(command), {}, command)

    def test_no_warning_for_a_push_outside_a_repository(self):
        outside = tempfile.mkdtemp(prefix="git-guard-plain-")
        out = run_main_in_process("git push origin feat/thing", outside, "linux")
        self.assertEqual(out, {})

    def test_a_denied_push_stays_a_deny_without_the_warning(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        out = self.check("git push origin main")
        self.assertEqual(decision(out), "deny")
        self.assertEqual(context(out), "")

    def test_no_warning_for_commits_that_came_in_from_the_default_branch(self):
        git_in(self.repo, "checkout", "-q", "main")
        commit_as(self.repo, "dev@example.com", "noreply@github.com")
        push_branch(self.repo, "origin", "main")
        git_in(self.repo, "checkout", "-q", "feat/thing")
        env = dict(os.environ, GIT_COMMITTER_NAME="dev", GIT_COMMITTER_EMAIL="dev@example.com")
        git_in(self.repo, "merge", "-q", "--no-edit", "main", env=env)
        commit_as(self.repo, "dev@example.com", "dev@example.com")
        self.assertEqual(self.check("git push origin feat/thing"), {})
        git_in(self.repo, "rebase", "-q", "main", env=env)
        self.assertEqual(self.check("git push --force-with-lease origin feat/thing"), {})

    def test_warns_about_the_branch_a_push_names_and_not_the_one_checked_out(self):
        git_in(self.repo, "checkout", "-q", "-b", "feat/other")
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        git_in(self.repo, "checkout", "-q", "feat/thing")
        self.assertEqual(self.check("git push origin feat/thing"), {})
        self.assertIn("dev@host.local", context(self.check("git push origin feat/other")))
        refspec = "git push origin feat/other:feat/renamed"
        self.assertIn("dev@host.local", context(self.check(refspec)))

    def test_names_every_commit_and_says_when_the_log_was_cut(self):
        for _ in range(3):
            commit_as(self.repo, "dev@example.com", "dev@host.local")
        message = context(self.check("git push origin feat/thing"))
        self.assertIn("3 commit(s)", message)
        with mock.patch.object(git_guard, "PUSH_IDENTITY_COMMITS", 2):
            message = context(self.check("git push origin feat/thing"))
        self.assertIn("2 or more commit(s)", message)
        self.assertIn("HEAD --not --remotes", message)

    def test_no_warning_in_a_repository_without_a_remote_tracking_branch(self):
        repo = git_repo(with_remote=False)
        checkout_feature(repo)
        commit_as(repo, "dev@example.com", "dev@host.local")
        out = run_main_in_process("git push origin feat/thing", repo, "linux")
        self.assertEqual(context(out), "")

    def test_the_first_push_check_runs_git_with_the_file_system_monitor_off(self):
        seen = []
        real_run = subprocess.run

        def spy(args, **kwargs):
            if list(args)[1:2] == ["ls-remote"]:
                seen.append(kwargs.get("env") or {})
            return real_run(args, **kwargs)

        with mock.patch.object(subprocess, "run", spy):
            self.check("git push origin main")
        self.assertEqual(len(seen), 1)
        last = int(seen[0]["GIT_CONFIG_COUNT"]) - 1
        self.assertEqual(seen[0].get(f"GIT_CONFIG_KEY_{last}"), "core.fsmonitor")
        self.assertEqual(seen[0].get(f"GIT_CONFIG_VALUE_{last}"), "false")

    def test_no_warning_for_a_push_that_sends_nothing_from_head(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        for command in (
            "git push origin :feat/old",
            "git push origin +:feat/old",
            "git push origin --delete feat/old",
            "git push -d origin feat/old",
            "git push --tags",
            "git push --tags origin",
        ):
            self.assertEqual(context(self.check(command)), "", command)

    def test_a_push_that_sends_nothing_does_not_use_up_the_directory(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        command = "git push origin :feat/old; git push origin feat/thing"
        self.assertIn("dev@host.local", context(self.check(command)))

    def test_reads_the_refs_a_push_sends(self):
        revisions = git_guard.pushed_revisions
        self.assertEqual(revisions(["origin"]), ["HEAD"])
        self.assertEqual(revisions(["origin", "@"]), ["HEAD"])
        self.assertEqual(revisions(["origin", "HEAD", "@"]), ["HEAD"])
        self.assertEqual(revisions(["origin", "+feat/a:feat/b", "feat/c"]), ["feat/a", "feat/c"])
        self.assertEqual(revisions(["origin", "feat/a", ":feat/old"]), ["feat/a"])
        self.assertEqual(revisions(["origin", "refs/heads/*:refs/heads/*"]), ["HEAD"])
        self.assertEqual(revisions(["--delete", "origin"]), [])
        self.assertEqual(revisions(["-d", "origin"]), [])
        self.assertEqual(revisions(["-d", "origin", "feat/old"]), [])
        self.assertEqual(revisions(["--tags"]), [])
        self.assertEqual(revisions(["origin", "--delete", "feat/old"]), [])
        self.assertEqual(revisions(["--follow-tags", "origin"]), ["HEAD"])

    def test_warns_for_a_push_of_at(self):
        commit_as(self.repo, "dev@example.com", "dev@host.local")
        self.assertIn("dev@host.local", context(self.check("git push origin @")))

    def test_a_config_count_that_git_refuses_is_read_as_none(self):
        for count, expected in (("-1", "1"), ("abc", "1"), ("", "1"), ("0", "1"), ("2", "3")):
            env = git_guard._common.git_env({"GIT_CONFIG_COUNT": count})
            self.assertEqual(env["GIT_CONFIG_COUNT"], expected, count)
            last = int(expected) - 1
            self.assertEqual(env[f"GIT_CONFIG_KEY_{last}"], "core.fsmonitor", count)
            self.assertNotIn("GIT_CONFIG_KEY_-1", env)

    def test_no_warning_for_a_commit_without_a_sign_off(self):
        # The newest commit has no sign-off, and git prints an empty field for it.
        commit_as(self.repo, "dev@example.com", "dev@example.com", signoff="dev@example.com")
        commit_as(self.repo, "dev@example.com", "dev@example.com")
        commit_as(self.repo, "dev@example.com", "dev@example.com")
        self.assertEqual(self.check("git push origin feat/thing"), {})

    def test_asks_each_directory_once_and_reaches_the_next_one(self):
        other = git_repo()
        checkout_feature(other)
        commit_as(other, "dev@example.com", "dev@host.local")
        command = f"git push origin feat/thing; git push origin feat/thing; git -C {other} push"
        self.assertIn("dev@host.local", context(self.check(command)))

    def test_a_repository_config_does_not_run_a_program_during_the_check(self):
        marker = os.path.join(tempfile.mkdtemp(prefix="git-guard-marker-"), "ran")
        script = os.path.join(os.path.dirname(marker), "gpg.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        os.chmod(script, 0o755)
        set_config(self.repo, "gpg.program", script)
        set_config(self.repo, "log.showSignature", "true")
        tree = git_in(self.repo, "rev-parse", "HEAD^{tree}")
        head = git_in(self.repo, "rev-parse", "HEAD")
        body = (
            f"tree {tree}\nparent {head}\nauthor dev <dev@example.com> 1700000000 +0000\n"
            "committer dev <dev@host.local> 1700000000 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n"
            "\nfix: thing\n"
        )
        signed = subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
            cwd=self.repo,
            input=body,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_in(self.repo, "update-ref", "refs/heads/feat/thing", signed)
        git_in(self.repo, "log", "-1", "--show-signature")
        self.assertTrue(os.path.exists(marker), "the fixture must trigger the program")
        os.remove(marker)
        # Git writes the signature to a file in $TMPDIR before it calls the program, so
        # the run needs a directory that exists, one without the repository in it.
        scratch = tempfile.mkdtemp(prefix="git-guard-scratch-")
        out = run_main_in_process("git push origin feat/thing", self.repo, "linux", scratch)
        self.assertIn("dev@host.local", context(out))
        self.assertFalse(os.path.exists(marker))

    def test_git_reads_run_with_the_file_system_monitor_switched_off(self):
        env = git_guard._common.git_env({"PATH": "/bin", "GIT_CONFIG_COUNT": "2"})
        self.assertEqual(env["GIT_CONFIG_COUNT"], "3")
        self.assertEqual(env["GIT_CONFIG_KEY_2"], "core.fsmonitor")
        self.assertEqual(env["GIT_CONFIG_VALUE_2"], "false")
        self.assertEqual(git_guard._common.git_env({})["GIT_CONFIG_COUNT"], "1")
        marker = os.path.join(tempfile.mkdtemp(prefix="git-guard-marker-"), "ran")
        script = os.path.join(os.path.dirname(marker), "monitor.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        os.chmod(script, 0o755)
        set_config(self.repo, "core.fsmonitor", script)
        git_in(self.repo, "status", "--short")
        self.assertTrue(os.path.exists(marker), "the fixture must trigger the program")
        os.remove(marker)
        git_guard._common.run_git(["status", "--short"], self.repo)
        self.assertFalse(os.path.exists(marker))


class PackageCommandShapeTest(unittest.TestCase):
    """go get and the two exact pnpm install forms leave the sandbox only when they stand
    alone in the call (ADR 0008). Any other pnpm install gets context, never a deny."""

    FROZEN = "pnpm install --frozen-lockfile --ignore-scripts --ignore-pnpmfile"
    LOCKFILE_ONLY = "pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile"

    def setUp(self):
        self.cwd = tempfile.mkdtemp(prefix="git-guard-package-")

    def check(self, command: str, platform: str = "darwin"):
        return run_main_in_process(command, self.cwd, platform)

    def test_allows_a_standalone_go_get_and_the_exact_pnpm_forms(self):
        for command in [
            "go get github.com/ostendorf-cloud/govue@v0.9.0",
            "go get ./...",
            self.FROZEN,
            self.LOCKFILE_ONLY,
        ]:
            self.assertIsNone(decision(self.check(command)), command)

    def test_denies_a_chained_piped_or_cd_prefixed_go_get(self):
        for command in [
            "go get github.com/ostendorf-cloud/govue@v0.9.0 && go mod tidy",
            "cd api && go get ./...",
            "go get ./... | tail -3",
            "go get ./... 2>/dev/null",
        ]:
            out = self.check(command)
            self.assertEqual(decision(out), "deny", command)
            self.assertIn("alone", reason(out))
            self.assertIn("one call per directory", reason(out))

    def test_denies_an_env_prefix_or_an_option_before_go_get(self):
        for command in [
            "GOFLAGS=-mod=mod go get ./...",
            "env GOPROXY=direct go get ./...",
            "go -C api get ./...",
        ]:
            self.assertEqual(decision(self.check(command)), "deny", command)

    def test_denies_the_exact_pnpm_forms_when_they_do_not_stand_alone(self):
        for command in [
            f"cd web && {self.FROZEN}",
            f"{self.FROZEN} && pnpm build",
            f"{self.LOCKFILE_ONLY} | tail -3",
            f"CI=1 {self.FROZEN}",
        ]:
            self.assertEqual(decision(self.check(command)), "deny", command)

    def test_adds_context_for_a_pnpm_install_outside_the_exact_forms(self):
        for command in [
            "pnpm install",
            "pnpm install --frozen-lockfile",
            "pnpm install --dir web --frozen-lockfile --ignore-scripts --ignore-pnpmfile",
            "pnpm --dir web install --frozen-lockfile --ignore-scripts --ignore-pnpmfile",
            "cd web && pnpm install --offline",
            "pnpm install left-pad",
            f"{self.FROZEN} 2>&1",
        ]:
            out = self.check(command)
            self.assertIsNone(decision(out), command)
            self.assertIn("inside the sandbox", context(out), command)

    def test_adds_no_context_for_the_exact_forms_or_other_commands(self):
        for command in [self.FROZEN, self.LOCKFILE_ONLY, "pnpm build", "go test ./...", "ls"]:
            out = self.check(command)
            self.assertIsNone(decision(out), command)
            self.assertEqual(out, {}, command)

    def test_leaves_other_go_and_pnpm_commands_alone(self):
        for command in [
            "cd api && go test ./... && go mod tidy",
            "pnpm rebuild && pnpm build",
            "go mod download | tail -3",
            "echo go get is not run",
        ]:
            self.assertIsNone(decision(self.check(command)), command)

    def test_does_nothing_off_macos(self):
        for command in ["cd api && go get ./...", f"cd web && {self.FROZEN}", "pnpm install"]:
            self.assertEqual(self.check(command, "linux"), {}, command)


if __name__ == "__main__":
    unittest.main()
