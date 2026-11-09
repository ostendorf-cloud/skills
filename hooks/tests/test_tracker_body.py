# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for tracker_body.py."""

import os
import sys
import tempfile
import unittest

from helper import HOOKS_DIR, bash_payload, decision, reason, run_hook

sys.path.insert(0, HOOKS_DIR)
import _common  # noqa: E402


class TrackerBodyTest(unittest.TestCase):
    def test_denies_a_trailer_in_a_gh_pr_create_body(self):
        command = (
            "gh pr create --title 'feat: add valkey module' --body "
            "'Adds the valkey module to the catalogue.\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_generated_with_line_in_a_gh_pr_create_body(self):
        command = (
            "gh pr create --title 'fix: pin provider version' "
            "--body 'Pins the provider to the last known good release.\n\n"
            "Generated with Claude Code'"
        )
        self.assertEqual(decision(run_hook("tracker_body.py", bash_payload(command))), "deny")

    def test_allows_generated_with_mid_sentence(self):
        command = "gh pr comment 1 --body 'the CRD is generated with controller-gen'"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_body_file_with_a_claude_dot_com_link(self):
        directory = tempfile.mkdtemp(prefix="tracker-body-")
        path = os.path.join(directory, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "Rotates the staging credentials ahead of the audit.\n\n"
                "See https://claude.com/claude-code for the tool that drafted this.\n"
            )
        command = f"gh issue edit 12 --body-file {path}"
        output = run_hook("tracker_body.py", bash_payload(command, directory))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_a_documentation_link(self):
        command = (
            "gh issue comment 12 --body "
            "'See https://docs.claude.com/en/docs/claude-code/hooks for the payload shape.'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_allows_an_ordinary_gh_issue_comment(self):
        command = "gh issue comment 12 --body 'Reproduced on staging, looking into the cause.'"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_allows_a_gh_pr_comment_that_mentions_claude_in_a_code_span(self):
        command = (
            "gh pr comment 42 --body "
            "'Renamed the variable from `claude_client` to `llm_client` for clarity.'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_allows_a_body_file_without_forbidden_patterns(self):
        directory = tempfile.mkdtemp(prefix="tracker-body-")
        path = os.path.join(directory, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Adds retry logic around the flaky upstream call.\n")
        command = f"gh pr edit 7 --body-file {path}"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command, directory))))

    def test_ignores_unrelated_gh_commands(self):
        for command in [
            "gh pr list",
            "gh issue view 12",
            "gh pr status",
        ]:
            self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))), command)

    def test_ignores_a_body_file_argument_of_dash_without_a_pipe(self):
        command = "gh pr create --title 'feat: add thing' --body-file -"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_an_attached_shorthand_body_flag(self):
        command = "gh pr comment 1 -b'Co-Authored-By: Claude <noreply@anthropic.com>'"
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_an_attached_shorthand_body_flag_with_equals(self):
        command = "gh pr comment 1 -b=Co-Authored-By:x"
        self.assertEqual(decision(run_hook("tracker_body.py", bash_payload(command))), "deny")

    def test_denies_an_attached_shorthand_body_file_flag(self):
        directory = tempfile.mkdtemp(prefix="tracker-body-")
        path = os.path.join(directory, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Generated with Claude Code\n")
        command = f"gh pr edit 7 -F{path}"
        self.assertEqual(
            decision(run_hook("tracker_body.py", bash_payload(command, directory))), "deny"
        )

    def test_allows_an_attached_shorthand_body_flag_without_forbidden_patterns(self):
        command = "gh pr comment 1 -b'Looks good, merging now.'"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_piped_into_a_body_file_from_stdin(self):
        command = "printf 'Co-Authored-By: Someone <a@b.c>' | gh pr comment 1 --body-file -"
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_a_body_file_from_stdin_without_forbidden_patterns(self):
        command = "printf 'Reproduced on staging.' | gh pr comment 1 --body-file -"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_allows_a_body_file_from_dev_stdin_without_a_pipe(self):
        command = "gh pr comment 1 --body-file /dev/stdin"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_in_a_gh_api_body_field(self):
        command = (
            "gh api repos/ostendorf-cloud/skills/issues/1/comments "
            "-f body='Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_allows_a_gh_api_body_field_without_forbidden_patterns(self):
        command = (
            "gh api repos/ostendorf-cloud/skills/issues/1/comments -f body='looks good, merging'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_through_an_absolute_gh_path(self):
        command = (
            "/opt/homebrew/bin/gh pr comment 1 --body "
            "'Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_through_a_quoted_gh_name(self):
        for command in [
            "\"gh\" pr comment 1 --body 'Co-Authored-By: Claude <noreply@anthropic.com>'",
            '"/opt/homebrew/bin/gh" pr comment 1 --body '
            "'Co-Authored-By: Claude <noreply@anthropic.com>'",
        ]:
            output = run_hook("tracker_body.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("attribution", reason(output))

    def test_allows_a_quoted_command_whose_name_only_ends_in_gh(self):
        command = "\"/usr/local/bin/mygh\" pr comment 1 --body 'Co-Authored-By: Claude'"
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_resolves_command_name_to_the_basename(self):
        self.assertEqual(_common.command_name("/opt/homebrew/bin/gh pr comment 1"), "gh")
        self.assertEqual(_common.command_name("gh pr comment 1"), "gh")
        self.assertEqual(_common.command_name('"/opt/homebrew/bin/gh" pr comment 1'), "gh")
        self.assertEqual(_common.command_name('"gh" pr comment 1'), "gh")
        self.assertEqual(_common.command_name(""), "")

    def test_allows_a_quoted_trailer_in_a_code_span(self):
        command = (
            "gh pr comment 45 --body "
            "'Quoting the pattern the hook denies: "
            "`Co-Authored-By: Claude <noreply@anthropic.com>`.'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_allows_a_quoted_generated_with_marker_in_a_fence(self):
        command = (
            "gh issue comment 45 --body "
            "'The hook should deny this line:\n\n```\nGenerated with Claude Code\n```'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_that_follows_a_fence(self):
        command = (
            "gh pr create --title 'fix: quote the attribution pattern in the review body' "
            "--body '```\nexample output\n```\n\nCo-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_inside_an_unterminated_fence(self):
        command = "gh pr comment 45 --body '```\nCo-Authored-By: Claude <noreply@anthropic.com>'"
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_sitting_between_a_stray_backtick_and_a_real_span(self):
        command = (
            "gh pr comment 45 --body "
            "'Won`t rerun until the Co-Authored-By: Claude <noreply@anthropic.com> issue in "
            "``extract_message`` is fixed.'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_quoted_in_a_span_that_crosses_a_line_break(self):
        command = (
            "gh issue comment 45 --body "
            "'Quoting the pattern the hook denies: `Co-Authored-By:\n"
            "Claude <noreply@anthropic.com>`.'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_between_two_stray_backticks_on_separate_lines(self):
        command = (
            "gh pr comment 45 --body "
            "'Won`t forget: the next line has the trailer.\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "This isn`t done yet.'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))

    def test_denies_a_trailer_with_a_flag_before_the_noun(self):
        for command in [
            "gh --hostname github.example.com pr create --title 'feat: add the valkey module' "
            "--body 'Co-Authored-By: Claude <noreply@anthropic.com>'",
            "gh --hostname=github.example.com issue comment 45 "
            "--body 'Co-Authored-By: Claude <noreply@anthropic.com>'",
            "gh --method POST api repos/owner/repo/issues/1/comments "
            "-f body='Co-Authored-By: Claude <noreply@anthropic.com>'",
        ]:
            output = run_hook("tracker_body.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("attribution", reason(output))

    def test_allows_a_clean_body_with_a_flag_before_the_noun(self):
        for command in [
            "gh --hostname github.example.com pr create --title 'feat: add the valkey module' "
            "--body 'Adds the valkey module to the catalogue.'",
            "gh --method POST api repos/owner/repo/issues/1/comments "
            "-f body='Rotated the staging credentials.'",
        ]:
            self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))), command)

    def test_denies_a_gh_part_whose_quoting_does_not_parse(self):
        for command in [
            'gh pr create --title x --body "Co-authored-by: Claude <noreply@anthropic.com>',
            "gh issue comment 45 --body 'Co-Authored-By: Claude <noreply@anthropic.com>",
            "gh --method POST api repos/owner/repo/issues/1/comments -f body='unclosed",
        ]:
            output = run_hook("tracker_body.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("quoting", reason(output), command)

    def test_allows_a_non_gh_part_whose_quoting_does_not_parse(self):
        command = 'jq --arg name "unclosed'
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_in_a_pr_body_behind_a_wrapper_prefix(self):
        for prefix in [
            "",
            "sudo ",
            "sudo -u ci ",
            "doas ",
            "env GH_HOST=github.example.com ",
            "mise exec -- ",
            "mise exec gh@2 -- ",
            "nice -n 10 ",
            "nohup ",
            "time ",
            "sudo /opt/homebrew/bin/",
        ]:
            command = (
                f"{prefix}gh pr create --title 'feat: add the valkey module' "
                "--body 'Co-Authored-By: Claude <noreply@anthropic.com>'"
            )
            output = run_hook("tracker_body.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("attribution", reason(output), command)

    def test_denies_a_generated_with_marker_in_an_issue_comment_behind_a_wrapper(self):
        for command in [
            "gh issue comment 45 --body 'Fixed.\n\nGenerated with Claude Code'",
            "sudo gh issue comment 45 --body 'Fixed.\n\nGenerated with Claude Code'",
            "mise exec -- gh issue comment 45 --body 'Fixed.\n\nGenerated with Claude Code'",
        ]:
            self.assertEqual(
                decision(run_hook("tracker_body.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_trailer_in_an_api_body_field_behind_a_wrapper_prefix(self):
        for command in [
            "gh api -X POST repos/owner/repo/issues/1/comments "
            "-f body='Co-authored-by: Claude <noreply@anthropic.com>'",
            "sudo gh api -X POST repos/owner/repo/issues/1/comments "
            "-f body='Co-authored-by: Claude <noreply@anthropic.com>'",
            "nice -n 10 gh api -X POST repos/owner/repo/issues/1/comments "
            "-f body='Co-authored-by: Claude <noreply@anthropic.com>'",
        ]:
            self.assertEqual(
                decision(run_hook("tracker_body.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_body_file_with_a_forbidden_link_behind_a_wrapper_prefix(self):
        directory = tempfile.mkdtemp(prefix="tracker-body-")
        path = os.path.join(directory, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("See https://claude.ai/share/abc for the session.\n")
        for command in [
            f"gh pr comment 1 --body-file {path}",
            f"sudo gh pr comment 1 --body-file {path}",
            f"mise exec -- gh pr comment 1 --body-file {path}",
        ]:
            self.assertEqual(
                decision(run_hook("tracker_body.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_multi_line_body_behind_a_wrapper_prefix(self):
        command = (
            "sudo gh pr create --title 'fix: pin the provider' --body "
            "'Pins the provider to the last known good release.\n\nGenerated with Claude Code'"
        )
        self.assertEqual(decision(run_hook("tracker_body.py", bash_payload(command))), "deny")

    def test_denies_an_unparseable_gh_part_behind_a_wrapper_prefix(self):
        for command in [
            'gh pr create --title x --body "Co-authored-by: Claude',
            'sudo gh pr create --title x --body "Co-authored-by: Claude',
            'mise exec -- gh pr create --title x --body "Co-authored-by: Claude',
        ]:
            output = run_hook("tracker_body.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("quoting", reason(output), command)

    def test_allows_a_clean_body_behind_a_wrapper_prefix(self):
        for command in [
            "gh pr comment 1 --body 'Rebased onto main and rerun the checks.'",
            "sudo gh pr comment 1 --body 'Rebased onto main and rerun the checks.'",
            "sudo -u ci gh issue comment 45 --body 'Picked this up.'",
            "doas gh pr create --title 'feat: add the valkey module' --body 'Adds the module.'",
            "env GH_HOST=github.example.com gh issue edit 44 --body 'Refined the scope.'",
            "mise exec -- gh pr comment 1 --body 'See docs.claude.com for the reference.'",
            "nice -n 10 gh api -X POST repos/owner/repo/issues/1/comments -f body='Done.'",
            "nohup gh pr list",
            "time gh issue view 44 --comments",
        ]:
            self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))), command)

    def test_allows_a_forbidden_pattern_behind_an_unlisted_wrapper(self):
        command = (
            "timeout 5 gh pr comment 1 --body 'Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        self.assertIsNone(decision(run_hook("tracker_body.py", bash_payload(command))))

    def test_denies_a_trailer_when_gh_is_called_by_its_absolute_path(self):
        command = (
            "/opt/homebrew/bin/gh pr create --title 'feat: add the valkey module' "
            "--body 'Co-Authored-By: Claude <noreply@anthropic.com>'"
        )
        output = run_hook("tracker_body.py", bash_payload(command))
        self.assertEqual(decision(output), "deny")
        self.assertIn("attribution", reason(output))


if __name__ == "__main__":
    unittest.main()
