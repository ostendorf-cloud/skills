# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for git_guard.py."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Optional
from unittest import mock

from helper import HOOKS_DIR, NO_SCRATCH, bash_payload, decision, reason, run_hook, scratch_env

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


if __name__ == "__main__":
    unittest.main()
