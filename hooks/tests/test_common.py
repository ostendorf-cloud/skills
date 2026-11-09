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


class ShellWordsTest(unittest.TestCase):
    def test_keeps_a_quoted_argument_in_one_word(self):
        self.assertEqual(
            _common.shell_words("git commit -m 'feat: add valkey module'"),
            ["git", "commit", "-m", "'feat: add valkey module'"],
        )

    def test_keeps_a_quoted_assignment_value_in_one_word(self):
        self.assertEqual(
            _common.shell_words('GIT_AUTHOR_NAME="a b" git push'),
            ['GIT_AUTHOR_NAME="a b"', "git", "push"],
        )

    def test_keeps_the_quoting_so_the_words_rejoin_to_the_command(self):
        command = 'git commit -m "feat: add valkey module"'
        self.assertEqual(" ".join(_common.shell_words(command)), command)

    def test_keeps_an_escaped_space_in_one_word(self):
        self.assertEqual(
            _common.shell_words("/opt/my\\ tools/git push"),
            ["/opt/my\\ tools/git", "push"],
        )

    def test_falls_back_to_a_whitespace_split_on_an_open_quote(self):
        self.assertEqual(
            _common.shell_words('git commit -m "wip'),
            ["git", "commit", "-m", '"wip'],
        )

    def test_returns_no_words_for_an_empty_part(self):
        self.assertEqual(_common.shell_words("   "), [])


class CommandNameTest(unittest.TestCase):
    def test_resolves_a_quoted_command_name(self):
        for part in [
            '"/usr/bin/git" push --force origin main',
            "'/usr/bin/git' push --force origin main",
            '"git" push --force origin main',
            "'git' push --force origin main",
        ]:
            self.assertEqual(_common.command_name(part), "git", part)

    def test_resolves_the_unquoted_forms_the_same(self):
        for part in ["/usr/bin/git push --force origin main", "git push --force origin main"]:
            self.assertEqual(_common.command_name(part), "git", part)

    def test_resolves_a_name_whose_path_holds_an_escaped_space(self):
        self.assertEqual(_common.command_name("/opt/my\\ tools/git push"), "git")

    def test_resolves_a_quoted_name_left_with_an_open_quote(self):
        self.assertEqual(_common.command_name('"git push --force origin main'), "git")

    def test_keeps_a_name_that_only_ends_in_the_tool_name_apart(self):
        for part, name in [
            ("legit push --force origin main", "legit"),
            ("mygit push --force origin main", "mygit"),
            ("gitless push --force origin main", "gitless"),
            ("git-crypt unlock", "git-crypt"),
            ("git-town sync", "git-town"),
            ('"/usr/local/bin/mygit" push --force origin main', "mygit"),
        ]:
            self.assertEqual(_common.command_name(part), name, part)

    def test_returns_an_empty_name_for_an_empty_part(self):
        self.assertEqual(_common.command_name(""), "")


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

    def test_strips_a_bare_wrapper_name(self):
        for part in [
            "time git push --force origin main",
            "nice git push --force origin main",
            "nohup git push --force origin main",
            "command git push --force origin main",
            "exec git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_a_wrapper_carrying_its_own_flags(self):
        for part in [
            "nice -n 10 git push --force origin main",
            "nice -n-5 git push --force origin main",
            "nice --adjustment=10 git push --force origin main",
            "nice --adjustment 10 git push --force origin main",
            "nice -10 git push --force origin main",
            "nohup -- git push --force origin main",
            "sudo -u ci git push --force origin main",
            "sudo -E -n git push --force origin main",
            "sudo --user=ci git push --force origin main",
            "doas -u ci git push --force origin main",
            "doas -L -n git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_a_privilege_escalation_prefix(self):
        for part in [
            "sudo git push --force origin main",
            "doas git push --force origin main",
            "sudo nice -n 10 git push --force origin main",
            "sudo env GIT_PAGER=cat git push --force origin main",
            "sudo GIT_PAGER=cat git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_a_wrapper_named_by_a_path_or_in_quotes(self):
        for part in [
            "/usr/bin/nice -n 10 git push --force origin main",
            '"/usr/bin/sudo" git push --force origin main',
            '"sudo" git push --force origin main',
            "/usr/bin/env git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_a_quoted_assignment_prefix(self):
        self.assertEqual(
            _common.strip_wrappers('GIT_AUTHOR_NAME="a b" git push --force origin main'),
            "git push --force origin main",
        )

    def test_strips_a_cluster_of_short_flags_ending_in_a_value_flag(self):
        for part in [
            "sudo -nu ci git push --force origin main",
            "sudo -Enu ci git push --force origin main",
            "sudo -bEnu ci git push --force origin main",
            "sudo -nT 30 git push --force origin main",
            "sudo -SnU ci git push --force origin main",
            "doas -nu ci git push --force origin main",
            "doas -Lnu ci git push --force origin main",
            "/usr/bin/time -ao /var/log/push.log git push --force origin main",
            "exec -la foo git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_keeps_the_next_word_when_a_short_value_flag_holds_its_value_in_the_cluster(self):
        for part in [
            "sudo -nuci git push --force origin main",
            "doas -nuci git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_reads_the_rest_of_a_cluster_as_the_value_of_a_short_value_flag(self):
        self.assertEqual(
            _common.strip_wrappers("sudo -ug ci git push --force origin main"),
            "ci git push --force origin main",
        )

    def test_strips_a_sudo_option_that_is_build_conditional_upstream(self):
        for part in [
            "sudo -a pam git push --force origin main",
            "sudo -c daemon git push --force origin main",
            "sudo -r sysadm_r git push --force origin main",
            "sudo -t unconfined_t git push --force origin main",
            "sudo -nr sysadm_r git push --force origin main",
            "sudo -nt unconfined_t git push --force origin main",
            "sudo --auth-type pam git push --force origin main",
            "sudo --login-class daemon git push --force origin main",
            "sudo --role sysadm_r git push --force origin main",
            "sudo --type unconfined_t git push --force origin main",
            "sudo --role=sysadm_r git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_the_value_flags_of_time_and_exec(self):
        for part in [
            "time -o /var/log/push.log git push --force origin main",
            "time -f %e git push --force origin main",
            "time --output /var/log/push.log git push --force origin main",
            "time --format %e git push --force origin main",
            "time --output=/var/log/push.log git push --force origin main",
            "exec -a foo git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_an_unambiguously_abbreviated_long_value_flag(self):
        for part in [
            "nice --adj 10 git push --force origin main",
            "nice --adjust 10 git push --force origin main",
            "sudo --us ci git push --force origin main",
            "sudo --ro sysadm_r git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_leaves_an_ambiguous_long_flag_abbreviation_alone(self):
        self.assertEqual(
            _common.strip_wrappers("sudo --ch /srv git push --force origin main"),
            "/srv git push --force origin main",
        )

    def test_reads_a_boolean_long_flag_as_taking_no_following_word(self):
        for part in [
            "sudo --login git push --force origin main",
            "sudo --list git push --force origin main",
            "sudo --preserve-env git push --force origin main",
            "sudo --non-interactive git push --force origin main",
            "nice --help git push --force origin main",
            "nohup --version git push --force origin main",
            "time --append git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_prefers_an_exact_boolean_long_flag_over_a_value_flag_it_abbreviates(self):
        self.assertEqual(
            _common.strip_wrappers("sudo --login git push --force origin main"),
            _common.strip_wrappers("sudo -i git push --force origin main"),
        )

    def test_strips_a_long_value_flag_a_boolean_flag_abbreviates(self):
        for part in [
            "sudo --login-class admin git push --force origin main",
            "sudo --login-class=admin git push --force origin main",
            "sudo --login-c admin git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_leaves_an_abbreviation_ambiguous_across_boolean_and_value_flags_alone(self):
        for part in [
            "sudo --log git push --force origin main",
            "sudo --h git push --force origin main",
            "sudo --p git push --force origin main",
            "time --v git push --force origin main",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "git push --force origin main", part)

    def test_strips_an_abbreviated_flag_that_runs_no_command_to_nothing(self):
        self.assertEqual(_common.strip_wrappers("sudo --edi /etc/sudoers"), "")

    def test_strips_a_wrapper_that_runs_no_command_to_nothing(self):
        for part in [
            "sudo -e /etc/sudoers",
            "sudo -ne /etc/sudoers",
            "sudo --edit /etc/sudoers",
            "sudo -V",
            "sudo -u",
            "sudo -nu",
            "nice -n",
            "time",
        ]:
            self.assertEqual(_common.strip_wrappers(part), "", part)

    def test_leaves_a_wrapper_it_does_not_know_in_place(self):
        for part in [
            "timeout 5 git push --force origin main",
            "xargs git push --force origin main",
            "legit push --force origin main",
            "sudoedit /etc/sudoers",
        ]:
            self.assertEqual(_common.strip_wrappers(part), part, part)


class NormalizeCommandPartTest(unittest.TestCase):
    def test_replaces_an_absolute_path_with_the_plain_command_name(self):
        self.assertEqual(
            _common.normalize_command_part("/usr/bin/git push --force origin main"),
            "git push --force origin main",
        )

    def test_strips_wrapper_prefixes_in_front_of_the_command_name(self):
        for part in [
            "time git push --force origin main",
            "command git push --force origin main",
            "env git push --force origin main",
            "exec /usr/bin/git push --force origin main",
            "nohup git push --force origin main",
            "nice git push --force origin main",
            "mise exec -- git push --force origin main",
            "time env GIT_PAGER=cat nohup /usr/bin/git push --force origin main",
        ]:
            self.assertEqual(
                _common.normalize_command_part(part), "git push --force origin main", part
            )

    def test_leaves_a_plain_command_as_written(self):
        for part in ["git push origin main", "git commit -m 'feat: x'", "git status"]:
            self.assertEqual(_common.normalize_command_part(part), part, part)

    def test_resolves_a_quoted_command_name(self):
        for part in [
            '"/usr/bin/git" push --force origin main',
            "'/usr/bin/git' push --force origin main",
            '"git" push --force origin main',
            'exec "/usr/bin/git" push --force origin main',
        ]:
            self.assertEqual(
                _common.normalize_command_part(part), "git push --force origin main", part
            )

    def test_strips_a_wrapper_carrying_its_own_flags_in_front_of_the_name(self):
        for part in [
            "nice -n 10 git push --force origin main",
            "nohup -- git push --force origin main",
            "sudo git push --force origin main",
            "sudo -u ci git push --force origin main",
            "doas git push --force origin main",
            "/usr/bin/nice -n 10 /usr/bin/git push --force origin main",
        ]:
            self.assertEqual(
                _common.normalize_command_part(part), "git push --force origin main", part
            )

    def test_keeps_a_quoted_argument_as_written(self):
        self.assertEqual(
            _common.normalize_command_part('"/usr/bin/git" commit -m "feat: add valkey module"'),
            'git commit -m "feat: add valkey module"',
        )

    def test_keeps_a_command_whose_name_only_ends_in_the_tool_name(self):
        self.assertEqual(
            _common.normalize_command_part("/usr/local/bin/mygit push --force origin main"),
            "mygit push --force origin main",
        )

    def test_keeps_a_command_whose_name_only_ends_in_the_tool_name_behind_a_wrapper(self):
        for part, expected in [
            ("nice -n 10 legit push --force origin main", "legit push --force origin main"),
            ("sudo mygit push --force origin main", "mygit push --force origin main"),
            ('"gitless" push --force origin main', "gitless push --force origin main"),
            ("git-crypt unlock", "git-crypt unlock"),
            ("git-town sync", "git-town sync"),
        ]:
            self.assertEqual(_common.normalize_command_part(part), expected, part)

    def test_returns_an_empty_part_unchanged(self):
        self.assertEqual(_common.normalize_command_part(""), "")


class StripGlobalGitOptionsTest(unittest.TestCase):
    def test_strips_the_global_options_of_a_plain_git_command(self):
        self.assertEqual(
            _common.strip_global_git_options(
                "git -c core.hooksPath=/dev/null --git-dir=/srv/repo/.git commit -m 'feat: x'"
            ),
            ("git commit -m 'feat: x'", None),
        )

    def test_returns_the_dash_c_path_of_a_plain_git_command(self):
        self.assertEqual(
            _common.strip_global_git_options("git -C /srv/repo push origin main"),
            ("git push origin main", "/srv/repo"),
        )

    def test_resolves_an_absolute_path_git_to_the_plain_command_name(self):
        self.assertEqual(
            _common.strip_global_git_options("/usr/bin/git commit -m 'feat: x'"),
            ("git commit -m 'feat: x'", None),
        )

    def test_strips_the_global_options_of_an_absolute_path_git_command(self):
        self.assertEqual(
            _common.strip_global_git_options("/usr/bin/git -C /srv/repo commit -m 'feat: x'"),
            ("git commit -m 'feat: x'", "/srv/repo"),
        )

    def test_leaves_a_command_whose_name_only_ends_in_git_unchanged(self):
        self.assertEqual(
            _common.strip_global_git_options("/usr/local/bin/mygit -C /srv/repo status"),
            ("/usr/local/bin/mygit -C /srv/repo status", None),
        )

    def test_returns_an_empty_part_unchanged(self):
        self.assertEqual(_common.strip_global_git_options(""), ("", None))


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

    def test_finds_the_noun_when_gh_is_called_by_absolute_path(self):
        self.assertEqual(
            _common.gh_dispatch(["gh", "label", "create", "bug"]), ["label", "create", "bug"]
        )
        self.assertEqual(
            _common.gh_dispatch(["/opt/homebrew/bin/gh", "label", "create", "bug"]),
            ["label", "create", "bug"],
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
