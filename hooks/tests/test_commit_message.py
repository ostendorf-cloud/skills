# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for commit_message.py."""

import os
import tempfile
import unittest

from helper import bash_payload, decision, reason, run_hook


class CommitMessageTest(unittest.TestCase):
    def test_allows_conventional_subjects(self):
        for command in [
            "git commit -m 'feat: add valkey module'",
            "git commit -m 'fix(tofu): pin provider version'",
            "git commit -m 'feat(api)!: drop v1 endpoints'",
            "git commit --amend --no-edit",
            "git commit",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_denies_non_conventional_subjects(self):
        for command in [
            "git commit -m 'added some stuff'",
            "git commit -m 'Feat: add thing'",
            "git commit -m 'wip: experiment'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_subject_over_the_length_limit(self):
        subject = "feat: " + "a" * 70
        command = f"git commit -m '{subject}'"
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_denies_an_attribution_line_in_the_body(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: add thing\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_generated_with_marker(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\nfeat: add thing\n\nGenerated with Claude Code\nEOF\n)\""
        )
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_denies_a_claude_dot_com_link(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\nfeat: add thing\n\n"
            'See https://claude.com/claude-code for details.\nEOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_generated_with_mid_sentence(self):
        command = "git commit -m 'fix: drop the generated with marker from the template'"
        self.assertIsNone(decision(run_hook("commit_message.py", bash_payload(command))))

    def test_allows_a_documentation_link(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\ndocs: link the hook protocol reference\n\n"
            "See https://docs.claude.com/en/docs/claude-code/hooks for the payload shape."
            '\nEOF\n)"'
        )
        self.assertIsNone(decision(run_hook("commit_message.py", bash_payload(command))))

    def test_reads_the_message_from_a_file_flag(self):
        directory = tempfile.mkdtemp(prefix="commit-message-")
        path = os.path.join(directory, "message.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not a conventional subject\n")
        output = run_hook("commit_message.py", bash_payload(f"git commit -F {path}", directory))
        self.assertEqual(decision(output), "deny")

    def test_allows_amend_without_a_new_message(self):
        self.assertIsNone(
            decision(run_hook("commit_message.py", bash_payload("git commit --amend")))
        )

    def test_denies_attribution_in_the_second_dash_m_flag(self):
        command = (
            "git commit -m 'feat: add thing' -m 'Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_two_clean_dash_m_flags(self):
        command = "git commit -m 'feat: add thing' -m 'longer body explaining why'"
        self.assertIsNone(decision(run_hook("commit_message.py", bash_payload(command))), command)

    def test_denies_commit_through_dash_c_path(self):
        directory = tempfile.mkdtemp(prefix="commit-message-")
        command = f"git -C {directory} commit -m 'added some stuff'"
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")


if __name__ == "__main__":
    unittest.main()
