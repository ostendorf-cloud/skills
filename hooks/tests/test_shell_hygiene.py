# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for shell_hygiene.py."""

import unittest

from helper import bash_payload, decision, run_hook


class ShellHygieneTest(unittest.TestCase):
    def test_allows_ordinary_commands(self):
        for command in [
            "task lint 2>&1",
            "python3 -m unittest discover",
            "grep -rn 'func main' .",
            "echo done > /dev/null",
            'echo "value=1" >> "$GITHUB_OUTPUT"',
            "echo done > /tmp/out.txt",
            "python3 -c 'print(1)'",
            "git commit -m \"$(cat <<'EOF'\nfeat: add thing\nEOF\n)\"",
        ]:
            self.assertIsNone(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), command
            )

    def test_denies_file_authoring_through_redirection(self):
        for command in [
            "echo hello > README.md",
            "printf 'x' > config.json",
            "cat input.txt > output.txt",
            "cat input | tee out.json",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_in_place_editing(self):
        for command in [
            "sed -i '' 's/a/b/' main.go",
            "sed -i.bak 's/a/b/' main.go",
            "perl -i -pe 's/a/b/' main.go",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_heredoc_into_a_file(self):
        command = "cat > internal/sync/skills.go <<'GO'\npackage sync\nGO"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_heredoc_fed_to_an_interpreter(self):
        for command in [
            "python3 - <<'PY'\nopen('x', 'w').write('1')\nPY",
            "python3 <<PY\nprint(1)\nPY",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_long_or_multiline_inline_scripts(self):
        for command in [
            "python3 -c 'import json\nprint(json.dumps({}))'",
            "node -e " + "'" + "x" * 210 + "'",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )


if __name__ == "__main__":
    unittest.main()
