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
            'git commit -m "feat: handle a > b"',
            'gh pr comment 1 --body "latency 10 -> 5"',
            'jq ".a > 1" x.json',
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
            "echo x > file.txt",
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

    def test_denies_inline_interpreter_writing_a_file(self):
        for command in [
            """python3 -c 'open(p, "w")'""",
            """node -e "require('fs').writeFileSync('x', '1')" """.strip(),
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_allows_inline_interpreter_reading_a_file(self):
        for command in [
            'python3 -c "print(1)"',
            """python3 -c "print(open('x').read())" """.strip(),
            """node -e "console.log(require('fs').readFileSync('x', 'utf8'))" """.strip(),
        ]:
            self.assertIsNone(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), command
            )

    def test_denies_a_write_in_the_second_part_of_a_chained_command(self):
        command = """python3 -c "print(1)" && python3 -c 'open("a", "w").write("x")'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_node_append_calls(self):
        for command in [
            """node -e "require('fs').appendFileSync('a', 'x')" """.strip(),
            """node -e "require('fs').appendFile('a', 'x', () => {})" """.strip(),
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_dotted_open_receivers_with_a_write_mode(self):
        for command in [
            """python3 -c "import io; io.open('a', 'w').write('x')" """.strip(),
            """python3 -c "from pathlib import Path; Path('a').open('w').write('x')" """.strip(),
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_perl_open_without_parentheses(self):
        command = """perl -e 'open my $fh, ">", "notes.md"; print $fh "x"'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_allows_an_interpreter_mentioned_as_another_commands_argument(self):
        command = """echo python3 -c 'open("a", "w")'"""
        self.assertIsNone(decision(run_hook("shell_hygiene.py", bash_payload(command))))


if __name__ == "__main__":
    unittest.main()
