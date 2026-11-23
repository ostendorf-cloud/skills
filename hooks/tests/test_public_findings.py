# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for public_findings.py.

The repository visibility lookup is replaced by a fake executable named in
AGENT_SKILLS_VISIBILITY_CMD, so no test reaches the network.
"""

import json
import os
import subprocess
import tempfile
import unittest

from helper import NO_SCRATCH, bash_payload, decision, reason, run_hook, scratch_env

FAKE_LOOKUP = """#!/bin/sh
if [ -n "$FAKE_LOOKUP_LOG" ]; then
  echo "$1" >> "$FAKE_LOOKUP_LOG"
fi
case "$1" in
  acme/internal-tools) echo true ;;
  acme/flaky) exit 1 ;;
  acme/garbled) echo maybe ;;
  *) echo false ;;
esac
"""

PLAIN_TITLE = "resolve static analysis findings"


def make_repo(root: str, remote: str, config: object = None) -> str:
    """A throwaway git repository under root whose origin is remote."""
    path = tempfile.mkdtemp(prefix="repo-", dir=root)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "remote", "add", "origin", remote], check=True)
    if config is not None:
        with open(os.path.join(path, ".agent-skills.json"), "w", encoding="utf-8") as handle:
            json.dump(config, handle)
    return path


class PublicFindingsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="public-findings-")
        self.fake = os.path.join(self.root, "fake-visibility")
        with open(self.fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_LOOKUP)
        os.chmod(self.fake, 0o755)
        self.public = make_repo(self.root, "https://github.com/acme/widgets.git")
        self.private = make_repo(self.root, "git@github.com:acme/internal-tools.git")

    def env(self, **extra):
        env = scratch_env(NO_SCRATCH)
        env["AGENT_SKILLS_VISIBILITY_CMD"] = self.fake
        env.update(extra)
        return env

    def run_in(self, command, cwd=None, **extra):
        cwd = cwd or self.public
        return run_hook("public_findings.py", bash_payload(command, cwd), env=self.env(**extra))

    def assertDenied(self, command, cwd=None, **extra):
        output = self.run_in(command, cwd, **extra)
        self.assertEqual(decision(output), "deny", command)
        self.assertIn("draft security advisory", reason(output))

    def assertAllowed(self, command, cwd=None, **extra):
        self.assertIsNone(decision(self.run_in(command, cwd, **extra)), command)

    def test_denies_each_command_shape_in_a_public_repository(self):
        shapes = [
            "gh issue create --title 'Fix' --body 'CodeQL reported a problem'",
            "gh issue edit 12 --body 'This is a vulnerability in the parser'",
            "gh issue comment 12 --body 'confirmed, exploit works on main'",
            "gh pr create --title 'fix: harden parser' --body 'closes the XSS in the preview'",
            "gh pr edit 7 --title 'fix: sanitize the cursor'",
            "gh pr comment 7 --body 'see code scanning alert #14'",
            "gh pr review 7 --comment --body 'this is a path traversal'",
            "git commit -m 'fix: close SQL injection in search'",
        ]
        for command in shapes:
            with self.subTest(command=command):
                self.assertDenied(command)

    def test_denies_each_vocabulary_group(self):
        samples = {
            "cve": "Tracks CVE-2026-1234 in the base image",
            "codeql": "Reported by codeql on main",
            "code scanning": "Opened from the Code Scanning view",
            "alert": "Dismisses alert #14",
            "vulnerab": "A vulnerable dependency",
            "exploit": "Possible exploit of the parser",
            "injection": "Template injection in the renderer",
            "xss": "Stored xss in the comment field",
            "ssrf": "SSRF through the webhook url",
            "path traversal": "Path traversal in the upload handler",
            "sanitiz": "Unsanitized input reaches the shell",
            "ghsa": "Advisory GHSA-abcd-efgh-ijkl applies",
        }
        for name, text in samples.items():
            with self.subTest(group=name):
                self.assertDenied(f"gh issue comment 3 --body '{text}'")

    def test_denies_the_security_label(self):
        self.assertDenied("gh issue create --title 'Update parser' --body 'later' --label security")
        self.assertDenied("gh issue edit 4 --add-label bug,Security")
        self.assertDenied("gh issue create --title 'Update parser' --body 'later' -l security")

    def test_allows_plain_wording(self):
        self.assertAllowed(f"gh pr create --title 'fix: {PLAIN_TITLE}' --body 'see the checks'")
        self.assertAllowed("gh issue create --title 'Add valkey' --body 'new module' --label bug")
        self.assertAllowed(f"git commit -m 'fix: {PLAIN_TITLE}'")

    def test_allows_a_private_repository(self):
        text = "CodeQL alert #3 is a vulnerability"
        self.assertAllowed(f"gh issue comment 5 --body '{text}'", self.private)
        self.assertAllowed("git commit -m 'fix: close SQL injection'", self.private)

    def test_denies_when_the_visibility_is_unknown(self):
        flaky = make_repo(self.root, "https://github.com/acme/flaky.git")
        garbled = make_repo(self.root, "https://github.com/acme/garbled.git")
        for cwd in (flaky, garbled):
            with self.subTest(cwd=cwd):
                self.assertDenied("gh issue comment 5 --body 'a vulnerability'", cwd)

    def test_denies_when_the_lookup_command_is_missing(self):
        self.assertDenied(
            "gh issue comment 5 --body 'a vulnerability'",
            AGENT_SKILLS_VISIBILITY_CMD=os.path.join(self.root, "missing"),
        )

    def test_denies_when_the_repository_is_not_known(self):
        bare = tempfile.mkdtemp(prefix="bare-", dir=self.root)
        subprocess.run(["git", "init", "-q", bare], check=True)
        self.assertDenied("gh issue comment 5 --body 'a vulnerability'", bare)

    def test_repo_flag_selects_the_target_repository(self):
        self.assertAllowed(
            "gh issue comment 5 --repo acme/internal-tools --body 'a vulnerability'",
            self.public,
        )
        text = "gh issue comment 5 -R acme/widgets --body 'a vulnerability'"
        self.assertDenied(text, self.private)

    def test_allow_words_opts_out_only_for_listed_words(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": ["Injection", "xss"]}},
        )
        self.assertAllowed("gh issue create --title 'Detect injection and XSS' --body 'x'", repo)
        self.assertDenied("gh issue create --title 'Detect SSRF' --body 'x'", repo)
        self.assertDenied("gh issue create --title 'Detect injection' --body 'a CVE-2026-1'", repo)

    def test_allow_words_can_opt_out_of_the_security_label(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": ["security"]}},
        )
        self.assertAllowed("gh issue create --title 'Add feed' --body 'x' --label security", repo)

    def test_ignores_an_invalid_allow_words_value(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": "vulnerab"}},
        )
        self.assertDenied("gh issue comment 5 --body 'a vulnerability'", repo)

    def test_denies_a_commit_message_read_from_a_file(self):
        path = os.path.join(self.public, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fix: patch the parser\n\nCloses a path traversal.\n")
        self.assertDenied("git commit -F msg.txt")
        self.assertDenied(f"git commit --file {path}")

    def test_allows_a_plain_commit_message_file(self):
        path = os.path.join(self.public, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"fix: {PLAIN_TITLE}\n")
        self.assertAllowed("git commit -s -F msg.txt")

    def test_allows_a_message_file_that_does_not_exist(self):
        self.assertAllowed("git commit -F missing-message.txt")
        self.assertAllowed("gh issue comment 5 --body-file missing-body.md")

    def test_allows_a_message_file_outside_the_readable_scope(self):
        outside = tempfile.mkdtemp(prefix="outside-")
        path = os.path.join(outside, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fix: close a vulnerability\n")
        self.assertAllowed(f"git commit -F {path}")

    def test_denies_a_body_file_in_the_working_directory(self):
        path = os.path.join(self.public, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Reported by CodeQL.\n")
        self.assertDenied("gh pr comment 9 --body-file body.md")

    def test_denies_a_body_file_in_the_session_scratch_scope(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        path = os.path.join(scratch, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Reported by CodeQL.\n")
        output = run_hook(
            "public_findings.py",
            bash_payload(f"gh pr comment 9 --body-file {path}", self.public),
            env=self.env(TMPDIR=scratch),
        )
        self.assertEqual(decision(output), "deny")

    def test_denies_a_piped_body_through_stdin(self):
        self.assertDenied("printf 'a vulnerability in the parser' | gh pr comment 9 --body-file -")

    def test_skips_a_commit_in_a_fixture_under_the_session_scratch_scope(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        fixture = make_repo(scratch, "https://github.com/acme/widgets.git")
        output = run_hook(
            "public_findings.py",
            bash_payload("git commit -m 'fix: close SQL injection'", fixture),
            env=self.env(TMPDIR=scratch),
        )
        self.assertIsNone(decision(output))

    def test_denies_gh_api_post_to_an_issue_comment(self):
        self.assertDenied(
            "gh api repos/acme/widgets/issues/12/comments -f body='a path traversal in upload'"
        )
        self.assertDenied(
            "gh api --method POST repos/acme/widgets/issues -f title='Fix' -f body='CVE-2026-9'"
        )
        self.assertDenied("gh api -X PATCH repos/acme/widgets/pulls/3 -f body='exploit details'")
        self.assertDenied("gh api repos/acme/widgets/issues -f title='Fix' -f 'labels[]=security'")

    def test_gh_api_target_repository_comes_from_the_endpoint(self):
        self.assertAllowed(
            "gh api repos/acme/internal-tools/issues/2/comments -f body='a vulnerability'"
        )

    def test_allows_gh_api_reads_and_other_endpoints(self):
        self.assertAllowed("gh api repos/acme/widgets/issues/12/comments")
        self.assertAllowed("gh api -X GET repos/acme/widgets/issues -f body='a vulnerability'")
        self.assertAllowed("gh api repos/acme/widgets/topics -X PUT -f body='a vulnerability'")

    def test_wrapper_prefixes_do_not_hide_the_write(self):
        for prefix in ("sudo ", "env GH_TOKEN=x ", "mise exec -- ", "/usr/local/bin/"):
            with self.subTest(prefix=prefix):
                self.assertDenied(f"{prefix}gh issue comment 5 --body 'a vulnerability'")

    def test_a_quoted_semicolon_does_not_split_the_body(self):
        self.assertDenied("gh issue comment 5 --body 'first; then a vulnerability && more'")
        self.assertAllowed("gh issue comment 5 --body 'first; second && third | fourth'")

    def test_any_part_of_a_chain_can_deny(self):
        self.assertDenied("git add . && git commit -m 'fix: close SQL injection'")

    def test_commit_without_a_message_source_is_allowed(self):
        self.assertAllowed("git commit --amend --no-edit")

    def test_other_commands_are_allowed(self):
        self.assertAllowed("ls -la")
        self.assertAllowed("gh issue list --search vulnerability")
        self.assertAllowed("gh pr view 7")

    def test_the_lookup_runs_once_per_repository_and_session(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        log = os.path.join(self.root, "lookups.log")
        command = "gh issue comment 5 --body 'a vulnerability'"
        for _ in range(2):
            output = run_hook(
                "public_findings.py",
                bash_payload(command, self.public),
                env=self.env(TMPDIR=scratch, FAKE_LOOKUP_LOG=log),
            )
            self.assertEqual(decision(output), "deny")
        with open(log, encoding="utf-8") as handle:
            self.assertEqual(handle.read().split(), ["acme/widgets"])

    def test_plain_wording_never_asks_for_the_visibility(self):
        log = os.path.join(self.root, "lookups.log")
        self.assertAllowed(f"gh issue comment 5 --body '{PLAIN_TITLE}'", FAKE_LOOKUP_LOG=log)
        self.assertFalse(os.path.exists(log))

    def test_a_private_answer_is_cached_for_the_session(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        log = os.path.join(self.root, "lookups.log")
        for _ in range(2):
            output = run_hook(
                "public_findings.py",
                bash_payload("gh issue comment 5 --body 'a vulnerability'", self.private),
                env=self.env(TMPDIR=scratch, FAKE_LOOKUP_LOG=log),
            )
            self.assertIsNone(decision(output))
        with open(log, encoding="utf-8") as handle:
            self.assertEqual(len(handle.read().split()), 1)

    def test_unparseable_input_prints_an_empty_response(self):
        self.assertEqual(run_hook("public_findings.py", {"tool_input": "not a dict"}), {})
        self.assertEqual(run_hook("public_findings.py", {}), {})
        self.assertAllowed("gh issue comment 5 --body 'unterminated vulnerability")


if __name__ == "__main__":
    unittest.main()
