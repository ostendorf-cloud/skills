# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for gh_alone.py."""

import contextlib
import io
import json
import sys
import unittest
from typing import Any
from unittest import mock

from helper import HOOKS_DIR, bash_payload, decision, reason, run_hook

# Imported in process, so the tests can fake sys.platform as test_git_guard does. The
# path is put back right after the import.
_saved_path = list(sys.path)
sys.path.insert(0, HOOKS_DIR)
import gh_alone  # noqa: E402

sys.path[:] = _saved_path


def run_on(platform: str, command: str) -> dict[str, Any]:
    """Runs gh_alone.main() in this process with sys.platform faked as platform."""
    payload = json.dumps(bash_payload(command))
    out = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "platform", platform))
        stack.enter_context(mock.patch.object(sys, "stdin", io.StringIO(payload)))
        stack.enter_context(contextlib.redirect_stdout(out))
        gh_alone.main()
    return json.loads(out.getvalue())


class GhAloneTest(unittest.TestCase):
    def assert_denied(self, command: str) -> None:
        output = run_on("darwin", command)
        self.assertEqual(decision(output), "deny", command)
        self.assertIn("--repo", reason(output))

    def assert_allowed(self, command: str, platform: str = "darwin") -> None:
        self.assertEqual(run_on(platform, command), {}, command)

    def test_allows_a_single_gh_call(self):
        self.assert_allowed("gh pr list")

    def test_allows_a_single_gh_call_with_options(self):
        self.assert_allowed("gh pr view 12 --repo ostendorf-cloud/skills --json title --jq .title")

    def test_allows_a_quoted_jq_filter_with_a_pipe_inside(self):
        self.assert_allowed("gh pr list --json number,title --jq '.[] | select(.number > 3)'")

    def test_allows_a_body_file_call(self):
        self.assert_allowed("gh pr create --title 'feat: x' --body-file /tmp/claude/body.md")

    def test_allows_a_kept_stderr_redirection(self):
        self.assert_allowed("gh pr list 2>&1")

    def test_allows_gh_behind_time_and_by_path(self):
        self.assert_allowed("time gh pr list")
        self.assert_allowed("/opt/homebrew/bin/gh pr list")

    def test_denies_gh_behind_cd(self):
        self.assert_denied("cd /Users/me/Code/repo && gh pr list")

    def test_denies_gh_piped_into_another_command(self):
        self.assert_denied("gh pr list --json number | jq '.[0]'")

    def test_denies_gh_behind_a_pipe(self):
        self.assert_denied("echo 12 | gh pr view")

    def test_denies_gh_with_an_output_redirection(self):
        self.assert_denied("gh pr list > /tmp/claude/prs.txt")

    def test_denies_gh_with_an_input_redirection(self):
        self.assert_denied("gh pr create --body-file - < /tmp/claude/body.md")

    def test_denies_gh_with_a_heredoc(self):
        self.assert_denied("gh pr comment 3 --body-file - <<EOF\nlooks fine\nEOF")

    def test_denies_gh_in_a_for_loop(self):
        self.assert_denied("for n in 1 2 3; do gh pr view $n; done")

    def test_denies_gh_in_a_while_loop_on_one_line(self):
        self.assert_denied("while read n; do gh pr view $n; done < list.txt")

    def test_denies_gh_in_a_condition(self):
        self.assert_denied("if gh auth status; then echo ok; fi")

    def test_denies_two_gh_calls_with_a_semicolon(self):
        self.assert_denied("gh pr list; gh issue list")

    def test_denies_two_gh_calls_with_and(self):
        self.assert_denied("gh pr list && gh issue list")

    def test_denies_two_gh_calls_with_or(self):
        self.assert_denied("gh pr list || gh issue list")

    def test_denies_gh_on_a_second_line(self):
        self.assert_denied("gh pr list\ngh issue list")

    def test_denies_gh_in_the_background(self):
        self.assert_denied("gh run watch 5 &")

    def test_denies_gh_in_a_command_substitution_assignment(self):
        self.assert_denied("number=$(gh pr list --json number --jq '.[0].number')")

    def test_denies_gh_in_a_command_substitution_argument(self):
        self.assert_denied("echo $(gh pr list)")

    def test_denies_gh_in_a_backtick_substitution(self):
        self.assert_denied("echo `gh pr list`")

    def test_denies_gh_in_a_subshell(self):
        self.assert_denied("(gh pr list)")

    def test_allows_gh_behind_an_environment_assignment(self):
        self.assert_allowed("GH_TOKEN=abc gh api repos/ostendorf-cloud/skills/pulls/1")

    def test_allows_gh_behind_several_environment_assignments(self):
        self.assert_allowed("GH_HOST=github.com GH_TOKEN=abc gh pr list")

    def test_denies_gh_behind_an_environment_assignment_in_a_chain(self):
        self.assert_denied("GH_TOKEN=abc gh pr list && gh issue list")

    def test_denies_gh_behind_env(self):
        self.assert_denied("env GH_HOST=github.com gh pr list")

    def test_denies_gh_with_an_absolute_path_in_a_chain(self):
        self.assert_denied("cd x && /opt/homebrew/bin/gh pr list")

    def test_ignores_gh_as_text_in_a_quoted_argument(self):
        self.assert_allowed("echo 'gh pr list' && ls")
        self.assert_allowed('echo "gh pr list" | cat')

    def test_ignores_a_quoted_command_substitution_text(self):
        self.assert_allowed("echo '$(gh pr list)' | cat")

    def test_ignores_gh_as_part_of_another_word(self):
        self.assert_allowed("./gh-helper pr list && ls")
        self.assert_allowed("ghost --version | cat")

    def test_ignores_gh_as_an_argument(self):
        self.assert_allowed("git log --grep gh | head")
        self.assert_allowed("ls gh && pwd")

    def test_ignores_commands_without_gh(self):
        self.assert_allowed("cd x && git status | cat")

    def test_allows_every_shape_on_linux(self):
        for command in (
            "cd x && gh pr list",
            "gh pr list | jq .",
            "gh pr list > f",
            "for n in 1; do gh pr view $n; done",
            "n=$(gh pr list)",
        ):
            self.assert_allowed(command, platform="linux")

    def test_stays_quiet_for_an_empty_or_malformed_payload(self):
        for payload in ("", "not json", "{}", '{"tool_input": {"command": 5}}'):
            out = io.StringIO()
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(sys, "platform", "darwin"))
                stack.enter_context(mock.patch.object(sys, "stdin", io.StringIO(payload)))
                stack.enter_context(contextlib.redirect_stdout(out))
                self.assertEqual(gh_alone.main(), 0)
            self.assertEqual(json.loads(out.getvalue()), {}, payload)

    def test_script_denies_only_on_the_platform_it_runs_on_when_started_as_a_process(self):
        output = run_hook("gh_alone.py", bash_payload("cd x && gh pr list"))
        self.assertEqual(decision(output), "deny" if sys.platform == "darwin" else None)


if __name__ == "__main__":
    unittest.main()
