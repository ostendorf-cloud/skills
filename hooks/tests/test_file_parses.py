# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for file_parses.py."""

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


class FileParsesTest(unittest.TestCase):
    def test_quiet_on_valid_yaml(self):
        path = write("items:\n  - one\n  - two\nkey: value\n", ".yaml")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_reports_invalid_yaml(self):
        path = write("items:\n  - `brew install thing` works\n", ".yaml")
        self.addCleanup(os.unlink, path)
        self.assertIn("no longer parses", context(run_hook("file_parses.py", write_payload(path))))

    def test_quiet_on_valid_json(self):
        path = write('{"key": "value"}\n', ".json")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_reports_invalid_json(self):
        path = write('{"key": "value"', ".json")
        self.addCleanup(os.unlink, path)
        self.assertIn("no longer parses", context(run_hook("file_parses.py", write_payload(path))))

    def test_quiet_on_valid_toml(self):
        path = write('key = "value"\n', ".toml")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_reports_invalid_toml(self):
        path = write("key = \n", ".toml")
        self.addCleanup(os.unlink, path)
        self.assertIn("no longer parses", context(run_hook("file_parses.py", write_payload(path))))

    def test_ignores_files_of_another_type(self):
        path = write("this is not yaml at all: [", ".md")
        self.addCleanup(os.unlink, path)
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_ignores_a_path_that_does_not_exist(self):
        self.assertEqual(
            context(run_hook("file_parses.py", write_payload("/nonexistent/file.yaml"))), ""
        )

    def test_ignores_files_under_worktrees(self):
        directory = tempfile.mkdtemp(prefix="file-parses-")
        worktree_dir = os.path.join(directory, ".worktrees", "feat-thing")
        os.makedirs(worktree_dir)
        path = os.path.join(worktree_dir, "broken.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("items:\n  - `broken` here\n")
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_ignores_files_under_claude_worktrees(self):
        directory = tempfile.mkdtemp(prefix="file-parses-")
        worktree_dir = os.path.join(directory, ".claude", "worktrees", "feat-thing")
        os.makedirs(worktree_dir)
        path = os.path.join(worktree_dir, "broken.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("items:\n  - `broken` here\n")
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")

    def test_ignores_a_templates_file_with_go_template_syntax(self):
        directory = tempfile.mkdtemp(prefix="file-parses-")
        templates_dir = os.path.join(directory, "templates")
        os.makedirs(templates_dir)
        path = os.path.join(templates_dir, "job.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{{- /* a comment */ -}}\nkind: Job\n")
        self.assertEqual(context(run_hook("file_parses.py", write_payload(path))), "")


if __name__ == "__main__":
    unittest.main()
