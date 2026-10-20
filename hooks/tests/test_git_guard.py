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


if __name__ == "__main__":
    unittest.main()
