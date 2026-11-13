# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for git_guard.py."""

import subprocess
import tempfile
import unittest

from helper import bash_payload, decision, reason, run_hook


def git_repo() -> str:
    """A temporary repository on branch main with one commit."""
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
            "env git push --force-with-lease origin feat/thing",
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
        repo = git_repo()
        checkout_feature(repo)
        remote = bare_remote()
        add_remote(repo, remote)
        self.assertIsNone(
            decision(run_hook("git_guard.py", bash_payload("git push origin main", repo)))
        )

    def test_denies_push_to_default_branch_that_already_exists_on_remote(self):
        repo = git_repo()
        remote = bare_remote()
        add_remote(repo, remote)
        subprocess.run(
            ["git", "push", "-q", "origin", "main"], cwd=repo, check=True, capture_output=True
        )
        checkout_feature(repo)
        output = run_hook("git_guard.py", bash_payload("git push origin main", repo))
        self.assertEqual(decision(output), "deny")
        self.assertIn("already has", reason(output))

    def test_denies_push_to_default_branch_when_the_remote_check_fails(self):
        repo = git_repo()
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


if __name__ == "__main__":
    unittest.main()
