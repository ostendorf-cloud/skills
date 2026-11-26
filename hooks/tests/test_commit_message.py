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

    def test_denies_a_non_conventional_subject_when_git_is_called_by_absolute_path(self):
        for command in [
            "git commit -m 'added some stuff'",
            "/usr/bin/git commit -m 'added some stuff'",
            "/opt/homebrew/bin/git commit -m 'added some stuff'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_attribution_line_when_git_is_called_by_absolute_path(self):
        command = (
            "/usr/bin/git commit -m \"$(cat <<'EOF'\n"
            "feat: add thing\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_commit_by_absolute_path_through_dash_c_path(self):
        directory = tempfile.mkdtemp(prefix="commit-message-")
        command = f"/usr/bin/git -C {directory} commit -m 'added some stuff'"
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_allows_a_conventional_subject_when_git_is_called_by_absolute_path(self):
        for command in [
            "/usr/bin/git commit -m 'feat: add valkey module'",
            "/usr/bin/git commit --amend --no-edit",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_denies_a_non_conventional_subject_behind_a_wrapper_prefix(self):
        for command in [
            "time git commit -m 'added some stuff'",
            "command git commit -m 'added some stuff'",
            "env git commit -m 'added some stuff'",
            "exec /usr/bin/git commit -m 'added some stuff'",
            "nohup git commit -m 'added some stuff'",
            "nice git commit -m 'added some stuff'",
            "mise exec -- git commit -m 'added some stuff'",
            "mise exec git@latest -- git commit -m 'added some stuff'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_attribution_line_behind_a_wrapper_prefix(self):
        command = (
            "time git commit -m \"$(cat <<'EOF'\n"
            "feat: add thing\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_a_conventional_subject_behind_a_wrapper_prefix(self):
        for command in [
            "time git commit -m 'feat: add valkey module'",
            "mise exec -- git commit --amend --no-edit",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_denies_a_non_conventional_subject_when_git_is_quoted(self):
        for command in [
            "\"git\" commit -m 'added some stuff'",
            "'git' commit -m 'added some stuff'",
            "\"/usr/bin/git\" commit -m 'added some stuff'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_non_conventional_subject_behind_a_privilege_escalation_prefix(self):
        for command in [
            "sudo git commit -m 'added some stuff'",
            "sudo -u ci git commit -m 'added some stuff'",
            "doas git commit -m 'added some stuff'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_non_conventional_subject_behind_a_flagged_wrapper(self):
        for command in [
            "nice -n 10 git commit -m 'added some stuff'",
            "nice --adjustment=10 git commit -m 'added some stuff'",
            "nohup -- git commit -m 'added some stuff'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_allows_a_conventional_subject_behind_a_flagged_wrapper(self):
        for command in [
            "nice -n 10 git commit -m 'feat: add valkey module'",
            "sudo git commit -m 'feat: add valkey module'",
            "\"git\" commit -m 'feat: add valkey module'",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_allows_another_command_whose_name_ends_in_git(self):
        for command in [
            "legit commit -m 'added some stuff'",
            "/usr/local/bin/mygit commit -m 'added some stuff'",
            "gitless commit -m 'added some stuff'",
            "git-town sync",
            "nice -n 10 legit commit -m 'added some stuff'",
            "sudo mygit commit -m 'added some stuff'",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_denies_commit_through_dash_c_path(self):
        directory = tempfile.mkdtemp(prefix="commit-message-")
        command = f"git -C {directory} commit -m 'added some stuff'"
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_allows_a_quoted_trailer_in_a_code_span(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: quote the attribution pattern in the review reply\n\n"
            "Mentions the pattern the hook denies, `Co-Authored-By: Claude "
            "<noreply@anthropic.com>`, as an example.\n"
            'EOF\n)"'
        )
        self.assertIsNone(decision(run_hook("commit_message.py", bash_payload(command))))

    def test_allows_a_quoted_generated_with_marker_in_a_fence(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "docs: document the generated-with marker the hook checks for\n\n"
            "```\nGenerated with Claude Code\n```\n"
            'EOF\n)"'
        )
        self.assertIsNone(decision(run_hook("commit_message.py", bash_payload(command))))

    def test_denies_a_trailer_that_follows_a_fence(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: close the fence before the attribution trailer\n\n"
            "```\nexample output\n```\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_inside_an_unterminated_fence(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: close the fence in the review reply template\n\n"
            "```\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_sitting_between_a_stray_backtick_and_a_real_span(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: handle the stray backtick before a real span\n\n"
            "Won`t rerun until the Co-Authored-By: Claude <noreply@anthropic.com> issue in "
            "``extract_message`` is fixed.\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_quoted_in_a_span_that_crosses_a_line_break(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "docs: quote the multi-line trailer pattern in the template\n\n"
            "Quoting the pattern the hook denies: `Co-Authored-By:\n"
            "Claude <noreply@anthropic.com>`.\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_between_two_stray_backticks_on_separate_lines(self):
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: stop two stray backticks swallowing the trailer between them\n\n"
            "Won`t forget: the next line has the trailer.\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "This isn`t done yet.\n"
            'EOF\n)"'
        )
        output = run_hook("commit_message.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_a_valid_commit_after_another_command_with_a_message_flag(self):
        for command in [
            "git tag -m 'release notes' && git commit -m 'feat: add thing'",
            "git stash push -m wip; git commit -m 'feat: add thing' -m 'why it helps'",
            "echo -m 'not a commit' | cat && git commit -m 'fix(tofu): pin provider version'",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_ignores_attribution_text_outside_the_commit_segment(self):
        for command in [
            "git commit -m 'feat: add thing' && echo -m 'Co-Authored-By: Claude'",
            "echo -m 'Co-Authored-By: Claude' && git commit -m 'feat: add thing'",
            "git commit -m 'feat: add thing' && gh pr comment 1 --body 'see claude.ai'",
        ]:
            self.assertIsNone(
                decision(run_hook("commit_message.py", bash_payload(command))), command
            )

    def test_judges_the_commit_segment_of_a_chained_command(self):
        for command in [
            "git add -A && git commit -m 'added some stuff'",
            "git tag -m 'v1' && git commit -m 'added some stuff' -m 'body'",
            "git add -A && git commit -m 'feat: add thing' -m 'Co-Authored-By: Claude <a@b.c>'",
        ]:
            self.assertEqual(
                decision(run_hook("commit_message.py", bash_payload(command))), "deny", command
            )

    def test_takes_the_first_dash_m_as_the_subject_of_several(self):
        command = "git commit -m 'added some stuff' -m 'feat: looks fine as a body'"
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_denies_attribution_in_a_third_dash_m_flag(self):
        command = (
            "git commit -m 'feat: add thing' -m 'body' "
            "-m 'Generated with Claude Code'"
        )
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")

    def test_reads_a_heredoc_message_from_the_commit_segment(self):
        command = (
            "git add -A && git commit -F - <<'EOF'\n"
            "added some stuff\n"
            "EOF"
        )
        self.assertEqual(decision(run_hook("commit_message.py", bash_payload(command))), "deny")


if __name__ == "__main__":
    unittest.main()
