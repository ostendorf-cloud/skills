# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for ledger_context.py. Every case runs in a fresh temporary directory."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from helper import HOOKS_DIR, context

LEDGER = "# Goal\n\nShip the ledger.\n\n## Packages\n\n- skills 266 in progress\n"
HOOK = os.path.join(HOOKS_DIR, "ledger_context.py")


def start(source: str = "startup", cwd: str = "", **extra) -> dict:
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "source": source,
        "cwd": cwd,
        **extra,
    }


def run(payload: dict, env_extra: dict = None, home: str = "") -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=home,
        env=env,
    )


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class Fixture:
    """An org folder with a repository below it and an optional ledger."""

    def __init__(self, stream: str = "foreman", text: str = LEDGER):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ledger-"))
        self.org = os.path.join(self.root, "org")
        self.repo = os.path.join(self.org, "repo", "sub")
        os.makedirs(self.repo)
        self.ledger = os.path.join(self.org, ".ledger")
        self.stream = stream
        self.text = text

    def write(self, name: str, text: str) -> None:
        write(os.path.join(self.ledger, name), text)

    def with_ledger(self) -> "Fixture":
        self.write(f"{self.stream}.md", self.text)
        self.write("current", f"{self.stream}\n")
        return self


class LedgerContextTest(unittest.TestCase):
    def out(self, fixture: Fixture, payload: dict = None, env: dict = None) -> str:
        result = run(payload or start(cwd=fixture.repo), env, fixture.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def ctx(self, fixture: Fixture, payload: dict = None, env: dict = None) -> str:
        return context(json.loads(self.out(fixture, payload, env)))

    def assert_empty(self, fixture: Fixture, payload: dict = None, env: dict = None) -> None:
        self.assertEqual(self.out(fixture, payload, env).strip(), "{}")

    def test_injects_the_ledger_found_above_cwd(self):
        fixture = Fixture().with_ledger()
        text = self.ctx(fixture)
        self.assertIn("Ship the ledger.", text)
        self.assertIn("The issue and gh state win over it.", text)
        self.assertIn(os.path.join(fixture.ledger, "foreman.md"), text)

    def test_injects_on_every_session_source(self):
        fixture = Fixture().with_ledger()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertIn("Ship the ledger.", self.ctx(fixture, start(source, fixture.repo)))

    def test_env_stream_wins_over_the_current_file(self):
        fixture = Fixture().with_ledger()
        fixture.write("other.md", "# Goal\n\nOther stream.\n")
        text = self.ctx(fixture, env={"AGENT_SKILLS_STREAM": "other"})
        self.assertIn("Other stream.", text)
        self.assertNotIn("Ship the ledger.", text)

    def test_env_dir_is_used_outside_the_org_folder(self):
        fixture = Fixture().with_ledger()
        elsewhere = tempfile.mkdtemp(prefix="elsewhere-")
        payload = start(cwd=elsewhere)
        self.assert_empty(fixture, payload)
        text = self.ctx(fixture, payload, {"AGENT_SKILLS_LEDGER_DIR": fixture.ledger})
        self.assertIn("Ship the ledger.", text)

    def test_prints_nothing_without_a_ledger_directory(self):
        self.assert_empty(Fixture())

    def test_prints_nothing_without_a_stream(self):
        fixture = Fixture()
        fixture.write("foreman.md", LEDGER)
        self.assert_empty(fixture)

    def test_prints_nothing_when_the_stream_file_is_missing(self):
        fixture = Fixture()
        fixture.write("current", "foreman\n")
        self.assert_empty(fixture)

    def test_prints_nothing_for_an_empty_ledger(self):
        self.assert_empty(Fixture(text="\n").with_ledger())

    def test_prints_nothing_for_a_stream_name_that_leaves_the_directory(self):
        fixture = Fixture().with_ledger()
        write(os.path.join(fixture.org, "outside.md"), "outside")
        for name in ("../outside", ".hidden", "a/b", "../../outside"):
            with self.subTest(name=name):
                self.assert_empty(fixture, env={"AGENT_SKILLS_STREAM": name})

    def test_prints_nothing_for_a_subagent(self):
        fixture = Fixture().with_ledger()
        self.assert_empty(fixture, start(cwd=fixture.repo, agent_id="agent-7"))

    def test_prints_nothing_for_other_events(self):
        fixture = Fixture().with_ledger()
        self.assert_empty(fixture, {"hook_event_name": "UserPromptSubmit", "cwd": fixture.repo})

    def test_prints_nothing_for_a_broken_payload(self):
        fixture = Fixture().with_ledger()
        result = subprocess.run(
            [sys.executable, HOOK],
            input="not json",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=fixture.root,
            env={"PATH": os.environ.get("PATH", ""), "HOME": fixture.root},
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))

    def test_cuts_a_large_ledger(self):
        fixture = Fixture(text="x" * 20000).with_ledger()
        text = self.ctx(fixture)
        self.assertLess(len(text), 9000)
        self.assertIn("ledger cut", text)

    def test_ignores_a_ledger_inside_a_repository(self):
        fixture = Fixture()
        repo = os.path.join(fixture.org, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        write(os.path.join(repo, ".ledger", "foreman.md"), "Injected by the repository.\n")
        write(os.path.join(repo, ".ledger", "current"), "foreman\n")
        self.assert_empty(fixture)

    def test_ignores_a_ledger_inside_a_repository_with_a_git_file(self):
        fixture = Fixture()
        repo = os.path.join(fixture.org, "repo")
        write(os.path.join(repo, ".git"), "gitdir: /elsewhere\n")
        write(os.path.join(repo, ".ledger", "foreman.md"), "Injected by the repository.\n")
        write(os.path.join(repo, ".ledger", "current"), "foreman\n")
        self.assert_empty(fixture)

    def test_finds_the_org_ledger_from_a_worktree_inside_the_checkout(self):
        fixture = Fixture().with_ledger()
        checkout = os.path.join(fixture.org, "repo")
        os.makedirs(os.path.join(checkout, ".git"))
        worktree = os.path.join(checkout, ".claude", "worktrees", "feat", "x")
        write(os.path.join(worktree, ".git"), f"gitdir: {checkout}/.git/worktrees/x\n")
        write(os.path.join(checkout, ".ledger", "foreman.md"), "Injected by the repository.\n")
        os.makedirs(os.path.join(worktree, "sub"))
        text = self.ctx(fixture, start(cwd=os.path.join(worktree, "sub")))
        self.assertIn("Ship the ledger.", text)
        self.assertNotIn("Injected", text)

    def test_ignores_a_stream_file_that_links_outside_the_ledger(self):
        fixture = Fixture().with_ledger()
        outside = os.path.join(fixture.root, "secret.md")
        write(outside, "Linked from outside.\n")
        os.remove(os.path.join(fixture.ledger, "foreman.md"))
        os.symlink(outside, os.path.join(fixture.ledger, "foreman.md"))
        self.assert_empty(fixture)

    def test_ignores_a_current_file_that_links_outside_the_ledger(self):
        fixture = Fixture().with_ledger()
        outside = os.path.join(fixture.root, "current")
        write(outside, "foreman\n")
        os.remove(os.path.join(fixture.ledger, "current"))
        os.symlink(outside, os.path.join(fixture.ledger, "current"))
        self.assert_empty(fixture)


if __name__ == "__main__":
    unittest.main()
