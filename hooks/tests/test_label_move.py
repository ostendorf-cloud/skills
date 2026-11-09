# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for label_move.py."""

import unittest

from helper import bash_payload, context, decision, run_hook


class LabelMoveTest(unittest.TestCase):
    def test_adds_context_on_issue_add_without_remove(self):
        command = 'gh issue edit 44 --add-label "ai: working"'
        message = context(run_hook("label_move.py", bash_payload(command)))
        self.assertIn("ai:", message)
        self.assertIn("remove", message.lower())

    def test_adds_context_on_pr_add_without_remove(self):
        command = 'gh pr edit 12 --add-label "ai: review requested"'
        message = context(run_hook("label_move.py", bash_payload(command)))
        self.assertNotEqual(message, "")

    def test_adds_context_with_equals_syntax(self):
        command = 'gh issue edit 44 --add-label="ai: done"'
        message = context(run_hook("label_move.py", bash_payload(command)))
        self.assertNotEqual(message, "")

    def test_no_context_when_remove_label_present(self):
        command = 'gh issue edit 44 --add-label "ai: working" --remove-label "ai: ready"'
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_adds_context_when_remove_label_targets_something_else(self):
        command = 'gh issue edit 44 --add-label "ai: working" --remove-label "needs triage"'
        message = context(run_hook("label_move.py", bash_payload(command)))
        self.assertNotEqual(message, "")

    def test_no_context_when_one_of_several_removes_is_an_ai_label(self):
        command = (
            'gh issue edit 44 --add-label "ai: working" --remove-label "needs triage" '
            '--remove-label "ai: ready"'
        )
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_adds_context_for_an_ai_label_anywhere_in_an_add_comma_list(self):
        command = 'gh issue edit 44 --add-label "priority: high,ai: done"'
        message = context(run_hook("label_move.py", bash_payload(command)))
        self.assertNotEqual(message, "")

    def test_no_context_for_an_ai_label_anywhere_in_a_remove_comma_list(self):
        command = (
            'gh issue edit 44 --add-label "ai: working" --remove-label "needs triage,ai: ready"'
        )
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_no_context_for_non_ai_label(self):
        command = "gh issue edit 44 --add-label bug"
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_no_context_for_gh_issue_view(self):
        command = "gh issue view 44 --comments"
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_no_context_for_gh_label_create(self):
        command = 'gh label create "ai: working" --color 0969da'
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_no_context_without_add_label(self):
        command = "gh issue edit 44 --body-file notes.md"
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_never_denies(self):
        command = 'gh issue edit 44 --add-label "ai: working"'
        self.assertIsNone(decision(run_hook("label_move.py", bash_payload(command))))

    def test_adds_context_with_a_flag_before_the_noun(self):
        for command in [
            'gh --hostname github.example.com issue edit 44 --add-label "ai: done"',
            'gh --hostname=github.example.com pr edit 12 --add-label "ai: review requested"',
            'gh issue --repo owner/repo edit 44 --add-label "ai: working"',
        ]:
            message = context(run_hook("label_move.py", bash_payload(command)))
            self.assertNotEqual(message, "", command)

    def test_no_context_with_a_flag_before_the_noun_when_an_ai_label_is_removed(self):
        command = (
            "gh --hostname github.example.com issue edit 44 "
            '--add-label "ai: done" --remove-label "ai: working"'
        )
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_no_context_with_a_flag_before_the_noun_on_a_read(self):
        command = "gh --hostname github.example.com issue view 44 --comments"
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")

    def test_unparseable_command_stays_quiet(self):
        command = 'gh issue edit 44 --add-label "ai: working'
        self.assertEqual(context(run_hook("label_move.py", bash_payload(command))), "")


if __name__ == "__main__":
    unittest.main()
