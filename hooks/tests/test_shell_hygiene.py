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
            "sed -n '1,5p' x.go",
            "perl -ne 'print' x.go",
            'gh pr comment 1 --body "never use sed -i"',
            "python3 report.py <<EOF\n1\nEOF",
            "python3 -c 'print(1 << 3)'",
            "perl deploy.pl -i config.yaml",
            "perl -Ilib -ne 'print' x.go",
            "perl -MFile::Basename -e 'print basename($ARGV[0])' x.go",
            "sed -n '1p' -- -input.txt",
            "curl -d 'user=sed' -i https://example.com/api/login",
            "curl --data tool=perl -i https://example.com/api/tools",
            "cat <<'SQL' | psql service | python3 report.py\nselect 1;\nSQL",
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

    def test_denies_in_place_editing_regardless_of_flag_order(self):
        for command in [
            "perl -p -i -e 's/a/b/' x.go",
            "sed -e 's/a/b/' -i x.go",
            "perl -0pi -e 's/a/b/' x.go",
            "sed 's/a/b/' x.go -i",
            "perl -i.bak -pe 's/a/b/' x.go",
            "sed --in-place 's/a/b/' x.go",
            "sed --in-place=.bak 's/a/b/' x.go",
            "sed --in 's/a/b/' x.go",
            "sed -I '' -e 's/a/b/' x.go",
            "sed '-i' -e 's/a/b/' x.go",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_in_place_editing_wherever_the_call_sits(self):
        for command in [
            "find . -name '*.go' | xargs sed -i '' -e 's/a/b/'",
            "git ls-files -z | xargs -0 perl -pi -e 's/a/b/'",
            "for f in *.go; do sed -i '' 's/a/b/' $f; done",
            "if true; then sed -i '' 's/a/b/' x.go; fi",
            "(sed -i '' 's/a/b/' x.go)",
            "bash -c 'sed -i \"\" -e s/a/b/ x.go'",
            "while read f; do sed -i '' 's/a/b/' \"$f\"; done < files.txt",
            "out=$(sed -i '' 's/a/b/' x.go)",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_in_place_editing_under_another_command_name(self):
        for command in [
            "gsed -i 's/a/b/' x.go",
            "perl5.34 -pi -e 's/a/b/' x.go",
            "/usr/bin/sed -i '' 's/a/b/' x.go",
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

    def test_denies_heredoc_fed_to_an_interpreter_given_by_path(self):
        command = "/usr/bin/python3 <<PY\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_heredoc_fed_to_an_interpreter_with_flags_before_it(self):
        command = "python3 -u <<PY\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_behind_a_cd_in_the_same_command(self):
        command = "cd /tmp && python3 <<PY\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_piped_into_an_interpreter(self):
        command = "cat <<'PY' | python3\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_piped_into_an_interpreter_behind_a_wrapper(self):
        command = "cat <<'PY' | mise exec -- python3\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_piped_into_an_interpreter_mid_pipeline(self):
        command = "cat <<'PY' | python3 - | grep 1\nprint(1)\nPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_fed_to_an_interpreter_inside_a_nested_shell(self):
        command = "bash -c 'python3 <<PY\nprint(1)\nPY'"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_fed_to_an_interpreter_in_a_subshell(self):
        for command in [
            "(python3 <<PY\nprint(1)\nPY\n)",
            "out=$(python3 <<PY\nprint(1)\nPY\n)",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_dash_heredoc_fed_to_an_interpreter(self):
        command = "python3 <<-PY\n\tprint(1)\n\tPY"
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_a_heredoc_fed_to_an_interpreter_through_a_wrapper(self):
        for command in [
            "mise exec -- python3 <<PY\nprint(1)\nPY",
            "env FOO=1 python3 <<PY\nprint(1)\nPY",
            "time python3 <<PY\nprint(1)\nPY",
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
            """python3 -c "from pathlib import Path; """
            """Path('a').open('w').write('x')" """.strip(),
            """python3 -c "from pathlib import Path; """
            """Path('a').open(mode='w').write('x')" """.strip(),
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_allows_a_single_argument_open_call_whose_argument_is_a_path(self):
        command = """python3 -c "import io; io.open('ab')" """.strip()
        self.assertIsNone(decision(run_hook("shell_hygiene.py", bash_payload(command))))

    def test_denies_a_bound_open_call_whose_sole_argument_is_a_mode(self):
        command = """python3 -c "from pathlib import Path; Path('a').open('ab')" """.strip()
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_perl_open_without_parentheses(self):
        command = """perl -e 'open my $fh, ">", "notes.md"; print $fh "x"'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_allows_an_interpreter_mentioned_as_another_commands_argument(self):
        command = """echo python3 -c 'open("a", "w")'"""
        self.assertIsNone(decision(run_hook("shell_hygiene.py", bash_payload(command))))

    def test_denies_an_inline_write_through_a_mise_exec_wrapper(self):
        command = """mise exec -- python3 -c 'open("a", "w").write("x")'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_an_inline_write_through_an_env_assignment_wrapper(self):
        command = """env FOO=1 python3 -c 'open("a", "w").write("x")'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_denies_an_inline_write_through_a_time_wrapper(self):
        command = """time python3 -c 'open("a", "w").write("x")'"""
        self.assertEqual(decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny")

    def test_allows_a_read_only_inline_call_through_a_mise_exec_wrapper(self):
        command = 'mise exec -- python3 -c "print(1)"'
        self.assertIsNone(decision(run_hook("shell_hygiene.py", bash_payload(command))))

    def test_denies_an_inline_write_through_a_flagged_or_escalating_wrapper(self):
        for command in [
            """nice -n 10 python3 -c 'open("a", "w").write("x")'""",
            """nohup -- python3 -c 'open("a", "w").write("x")'""",
            """sudo python3 -c 'open("a", "w").write("x")'""",
            """sudo -u ci python3 -c 'open("a", "w").write("x")'""",
            """doas python3 -c 'open("a", "w").write("x")'""",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_in_place_edit_and_a_tee_through_a_flagged_or_escalating_wrapper(self):
        for command in [
            "nice -n 10 sed -i '' 's/a/b/' x.go",
            "sudo sed -i '' 's/a/b/' x.go",
            "nice -n 10 tee notes.md",
            "sudo tee /etc/hosts",
            "doas tee /etc/hosts",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_heredoc_piped_into_an_interpreter_behind_a_flagged_wrapper(self):
        for command in [
            "cat <<'PY' | nice -n 10 python3\nprint(1)\nPY",
            "cat <<'PY' | sudo python3\nprint(1)\nPY",
        ]:
            self.assertEqual(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), "deny", command
            )

    def test_allows_a_read_only_inline_call_through_a_flagged_wrapper(self):
        for command in [
            'nice -n 10 python3 -c "print(1)"',
            'sudo python3 -c "print(1)"',
        ]:
            self.assertIsNone(
                decision(run_hook("shell_hygiene.py", bash_payload(command))), command
            )


if __name__ == "__main__":
    unittest.main()
