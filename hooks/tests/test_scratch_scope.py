# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for the session scratch scope of shell_hygiene.py, commit_message.py and
git_guard.py.

Each hook ignores a throwaway fixture under the session scratch directory ($TMPDIR) and
keeps policing a real repository exactly as before. The layout of every test is one
parent directory holding `scratch` (the session scratch directory), `fixture` below it
(a fixture repository), `real` beside it (a real repository, outside the scratch scope)
and `real-remote` (a bare remote of that repository). The parent sits inside the
checkout, outside /tmp, because /tmp is an allowed redirect target on its own.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from helper import HOOKS_DIR, bash_payload, decision, reason, run_hook, scratch_env

CHECKOUT = os.path.dirname(HOOKS_DIR)


def git(path: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def make_repo(path: str, remote: str) -> None:
    """A repository on branch main with one commit and origin set to the bare remote,
    which already carries main, the way a clone of an existing repository does."""
    os.makedirs(path)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "dev@example.com")
    git(path, "config", "user.name", "dev")
    git(path, "config", "commit.gpgsign", "false")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("init\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "chore: init")
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True, capture_output=True)
    git(path, "remote", "add", "origin", remote)
    git(path, "push", "-q", "origin", "main")


class ScopeCase(unittest.TestCase):
    # Where the parent directory lives. A redirect test needs a directory outside /tmp,
    # which is an allowed redirect target on its own, so it uses plain directories
    # inside the checkout. The other tests use real repositories under the temporary
    # directory, because the sandbox does not let git write hooks inside the checkout.
    PARENT_DIR = None
    WITH_REPOSITORIES = True

    def setUp(self):
        self.parent = os.path.realpath(tempfile.mkdtemp(prefix=".scope-test-", dir=self.PARENT_DIR))
        self.addCleanup(shutil.rmtree, self.parent, ignore_errors=True)
        self.scratch = os.path.join(self.parent, "scratch")
        self.fixture = os.path.join(self.scratch, "fixture")
        self.fixture_remote = os.path.join(self.scratch, "fixture-remote.git")
        self.real = os.path.join(self.parent, "real")
        self.real_remote = os.path.join(self.parent, "real-remote.git")
        os.makedirs(self.scratch)
        if self.WITH_REPOSITORIES:
            make_repo(self.fixture, self.fixture_remote)
            make_repo(self.real, self.real_remote)
        else:
            os.makedirs(self.fixture)
            os.makedirs(self.real)
        self.env = scratch_env(self.scratch)

    def run_scoped(self, hook: str, command: str, cwd: str) -> dict:
        return run_hook(hook, bash_payload(command, cwd), env=self.env)

    def expect_allowed(self, hook: str, command: str, cwd: str) -> None:
        output = self.run_scoped(hook, command, cwd)
        self.assertIsNone(decision(output), f"{command} in {cwd}: {reason(output)}")

    def expect_denied(self, hook: str, command: str, cwd: str) -> None:
        output = self.run_scoped(hook, command, cwd)
        self.assertEqual(decision(output), "deny", f"{command} in {cwd}")


class RedirectScopeTest(ScopeCase):
    PARENT_DIR = CHECKOUT
    WITH_REPOSITORIES = False

    def test_allows_a_redirect_into_a_scratch_path(self):
        for command in [
            f"echo x > {self.scratch}/out.txt",
            "echo x > $TMPDIR/out.txt",
            'echo x > "${TMPDIR}/out.txt"',
            f"printf 'x' >> {self.scratch}/sub/dir/out.txt",
            "echo x | tee $TMPDIR/out.txt",
        ]:
            self.expect_allowed("shell_hygiene.py", command, self.real)

    def test_allows_a_relative_redirect_when_the_working_directory_is_scratch(self):
        for cwd in (self.scratch, self.fixture):
            for command in ["echo x > out.txt", "echo x | tee out.txt", "echo x >> ./sub/out.txt"]:
                self.expect_allowed("shell_hygiene.py", command, cwd)

    def test_denies_a_relative_redirect_inside_a_repository(self):
        for command in ["echo x > README.md", "echo x | tee README.md", "printf x > out.json"]:
            self.expect_denied("shell_hygiene.py", command, self.real)

    def test_denies_a_redirect_that_leaves_the_scratch_directory(self):
        for command in [
            f"echo x > {self.scratch}/../real/README.md",
            "echo x > $TMPDIR/../real/README.md",
            "echo x > ../real/README.md",
            f"echo x > {self.real}/README.md",
            "echo x | tee ../real/README.md",
        ]:
            self.expect_denied("shell_hygiene.py", command, self.scratch)

    def test_denies_a_redirect_after_a_cd_into_a_repository(self):
        for command in [
            f"cd {self.real} && echo x > README.md",
            "cd $TMPDIR/../real && echo x > README.md",
            "cd ../real && echo x > README.md",
            f"(cd {self.real} && echo x > README.md)",
            f"pushd {self.real} && echo x > README.md",
            "cd $SOMEWHERE && echo x > README.md",
        ]:
            self.expect_denied("shell_hygiene.py", command, self.scratch)

    def test_denies_a_redirect_through_a_symlink_that_points_out_of_scratch(self):
        os.symlink(self.real, os.path.join(self.scratch, "link"))
        for command in ["echo x > $TMPDIR/link/README.md", "echo x > link/README.md"]:
            self.expect_denied("shell_hygiene.py", command, self.scratch)

    def test_denies_a_redirect_when_the_command_makes_the_scope_unknown(self):
        for command in [
            "cd $TMPDIR/nonexistent; echo x > README.md",
            f"ln -s {self.real} $TMPDIR/l; echo x > $TMPDIR/l/README.md",
            f"export TMPDIR={self.real}; echo x > $TMPDIR/README.md",
            f"TMPDIR={self.real} sh -c 'echo x'; echo x > $TMPDIR/README.md",
        ]:
            self.expect_denied("shell_hygiene.py", command, self.scratch)

    def test_allows_a_redirect_after_a_cd_into_an_existing_scratch_directory(self):
        self.expect_allowed("shell_hygiene.py", "cd $TMPDIR && echo x > $TMPDIR/out.txt", self.real)

    def test_the_redirect_deny_names_its_scope(self):
        output = self.run_scoped("shell_hygiene.py", "echo x > README.md", self.real)
        self.assertIn("inside a repository", reason(output))


class CommitScopeTest(ScopeCase):
    ORDINARY = "git commit -m 'added some stuff'"

    def test_allows_an_ordinary_message_in_a_fixture_repository_under_scratch(self):
        for cwd in (self.fixture, self.scratch):
            self.expect_allowed("commit_message.py", self.ORDINARY, cwd)

    def test_allows_an_ordinary_message_for_a_fixture_reached_by_git_c_or_cd(self):
        for command in [
            f"git -C {self.fixture} commit -m 'added some stuff'",
            f"cd {self.fixture} && git commit -m 'added some stuff'",
            "cd $TMPDIR/fixture && git commit -m 'added some stuff'",
        ]:
            self.expect_allowed("commit_message.py", command, self.real)

    def test_denies_an_ordinary_message_in_a_repository(self):
        self.expect_denied("commit_message.py", self.ORDINARY, self.real)
        self.expect_denied("commit_message.py", "git commit -m 'wip: experiment'", self.real)
        self.expect_denied(
            "commit_message.py",
            "git commit -m 'feat: add thing' -m 'Co-Authored-By: Someone <a@example.com>'",
            self.real,
        )

    def test_denies_an_ordinary_message_after_a_cd_out_of_scratch(self):
        for command in [
            f"cd {self.real} && git commit -m 'added some stuff'",
            "cd $TMPDIR/../real && git commit -m 'added some stuff'",
            "cd ../real && git commit -m 'added some stuff'",
            f"cd {self.fixture} && cd {self.real} && git commit -m 'added some stuff'",
            f"git -C {self.real} commit -m 'added some stuff'",
            f"git -C {self.fixture} -C {self.real} commit -m 'added some stuff'",
            f"git --git-dir={self.real}/.git commit -m 'added some stuff'",
            f"GIT_DIR={self.real}/.git git commit -m 'added some stuff'",
            f"(cd {self.real} && git commit -m 'added some stuff')",
            "cd $SOMEWHERE && git commit -m 'added some stuff'",
        ]:
            self.expect_denied("commit_message.py", command, self.scratch)

    def test_denies_an_ordinary_message_when_scratch_is_not_the_session_scratch(self):
        output = run_hook(
            "commit_message.py",
            bash_payload(self.ORDINARY, self.fixture),
            env=scratch_env(os.path.join(self.parent, "elsewhere")),
        )
        self.assertEqual(decision(output), "deny")

    def test_denies_an_ordinary_message_when_the_command_makes_the_scope_unknown(self):
        message = "git commit -m 'added some stuff'"
        for command in [
            f"cd $TMPDIR/nonexistent; {message}",
            f"ln -s {self.real} $TMPDIR/l; cd $TMPDIR/l && {message}",
            f"export TMPDIR={self.real}; cd $TMPDIR && {message}",
            f"git -C $TMPDIR/nonexistent {message[4:]}",
        ]:
            self.expect_denied("commit_message.py", command, self.scratch)
            self.expect_denied("commit_message.py", command, self.real)

    def test_allows_an_ordinary_message_after_a_cd_into_an_existing_fixture(self):
        self.expect_allowed(
            "commit_message.py", "cd $TMPDIR/fixture; git commit -m 'added some stuff'", self.real
        )

    def test_the_commit_deny_names_its_scope(self):
        output = self.run_scoped("commit_message.py", self.ORDINARY, self.real)
        self.assertIn("inside a repository", reason(output))


class PushScopeTest(ScopeCase):
    def test_allows_a_push_to_main_of_a_fixture_with_a_bare_remote_under_scratch(self):
        self.expect_allowed("git_guard.py", "git push origin main", self.fixture)
        self.expect_allowed("git_guard.py", "git push", self.fixture)
        self.expect_allowed("git_guard.py", f"git push {self.fixture_remote} main", self.fixture)

    def test_allows_a_push_to_main_of_a_fixture_reached_by_git_c_or_cd(self):
        for command in [
            f"git -C {self.fixture} push origin main",
            f"cd {self.fixture} && git push origin main",
            "cd $TMPDIR/fixture && git push origin main",
        ]:
            self.expect_allowed("git_guard.py", command, self.real)

    def test_denies_a_push_to_main_of_a_real_repository(self):
        for command in ["git push origin main", "git push", f"git push {self.real_remote} main"]:
            self.expect_denied("git_guard.py", command, self.real)

    def test_denies_a_push_to_main_after_a_cd_out_of_scratch(self):
        for command in [
            f"cd {self.real} && git push origin main",
            "cd $TMPDIR/../real && git push origin main",
            "cd ../real && git push origin main",
            f"cd {self.fixture} && cd {self.real} && git push origin main",
            f"git -C {self.real} push origin main",
            f"git -C {self.fixture} -C {self.real} push origin main",
            f"git --git-dir={self.real}/.git push origin main",
            f"GIT_DIR={self.real}/.git git push origin main",
            "cd $SOMEWHERE && git push origin main",
        ]:
            self.expect_denied("git_guard.py", command, self.scratch)

    def test_denies_a_push_to_main_through_a_symlink_that_points_out_of_scratch(self):
        os.symlink(self.real, os.path.join(self.scratch, "link"))
        self.expect_denied("git_guard.py", "cd $TMPDIR/link && git push origin main", self.scratch)

    def test_denies_a_push_to_main_from_a_fixture_to_a_remote_outside_scratch(self):
        git(self.fixture, "remote", "set-url", "origin", self.real_remote)
        self.expect_denied("git_guard.py", "git push origin main", self.fixture)
        self.expect_denied("git_guard.py", f"git push {self.real_remote} main", self.fixture)

    def test_denies_a_push_to_main_from_a_fixture_to_a_remote_that_leaves_scratch_by_dots(self):
        url = os.path.join(self.scratch, "..", "real-remote.git")
        git(self.fixture, "remote", "set-url", "origin", url)
        self.expect_denied("git_guard.py", "git push origin main", self.fixture)

    def test_denies_a_push_to_main_from_a_fixture_to_a_network_style_remote(self):
        for url in ["file:///nonexistent/remote.git", "git@example.invalid:o/r.git"]:
            git(self.fixture, "remote", "set-url", "origin", url)
            self.expect_denied("git_guard.py", "git push origin main", self.fixture)

    def test_denies_a_push_to_main_from_a_real_repository_to_a_remote_under_scratch(self):
        git(self.real, "remote", "set-url", "origin", self.fixture_remote)
        self.expect_denied("git_guard.py", "git push origin main", self.real)

    def test_still_denies_force_pushes_and_hook_bypass_inside_scratch(self):
        for command in [
            "git push --force origin main",
            "git push --force origin feature",
            "git push --all origin",
            "git commit --no-verify -m 'feat: add thing'",
        ]:
            self.expect_denied("git_guard.py", command, self.fixture)

    def test_denies_a_push_to_main_when_the_command_makes_the_scope_unknown(self):
        push = "git push origin main"
        for command in [
            f"cd $TMPDIR/nonexistent; {push}",
            f"ln -s {self.real} $TMPDIR/l; cd $TMPDIR/l && {push}",
            f"export TMPDIR={self.real}; cd $TMPDIR && {push}",
            f"TMPDIR={self.real}; cd $TMPDIR && {push}",
            "git -C $TMPDIR/nonexistent push origin main",
        ]:
            self.expect_denied("git_guard.py", command, self.real)
            self.expect_denied("git_guard.py", command, self.scratch)

    def test_denies_a_push_to_main_when_the_command_rewrites_the_remote(self):
        url = "https://example.invalid/o/r.git"
        for command in [
            f"git remote set-url origin {url} && git push origin main",
            f"git config remote.origin.url {url}; git push origin main",
            f"git -c remote.origin.pushurl={url} push origin main",
            f"git -c url.{url}.insteadOf={self.fixture_remote} push origin main",
            f"GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.url GIT_CONFIG_VALUE_0={url} "
            "git push origin main",
            f"echo '[remote \"origin\"]' >> {self.fixture}/.git/config; git push origin main",
        ]:
            self.expect_denied("git_guard.py", command, self.fixture)

    def test_allows_signing_and_hook_config_inside_a_fixture(self):
        for command in [
            "git config commit.gpgsign false",
            "git config core.hooksPath /dev/null",
            "git -c commit.gpgsign=false commit --allow-empty -m 'chore: init'",
            "git -c core.hooksPath=/dev/null commit --allow-empty -m 'chore: init'",
        ]:
            self.expect_allowed("git_guard.py", command, self.fixture)

    def test_denies_signing_and_hook_config_in_a_wider_scope_or_a_real_repository(self):
        for command in [
            "git config --global commit.gpgsign false",
            "git config --system core.hooksPath /dev/null",
            "git config --file ~/.gitconfig commit.gpgsign false",
        ]:
            self.expect_denied("git_guard.py", command, self.fixture)
        for command in [
            "git config commit.gpgsign false",
            "git -c commit.gpgsign=false commit --allow-empty -m 'chore: init'",
        ]:
            self.expect_denied("git_guard.py", command, self.real)

    def test_denies_a_push_to_main_when_a_subshell_rewrites_the_remote(self):
        url = "https://example.invalid/o/r.git"
        for command in [
            f"(git remote set-url origin {url}) && git push origin main",
            f"bash -c 'git remote set-url origin {url}'; git push origin main",
        ]:
            self.expect_denied("git_guard.py", command, self.fixture)

    def test_allows_a_push_to_main_of_a_fixture_next_to_other_git_commands(self):
        for command in [
            "git status && git push origin main",
            "git log --oneline | head -3; git push origin main",
        ]:
            self.expect_allowed("git_guard.py", command, self.fixture)

    def test_the_push_deny_names_its_scope(self):
        output = self.run_scoped("git_guard.py", "git push origin main", self.real)
        self.assertIn("inside a repository", reason(output).lower())


if __name__ == "__main__":
    unittest.main()
