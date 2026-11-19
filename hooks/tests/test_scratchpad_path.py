# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for scratchpad_path.py."""

import subprocess
import sys
import unittest

from helper import HOOKS_DIR, bash_payload, decision, file_tool_payload, reason, run_hook

PROJECT = "-Users-simonostendorf-Code-github-com-ostendorf-cloud"
SESSION = "b568d98e-07b5-4f88-bb7f-bbdba6a343a2"
OTHER_SESSION = "0a1b2c3d-1111-2222-3333-444455556666"
BASE = f"/private/tmp/claude-501/{PROJECT}"
WRONG = f"{BASE}-{SESSION}/scratchpad/notes.md"
RIGHT = f"{BASE}/{SESSION}/scratchpad/notes.md"
FIXED_DIR = f"{BASE}/{SESSION}/"


def run(payload):
    return run_hook("scratchpad_path.py", payload)


class ScratchpadPathTest(unittest.TestCase):
    def test_denies_wrong_path_in_bash_command(self):
        output = run(bash_payload(f"git commit -F {WRONG}"))
        self.assertEqual(decision(output), "deny")

    def test_denial_shows_corrected_path(self):
        output = run(bash_payload(f"git commit -F {WRONG}"))
        self.assertIn(FIXED_DIR, reason(output))
        self.assertNotIn(f"{PROJECT}-{SESSION}", reason(output))

    def test_denies_wrong_path_for_file_tools(self):
        for tool in ("Read", "Write", "Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                output = run(file_tool_payload(tool, WRONG))
                self.assertEqual(decision(output), "deny")

    def test_denies_wrong_path_for_notebook_edit(self):
        output = run(file_tool_payload("NotebookEdit", f"{BASE}-{SESSION}/scratchpad/a.ipynb"))
        self.assertEqual(decision(output), "deny")

    def test_denies_wrong_path_on_the_tmp_alias(self):
        output = run(bash_payload(f"cat /tmp/claude-501/{PROJECT}-{SESSION}/x"))
        self.assertEqual(decision(output), "deny")

    def test_denies_wrong_path_at_end_of_input(self):
        output = run(bash_payload(f"ls {BASE}-{SESSION}"))
        self.assertEqual(decision(output), "deny")

    def test_denial_lists_every_wrong_path_in_one_command(self):
        other = f"{BASE}-{OTHER_SESSION}/scratchpad/b.md"
        output = run(bash_payload(f"cp {WRONG} {other}"))
        self.assertEqual(decision(output), "deny")
        self.assertIn(FIXED_DIR, reason(output))
        self.assertIn(f"{BASE}/{OTHER_SESSION}/", reason(output))

    def test_denial_names_a_repeated_path_once(self):
        output = run(bash_payload(f"cp {WRONG} {WRONG}.bak"))
        self.assertEqual(reason(output).count(FIXED_DIR), 1)

    def test_allows_corrected_path(self):
        self.assertIsNone(decision(run(bash_payload(f"cat {RIGHT}"))))
        self.assertIsNone(decision(run(file_tool_payload("Read", RIGHT))))

    def test_allows_other_uid(self):
        path = f"/private/tmp/claude-502/{PROJECT}/{SESSION}/scratchpad/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_project_dir_that_contains_the_word_uuid(self):
        path = f"/private/tmp/claude-501/-Users-me-Code-uuid-tools/{SESSION}/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_dash_name_that_is_not_a_session_id(self):
        path = "/private/tmp/claude-501/-Users-me-Code-some-project/scratchpad/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_hex_run_longer_than_a_session_id(self):
        path = f"{BASE}-{SESSION}0/scratchpad/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_session_id_in_a_file_name_under_the_correct_dir(self):
        path = f"{BASE}/{SESSION}/scratchpad/out-{SESSION}.log"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_project_dir_without_leading_dash(self):
        path = f"/tmp/claude-501/foo-{SESSION}/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_wrong_shaped_id_followed_by_more_text(self):
        for suffix in ("-old", "x"):
            with self.subTest(suffix=suffix):
                path = f"{BASE}-{SESSION}{suffix}/a.md"
                self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_non_numeric_or_missing_uid(self):
        for name in ("claude-cache", "claude-"):
            with self.subTest(name=name):
                path = f"/tmp/{name}/-x-{SESSION}/a.md"
                self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_relative_path_ending_in_tmp(self):
        path = f"./tmp/claude-501/{PROJECT}-{SESSION}/a.md"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_denies_wrong_path_at_start_and_after_a_separator(self):
        for command in (
            f"{BASE}-{SESSION}/a.md",
            f"cat {BASE}-{SESSION}/a.md",
            f"cat '{BASE}-{SESSION}/a.md'",
            f'cat "{BASE}-{SESSION}/a.md"',
            f"FILE={BASE}-{SESSION}/a.md cat",
        ):
            with self.subTest(command=command):
                self.assertEqual(decision(run(bash_payload(command))), "deny")

    def test_allows_wrong_path_inside_another_path(self):
        for path in (
            f"/private/var/tmp/claude-501/{PROJECT}-{SESSION}/a.md",
            f"/data/tmp/claude-501/{PROJECT}-{SESSION}/a.md",
        ):
            with self.subTest(path=path):
                self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_allows_session_id_elsewhere(self):
        self.assertIsNone(decision(run(bash_payload(f"cat /var/log/app-{SESSION}/x"))))
        self.assertIsNone(decision(run(bash_payload(f"cat /private/tmp/other-tool-{SESSION}/x"))))

    def test_allows_other_tool_path_with_session_id(self):
        path = f"/private/tmp/claude-501/{PROJECT}/{SESSION}/tasks/{SESSION}.output"
        self.assertIsNone(decision(run(bash_payload(f"cat {path}"))))

    def test_ignores_tool_input_fields_that_hold_no_path(self):
        payload = file_tool_payload("Write", f"{RIGHT}")
        payload["tool_input"]["content"] = f"see {WRONG}"
        self.assertIsNone(decision(run(payload)))

    def test_ignores_empty_and_malformed_input(self):
        self.assertEqual(run({}), {})
        self.assertEqual(run({"tool_input": None}), {})
        self.assertEqual(run({"tool_input": "text"}), {})
        self.assertEqual(run({"tool_input": {"command": 5, "file_path": None}}), {})
        self.assertEqual(run(bash_payload("")), {})

    def test_garbage_stdin_prints_empty_json_and_exits_zero(self):
        result = subprocess.run(
            [sys.executable, f"{HOOKS_DIR}/scratchpad_path.py"],
            input="not json {{{",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
