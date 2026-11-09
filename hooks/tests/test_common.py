# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for the _common.py helpers shared across hooks."""

import sys
import unittest

from helper import HOOKS_DIR

sys.path.insert(0, HOOKS_DIR)
import _common  # noqa: E402


class StripCodeTest(unittest.TestCase):
    def test_removes_a_fenced_block_and_an_inline_span(self):
        text = (
            "Reproduced with this call:\n\n"
            "```\n"
            "gh pr comment 1 --body 'Co-Authored-By: Claude <noreply@anthropic.com>'\n"
            "```\n\n"
            "The fix renames `extract_message` to take the path too."
        )
        stripped = _common.strip_code(text)
        self.assertNotIn("Co-Authored-By", stripped)
        self.assertNotIn("extract_message", stripped)
        self.assertIn("Reproduced with this call:", stripped)
        self.assertIn("The fix renames", stripped)

    def test_keeps_an_unterminated_fence_as_plain_text(self):
        text = (
            "Pasted the wrong snippet below:\n\n```\nCo-Authored-By: Claude <noreply@anthropic.com>"
        )
        stripped = _common.strip_code(text)
        self.assertIn("Co-Authored-By", stripped)
        self.assertIn("Pasted the wrong snippet below:", stripped)

    def test_leaves_a_stray_backtick_as_plain_text_before_a_real_span(self):
        text = (
            "Won`t rerun until the Co-Authored-By: Claude <noreply@anthropic.com> "
            "issue in ``extract_message`` is fixed."
        )
        stripped = _common.strip_code(text)
        self.assertIn("Co-Authored-By", stripped)
        self.assertNotIn("extract_message", stripped)

    def test_keeps_a_span_across_a_line_break_as_plain_text(self):
        text = (
            "Quoting the pattern the hook denies: `Co-Authored-By:\n"
            "Claude <noreply@anthropic.com>`."
        )
        stripped = _common.strip_code(text)
        self.assertIn("Co-Authored-By", stripped)
        self.assertIn("Quoting the pattern the hook denies:", stripped)

    def test_keeps_two_stray_backticks_on_separate_lines_as_plain_text(self):
        text = (
            "Won`t forget: the next line has the trailer.\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "This isn`t done yet.\n"
        )
        stripped = _common.strip_code(text)
        self.assertIn("Co-Authored-By", stripped)


class StripWrappersTest(unittest.TestCase):
    def test_strips_a_mise_exec_prefix_with_a_tool_spec(self):
        self.assertEqual(
            _common.strip_wrappers("mise exec python@3.11 -- python3 -c 'print(1)'"),
            "python3 -c 'print(1)'",
        )

    def test_strips_chained_wrapper_prefixes_in_any_order(self):
        self.assertEqual(
            _common.strip_wrappers("time env FOO=1 BAR=2 mise exec -- python3 -c 'print(1)'"),
            "python3 -c 'print(1)'",
        )


class SubcommandAfterTest(unittest.TestCase):
    def test_finds_the_subcommand_behind_a_value_flag(self):
        self.assertEqual(
            _common.subcommand_after(["--session", "abc123", "get", "password"], {"--session"}),
            "get",
        )

    def test_skips_a_flag_that_carries_its_value_in_the_token(self):
        self.assertEqual(_common.subcommand_after(["--repo=owner/repo", "create"]), "create")

    def test_keeps_a_flag_that_takes_no_value_from_hiding_the_subcommand(self):
        self.assertEqual(_common.subcommand_after(["--raw", "get", "password"]), "get")

    def test_treats_an_unknown_space_form_flag_as_taking_a_value(self):
        self.assertEqual(
            _common.subcommand_after(["-R", "owner/repo", "create"], space_form_takes_value=True),
            "create",
        )

    def test_finds_nothing_after_a_double_dash(self):
        self.assertEqual(_common.subcommand_after(["--", "create"]), "")

    def test_finds_nothing_in_flags_alone(self):
        self.assertEqual(_common.subcommand_after(["--help"]), "")

    def test_returns_the_subcommand_and_its_operands(self):
        self.assertEqual(
            _common.subcommand_tokens(["-o", "env", "secret", "get", "id"], {"-o"}),
            ["secret", "get", "id"],
        )


class GhDispatchTest(unittest.TestCase):
    def test_finds_the_noun_behind_a_flag_in_front_of_it(self):
        self.assertEqual(
            _common.gh_dispatch(["gh", "--repo", "owner/repo", "secret", "list"]),
            ["secret", "list"],
        )

    def test_finds_the_noun_behind_a_flag_that_carries_its_value(self):
        self.assertEqual(
            _common.gh_dispatch(["gh", "--method=PATCH", "api", "repos/owner/repo"]),
            ["api", "repos/owner/repo"],
        )

    def test_finds_the_noun_without_a_flag_in_front_of_it(self):
        self.assertEqual(
            _common.gh_dispatch(["gh", "label", "create", "bug"]), ["label", "create", "bug"]
        )

    def test_finds_nothing_for_another_command(self):
        self.assertEqual(_common.gh_dispatch(["kubectl", "get", "secret"]), [])

    def test_finds_nothing_for_gh_alone(self):
        self.assertEqual(_common.gh_dispatch(["gh"]), [])
        self.assertEqual(_common.gh_dispatch([]), [])


class MalformedQuotingViolationTest(unittest.TestCase):
    def test_denies_a_policed_command_whose_quoting_does_not_parse(self):
        reason = _common.malformed_quoting_violation('gh repo edit owner/repo --description "unc')
        self.assertIsNotNone(reason)
        self.assertIn("quoting is unbalanced", reason)

    def test_allows_a_policed_command_whose_quoting_parses(self):
        self.assertIsNone(
            _common.malformed_quoting_violation("gh repo edit owner/repo --description 'new'")
        )

    def test_allows_an_unparseable_command_that_is_not_policed(self):
        self.assertIsNone(_common.malformed_quoting_violation('jq --arg name "unclosed'))

    def test_allows_an_empty_part(self):
        self.assertIsNone(_common.malformed_quoting_violation(""))

    def test_finds_a_policed_command_behind_its_absolute_path(self):
        self.assertIsNotNone(
            _common.malformed_quoting_violation('/opt/homebrew/bin/gh repo edit -d "unc')
        )


if __name__ == "__main__":
    unittest.main()
