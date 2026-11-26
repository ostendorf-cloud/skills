# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for ledger_context.py. Every case runs in a fresh temporary directory."""

import os
import subprocess
import sys
import tempfile
import unittest

from helper import HOOKS_DIR, context

LEDGER = "# Goal\n\nShip the ledger.\n\n## Packages\n\n- skills 266 in progress\n"


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
    import json

    return subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, "ledger_context.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=home,
        env=env,
    )


class Fixture:
    """An org folder with a repository below it and an optional ledger."""

    def __init__(self, test: unittest.TestCase, stream: str = "foreman", text: str = LEDGER):
        self.root = tempfile.mkdtemp(prefix="ledger-")
        self.org = os.path.join(self.root, "org")
        self.repo = os.path.join(self.org, "repo", "sub")
        os.makedirs(self.repo)
        self.ledger = os.path.join(self.org, ".ledger")
        self.stream = stream
        self.text = text

    def write(self, name: str, text: str) -> None:
        os.makedirs(self.ledger, exist_ok=True)
        with open(os.path.join(self.ledger, name), "w", encoding="utf-8") as handle:
            handle.write(text)

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
        import json

        stdout = self.out(fixture, payload, env)
        return context(json.loads(stdout)) if stdout.strip() else ""

    def test_injects_the_ledger_found_above_cwd(self):
        fixture = Fixture(self).with_ledger()
        text = self.ctx(fixture)
        self.assertIn("Ship the ledger.", text)
        self.assertIn("The issue and gh state win over it.", text)
        self.assertIn(os.path.join(fixture.ledger, "foreman.md"), text)

    def test_injects_on_every_session_source(self):
        fixture = Fixture(self).with_ledger()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertIn("Ship the ledger.", self.ctx(fixture, start(source, fixture.repo)))

    def test_env_stream_wins_over_the_current_file(self):
        fixture = Fixture(self).with_ledger()
        fixture.write("other.md", "# Goal\n\nOther stream.\n")
        text = self.ctx(fixture, env={"AGENT_SKILLS_STREAM": "other"})
        self.assertIn("Other stream.", text)
        self.assertNotIn("Ship the ledger.", text)

    def test_env_dir_is_used_outside_the_org_folder(self):
        fixture = Fixture(self).with_ledger()
        elsewhere = tempfile.mkdtemp(prefix="elsewhere-")
        payload = start(cwd=elsewhere)
        self.assertEqual(self.out(fixture, payload), "")
        text = self.ctx(fixture, payload, {"AGENT_SKILLS_LEDGER_DIR": fixture.ledger})
        self.assertIn("Ship the ledger.", text)

    def test_prints_nothing_without_a_ledger_directory(self):
        fixture = Fixture(self)
        self.assertEqual(self.out(fixture), "")

    def test_prints_nothing_without_a_stream(self):
        fixture = Fixture(self)
        fixture.write("foreman.md", LEDGER)
        self.assertEqual(self.out(fixture), "")

    def test_prints_nothing_when_the_stream_file_is_missing(self):
        fixture = Fixture(self)
        fixture.write("current", "foreman\n")
        self.assertEqual(self.out(fixture), "")

    def test_prints_nothing_for_an_empty_ledger(self):
        fixture = Fixture(self, text="\n").with_ledger()
        self.assertEqual(self.out(fixture), "")

    def test_prints_nothing_for_a_stream_name_that_leaves_the_directory(self):
        fixture = Fixture(self).with_ledger()
        secret = os.path.join(fixture.org, "outside.md")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("outside")
        for name in ("../outside", ".hidden", "a/b", "../../outside"):
            with self.subTest(name=name):
                self.assertEqual(self.out(fixture, env={"AGENT_SKILLS_STREAM": name}), "")

    def test_prints_nothing_for_a_subagent(self):
        fixture = Fixture(self).with_ledger()
        self.assertEqual(self.out(fixture, start(cwd=fixture.repo, agent_id="agent-7")), "")

    def test_prints_nothing_for_other_events(self):
        fixture = Fixture(self).with_ledger()
        payload = {"hook_event_name": "UserPromptSubmit", "cwd": fixture.repo}
        self.assertEqual(self.out(fixture, payload), "")

    def test_prints_nothing_for_a_broken_payload(self):
        fixture = Fixture(self).with_ledger()
        result = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, "ledger_context.py")],
            input="not json",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=fixture.root,
            env={"PATH": os.environ.get("PATH", ""), "HOME": fixture.root},
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_cuts_a_large_ledger(self):
        fixture = Fixture(self, text="x" * 20000).with_ledger()
        text = self.ctx(fixture)
        self.assertLess(len(text), 9000)
        self.assertIn("ledger cut", text)


if __name__ == "__main__":
    unittest.main()
