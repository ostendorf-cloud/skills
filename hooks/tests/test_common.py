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


if __name__ == "__main__":
    unittest.main()
