# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for main_session_rules.py."""

import os
import shutil
import tempfile
import unittest

from helper import HOOKS_DIR, context, run_hook

RULES = "# Main session\n\nAsk before you guess.\n"
MAX_RULES_CHARS = 9000


def installed_copy(rules: str = RULES) -> str:
    """A hook directory shaped like the installed one: the script, _common and the rules."""
    directory = os.path.join(tempfile.mkdtemp(prefix="main-session-"), "hooks")
    os.makedirs(directory)
    for name in ("main_session_rules.py", "_common.py"):
        shutil.copy(os.path.join(HOOKS_DIR, name), directory)
    if rules is not None:
        with open(os.path.join(directory, "main-session.md"), "w", encoding="utf-8") as handle:
            handle.write(rules)
    return directory


def run_in(directory: str, payload: dict) -> dict:
    return run_hook(os.path.join(directory, "main_session_rules.py"), payload)


def start(source: str = "startup", **extra) -> dict:
    return {"hook_event_name": "SessionStart", "session_id": "s", "source": source, **extra}


class MainSessionRulesTest(unittest.TestCase):
    def test_emits_the_rules_on_startup(self):
        directory = installed_copy()
        self.assertEqual(context(run_in(directory, start("startup"))), RULES.strip())

    def test_emits_the_rules_for_every_session_source(self):
        directory = installed_copy()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(context(run_in(directory, start(source))), RULES.strip())

    def test_emits_the_rules_when_agent_id_is_empty(self):
        directory = installed_copy()
        self.assertEqual(context(run_in(directory, start(agent_id=""))), RULES.strip())

    def test_emits_nothing_for_a_subagent(self):
        directory = installed_copy()
        self.assertEqual(context(run_in(directory, start(agent_id="agent-7"))), "")

    def test_emits_nothing_when_the_rules_file_is_missing(self):
        directory = installed_copy(rules=None)
        self.assertEqual(run_in(directory, start()), {})

    def test_emits_nothing_when_the_rules_file_is_empty(self):
        directory = installed_copy(rules="\n")
        self.assertEqual(run_in(directory, start()), {})

    def test_ignores_events_other_than_session_start(self):
        directory = installed_copy()
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s"}
        self.assertEqual(run_in(directory, payload), {})

    def test_shipped_rules_stay_below_the_context_cut(self):
        path = os.path.join(os.path.dirname(HOOKS_DIR), "rules", "main-session.md")
        with open(path, encoding="utf-8") as handle:
            self.assertLess(len(handle.read()), MAX_RULES_CHARS)


if __name__ == "__main__":
    unittest.main()
