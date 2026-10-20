# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for tofu_fmt.py."""

import os
import tempfile
import unittest

from helper import context, run_hook, write_payload


def write(content: str, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(content)
        return handle.name


class TofuFmtTest(unittest.TestCase):
    def test_reports_a_file_tofu_fmt_rewrites(self):
        path = write('resource "null_resource" "x" {\n  count=1\n}\n', ".tf")
        self.addCleanup(os.unlink, path)
        message = context(run_hook("tofu_fmt.py", write_payload(path)))
        self.assertIn("tofu fmt rewrote", message)
        self.assertIn(path, message)

    def test_quiet_on_an_already_formatted_file(self):
        path = write('resource "null_resource" "x" {\n  count = 1\n}\n', ".tf")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("tofu_fmt.py", write_payload(path))), "")

    def test_ignores_files_of_another_type(self):
        path = write("not tofu at all\n", ".txt")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("tofu_fmt.py", write_payload(path))), "")

    def test_ignores_a_path_that_does_not_exist(self):
        self.assertEqual(
            context(run_hook("tofu_fmt.py", write_payload("/nonexistent/file.tf"))), ""
        )


if __name__ == "__main__":
    unittest.main()
