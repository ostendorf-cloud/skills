# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for tofu_fmt.py."""

import os
import shutil
import tempfile
import unittest

from helper import context, run_hook, write_payload

TOFU_AVAILABLE = shutil.which("tofu") is not None
UNFORMATTED = 'resource "null_resource" "x" {\n  count=1\n}\n'


def write(content: str, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(content)
        return handle.name


class TofuFmtTest(unittest.TestCase):
    @unittest.skipUnless(TOFU_AVAILABLE, "tofu is not installed on this machine")
    def test_reports_a_file_tofu_fmt_would_change(self):
        path = write(UNFORMATTED, ".tf")
        self.addCleanup(os.unlink, path)
        message = context(run_hook("tofu_fmt.py", write_payload(path)))
        self.assertIn("tofu fmt would change", message)
        self.assertIn(path, message)

    @unittest.skipUnless(TOFU_AVAILABLE, "tofu is not installed on this machine")
    def test_never_rewrites_the_file(self):
        path = write(UNFORMATTED, ".tf")
        self.addCleanup(os.unlink, path)
        run_hook("tofu_fmt.py", write_payload(path))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), UNFORMATTED)

    @unittest.skipUnless(TOFU_AVAILABLE, "tofu is not installed on this machine")
    def test_quiet_on_an_already_formatted_file(self):
        path = write('resource "null_resource" "x" {\n  count = 1\n}\n', ".tf")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("tofu_fmt.py", write_payload(path))), "")

    def test_quiet_when_tofu_is_absent(self):
        path = write(UNFORMATTED, ".tf")
        self.addCleanup(os.unlink, path)
        output = run_hook("tofu_fmt.py", write_payload(path), env={"PATH": "/nonexistent"})
        self.assertEqual(context(output), "")

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
