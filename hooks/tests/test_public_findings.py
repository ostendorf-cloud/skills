# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for public_findings.py.

The repository visibility lookup is replaced by a fake executable named in
AGENT_SKILLS_VISIBILITY_CMD, so no test reaches the network.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helper import HOOKS_DIR, NO_SCRATCH, bash_payload, decision, reason, run_hook, scratch_env

sys.path.insert(0, HOOKS_DIR)
import public_findings  # noqa: E402

FAKE_LOOKUP = """#!/bin/sh
if [ -n "$FAKE_LOOKUP_LOG" ]; then
  echo "$1" >> "$FAKE_LOOKUP_LOG"
fi
case "$1" in
  acme/internal-tools) echo true ;;
  acme/flaky) echo "auth failed for the fake host" >&2; exit 1 ;;
  acme/garbled) echo maybe ;;
  *) echo false ;;
esac
"""

PLAIN_TITLE = "resolve static analysis findings"

ALLOWED_TEXTS = [
    "ci: add CodeQL workflow",
    "chore: add codeql.yaml",
    "refactor: use dependency injection",
    "feat(logging): sanitize tokens from log lines",
    "chore(deps): update trivy vulnerability database action",
    "ci: run exploit-db sync",
    "feat: no sanitization needed for ints",
    "feat: add an alert rule for disk usage",
    "docs: see the code scanning view",
    PLAIN_TITLE,
    "chore(deps): update dependency x to v2",
    "update trivy vulnerability database action",
    "docs: explain injection of the theme",
    "feat: security headers",
    "docs: security policy",
    "fix(security-review): wording",
    "lgtm, merge",
    "ci: upload CodeQL results as SARIF",
    "ci: upload code scanning results from trivy",
    "feat(alerting): alert 5xx rate above 1 percent",
    "fix(alertmanager): route alert 2 severity to pager",
    "feat: grafana alert 1 for latency",
    "feat(hooks): flag prompt injection in tool output",
    "docs: name prompt injection in the baseline",
    "feat(helm): add header injection of the tenant id",
    "fix(log): add log injection of request ids",
    "refactor(di): code injection via constructor",
    "release: v1.4.0 fixes the vulnerabilities in the base image",
    "chore(docker): bump alpine to reduce the vulnerabilities in the image",
    "chore: run trivy and record vulnerabilities found",
    "docs: explain how to report a security vulnerability",
    "feat: add cross-site cookie support",
    "feat: add redirect rules for the old docs url",
    "refactor: move the source resource into force mode",
    "docs: describe the remote code review process",
    "feat: add privilege dropping to the runner",
    "feat: walk the directory tree",
    "feat: add zip support",
    "docs: add xxl sizes",
    "feat: add deserialization of the config",
    "docs: explain the prototype pattern",
    "feat: add a sqlite driver",
    "feat: add auth middleware",
    "refactor: replace hardcoded paths",
    "docs: link the cweb page",
]

DENIED_TEXTS = {
    "cve": "Tracks CVE-2026-1234 in the base image",
    "ghsa": "Advisory GHSA-xxxx-xxxx-xxxx applies",
    "codeql": "Fixes CodeQL alert for the parser",
    "code scanning": "Closes a code scanning alert",
    "alert": "Dismisses alert #14",
    "vulnerab": "A vulnerability in the upload handler",
    "exploit": "Possible exploit of the parser",
    "injection": "SQL injection in the search",
    "xss": "Stored XSS in the comment field",
    "ssrf": "SSRF through the webhook url",
    "path traversal": "Path traversal in the upload handler",
    "sanitiz": "Unsanitized input reaches the shell",
    "csrf": "Missing CSRF check on the form",
    "open redirect": "Open redirect in the login page",
    "rce": "RCE in the upload handler",
    "privilege escalation": "Privilege escalation through the sudo rule",
    "zip slip": "Zip slip in the archive reader",
    "xxe": "XXE in the xml parser",
    "deserialization": "Insecure deserialization of the session",
    "prototype pollution": "Prototype pollution in merge",
    "auth bypass": "Auth bypass on the admin route",
    "hardcoded credentials": "Hardcoded credentials in the script",
    "cwe": "Maps to CWE-79",
}

MORE_DENIED_TEXTS = [
    "CodeQL alert #5",
    "dependabot alert for lodash",
    "secret scanning alert in the repo",
    "command injection in the runner",
    "shell injection in the runner",
    "SQLi in the search",
    "cross-site scripting in the preview",
    "Cross Site Scripting in the preview",
    "remote code execution on upload",
    "arbitrary code execution on upload",
    "directory traversal in the upload handler",
    "zip-slip in the unpacker",
    "authentication bypass on login",
    "it bypasses authentication",
    "hard-coded password in the repo",
    "the service is vulnerable to replay",
    "this parser is vulnerable",
    "the vulnerability of the parser",
    "a vulnerability in the login handler",
    "the parser is vulnerable to SQL injection",
    "it is exploitable",
    "exploits for the parser",
    "incomplete sanitization of paths",
    "bad code sanitization",
    "missing sanitisation",
    "the parser lacks sanitization",
    "the exploitation of the cache",
    "exploits",
    "an un-sanitized value",
]


def make_repo(root: str, remote: str, config: object = None) -> str:
    """A throwaway git repository under root whose origin is remote."""
    path = tempfile.mkdtemp(prefix="repo-", dir=root)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "remote", "add", "origin", remote], check=True)
    if config is not None:
        with open(os.path.join(path, ".agent-skills.json"), "w", encoding="utf-8") as handle:
            json.dump(config, handle)
    return path


def comment(text: str) -> str:
    return f"gh issue comment 5 --body {shlex.quote(text)}"


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

    def run_in(self, command, cwd=None, session=None, **extra):
        payload = bash_payload(command, cwd or self.public)
        if session is not None:
            payload["session_id"] = session
        return run_hook("public_findings.py", payload, env=self.env(**extra))

    def assert_denied(self, command, cwd=None, **extra):
        output = self.run_in(command, cwd, **extra)
        self.assertEqual(decision(output), "deny", command)
        self.assertIn("draft security advisory", reason(output))
        return reason(output)

    def assert_unknown(self, command, cwd=None, **extra):
        output = self.run_in(command, cwd, **extra)
        self.assertEqual(decision(output), "deny", command)
        self.assertIn("could not be read", reason(output))
        return reason(output)

    def assert_allowed(self, command, cwd=None, **extra):
        self.assertIsNone(decision(self.run_in(command, cwd, **extra)), command)

    def test_denies_each_command_shape_in_a_public_repository(self):
        shapes = [
            "gh issue create --title 'Fix' --body 'CodeQL alert #4 on main'",
            "gh issue edit 12 --body 'This is a vulnerability in the parser'",
            "gh issue comment 12 --body 'confirmed, exploit works on main'",
            "gh pr create --title 'fix: harden parser' --body 'closes the XSS in the preview'",
            "gh pr edit 7 --title 'fix: unsanitized cursor'",
            "gh pr comment 7 --body 'see code scanning alert #14'",
            "gh pr review 7 --comment --body 'this is a path traversal'",
            "git commit -m 'fix: close SQL injection in search'",
        ]
        for command in shapes:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_denies_each_vocabulary_group(self):
        for name, text in DENIED_TEXTS.items():
            with self.subTest(group=name):
                self.assertIn(name, self.assert_denied(comment(text)))

    def test_denies_the_finding_shapes(self):
        for text in MORE_DENIED_TEXTS:
            with self.subTest(text=text):
                self.assert_denied(comment(text))

    def test_allows_normal_work_that_uses_a_vocabulary_word(self):
        for text in ALLOWED_TEXTS:
            with self.subTest(text=text):
                self.assert_allowed(comment(text))
                self.assert_allowed(f"git commit -m {shlex.quote(text)}")
                self.assert_allowed(f"gh pr create --title {shlex.quote(text)} --body 'x'")

    def test_denies_the_security_label(self):
        self.assert_denied("gh issue create --title 'Update' --body 'later' --label security")
        self.assert_denied("gh issue edit 4 --add-label bug,Security")
        self.assert_denied("gh issue create --title 'Update parser' --body 'later' -l security")

    def test_denies_creating_the_security_label(self):
        self.assert_denied("gh label create security --color ff0000 --description 'Findings'")
        self.assert_denied("gh label edit security --name security")
        self.assert_allowed("gh label create bug --color ff0000")

    def test_allows_pr_create_with_fill(self):
        self.assert_allowed("gh pr create --fill")

    def test_the_deny_names_the_matched_words_and_the_opt_out(self):
        text = self.assert_denied(comment("CVE-2026-1234 and CodeQL alert #5 details"))
        self.assertIn("cve", text)
        self.assertIn("codeql", text)
        self.assertNotIn("details", text)
        self.assertIn("publicFindings.allowWords", text)

    def test_allows_a_private_repository(self):
        text = "CodeQL alert #3 is a vulnerability in the parser"
        self.assert_allowed(comment(text), self.private)
        self.assert_allowed("git commit -m 'fix: close SQL injection'", self.private)

    def test_reports_the_reason_when_the_visibility_cannot_be_read(self):
        flaky = make_repo(self.root, "https://github.com/acme/flaky.git")
        garbled = make_repo(self.root, "https://github.com/acme/garbled.git")
        text = comment("a vulnerability in the parser")
        self.assertIn("auth failed for the fake host", self.assert_unknown(text, flaky))
        self.assertIn("acme/flaky", self.assert_unknown(text, flaky))
        self.assertIn("unexpected answer", self.assert_unknown(text, garbled))

    def test_denies_when_the_lookup_command_is_missing(self):
        text = self.assert_unknown(
            comment("a vulnerability in the parser"),
            AGENT_SKILLS_VISIBILITY_CMD=os.path.join(self.root, "missing"),
        )
        self.assertIn("FileNotFoundError", text)

    def test_denies_when_the_repository_is_not_known(self):
        other = tempfile.mkdtemp(prefix="other-", dir=self.root)
        subprocess.run(["git", "init", "-q", other], check=True)
        subprocess.run(
            ["git", "-C", other, "remote", "add", "upstream", "https://github.com/acme/x.git"],
            check=True,
        )
        self.assert_unknown(comment("a vulnerability in the parser"), other)
        self.assert_unknown("git commit -m 'fix: close SQL injection'", other)

    def test_the_unknown_deny_names_the_advisory_and_the_opt_out(self):
        flaky = make_repo(self.root, "https://github.com/acme/flaky.git")
        output = self.run_in(comment("a vulnerability in the parser"), flaky)
        self.assertEqual(decision(output), "deny")
        self.assertIn("could not be read", reason(output))
        self.assertIn("draft security advisory", reason(output))
        self.assertIn("publicFindings.allowWords", reason(output))

    def test_allows_a_repository_whose_remotes_are_not_network_urls(self):
        for remote in ("/srv/git/bar.git", "file:///srv/git/bar.git", "../bar"):
            with self.subTest(remote=remote):
                repo = make_repo(self.root, remote)
                self.assertEqual(public_findings.slug_from_remote(repo), "")
                self.assert_allowed("git commit -m 'fix: close SQL injection'", repo)

    def test_a_scp_style_remote_still_gives_a_slug(self):
        repo = make_repo(self.root, "git@github.com:acme/widgets.git")
        self.assertEqual(public_findings.slug_from_remote(repo), "acme/widgets")
        self.assertEqual(
            public_findings.slug_from_remote(make_repo(self.root, "ssh://git@github.com/a/b")),
            "a/b",
        )

    def test_allows_a_commit_in_a_repository_without_any_remote(self):
        bare = tempfile.mkdtemp(prefix="bare-", dir=self.root)
        subprocess.run(["git", "init", "-q", bare], check=True)
        self.assert_allowed("git commit -m 'fix: close SQL injection'", bare)
        self.assert_allowed("git tag -a v1 -m 'fix: close SQL injection'", bare)

    def test_the_unknown_deny_says_retry_only_for_a_lookup_failure(self):
        text = "a vulnerability in the parser"
        flaky = make_repo(self.root, "https://github.com/acme/flaky.git")
        self.assertIn("Retry", self.assert_unknown(comment(text), flaky))
        invalid = f"gh issue comment 5 -R 'acme/web;rm' --body {shlex.quote(text)}"
        message = self.assert_unknown(invalid)
        self.assertIn("fix the repository argument", message)
        self.assertNotIn("Retry", message)

    def test_denies_a_tag_message_like_a_commit_message(self):
        for command in (
            "git tag -a v1.2.0 -m 'fix: close SQL injection'",
            "git tag -am 'fix: close SQL injection' v1.2.0",
            "git tag v1.2.0 --message='fix: close SQL injection'",
        ):
            with self.subTest(command=command):
                self.assert_denied(command)
        self.assert_allowed(f"git tag -a v1.2.0 -m '{PLAIN_TITLE}'")
        self.assert_allowed("git tag v1.2.0")
        self.assert_allowed("git tag -l 'SQL injection*'")

    def test_denies_creating_the_security_label_through_the_rest_api(self):
        for flag in ("-f", "--field", "-F", "--raw-field"):
            with self.subTest(flag=flag):
                self.assert_denied(f"gh api repos/acme/widgets/labels {flag} name=security")
        self.assert_denied("gh api repos/acme/widgets/labels -f name=bug -f description='XSS'")
        self.assert_allowed("gh api repos/acme/widgets/labels -f name=bug -f color=ff0000")
        self.assert_allowed("gh api repos/acme/widgets/labels")

    def test_denies_the_remaining_graphql_mutations(self):
        for mutation in (
            "updateIssueComment",
            "updatePullRequestReviewComment",
            "addDiscussionComment",
            "createDiscussion",
        ):
            with self.subTest(mutation=mutation):
                query = "mutation { " + mutation + '(input: {body: "SQL injection"}) { id } }'
                self.assert_denied(f"gh api graphql -f query={shlex.quote(query)}")

    def test_this_repository_config_allows_its_own_subject_only_here(self):
        path = os.path.join(HOOKS_DIR, "..", ".agent-skills.json")
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
        repo = make_repo(self.root, "https://github.com/acme/skills.git", config)
        texts = [
            "docs(security-review): add SSRF and path traversal checks",
            "test(hooks): cover XSS and SSRF in the public findings hook",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assert_allowed(f"git commit -m {shlex.quote(text)}", repo)
                self.assert_denied(f"git commit -m {shlex.quote(text)}", self.public)
                self.assert_denied(
                    f"gh issue comment 5 -R acme/other --body {shlex.quote(text)}", repo
                )
        self.assert_denied("git commit -m 'fix: CVE-2026-1234'", repo)

    def test_repo_flag_selects_the_target_repository(self):
        text = "a vulnerability in the parser"
        self.assert_allowed(
            f"gh issue comment 5 --repo acme/internal-tools --body {shlex.quote(text)}"
        )
        other = f"gh issue comment 5 -R acme/widgets --body {shlex.quote(text)}"
        self.assert_denied(other, self.private)

    def test_a_repo_flag_that_is_not_owner_and_name_is_unknown(self):
        log = os.path.join(self.root, "lookups.log")
        for flag in ("-R '../etc/passwd'", "-R '--json'", "-R host.example/acme/widgets"):
            with self.subTest(flag=flag):
                self.assert_unknown(
                    f"gh issue comment 5 {flag} --body 'a vulnerability in the parser'",
                    FAKE_LOOKUP_LOG=log,
                )
        self.assertFalse(os.path.exists(log))

    def test_allow_words_opts_out_only_for_listed_words(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": ["Injection", "xss"]}},
        )
        title = "Detect SQL injection and XSS"
        self.assert_allowed(f"gh issue create --title '{title}' --body 'x'", repo)
        self.assert_denied("gh issue create --title 'Detect SSRF' --body 'x'", repo)
        self.assert_denied("gh issue create --title 'SQL injection' --body 'a CVE-2026-1'", repo)

    def test_allow_words_apply_only_to_the_repository_of_the_working_directory(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": ["injection"]}},
        )
        allowed = "gh issue create --title 'Detect SQL injection' --body 'x'"
        self.assert_allowed(allowed, repo)
        self.assert_allowed(allowed + " -R ACME/Scanner", repo)
        self.assert_denied(allowed + " -R acme/other", repo)

    def test_allow_words_can_opt_out_of_the_security_label(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": ["security"]}},
        )
        self.assert_allowed("gh issue create --title 'Add feed' --body 'x' --label security", repo)

    def test_ignores_an_invalid_allow_words_value(self):
        repo = make_repo(
            self.root,
            "https://github.com/acme/scanner.git",
            {"publicFindings": {"allowWords": "vulnerab"}},
        )
        self.assert_denied(comment("a vulnerability in the parser"), repo)

    def test_denies_a_commit_message_read_from_a_file(self):
        path = os.path.join(self.public, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fix: patch the parser\n\nCloses a path traversal.\n")
        self.assert_denied("git commit -F msg.txt")
        self.assert_denied(f"git commit --file {path}")
        self.assert_denied(f"git commit -sF {path}")

    def test_allows_a_plain_commit_message_file(self):
        path = os.path.join(self.public, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"fix: {PLAIN_TITLE}\n")
        self.assert_allowed("git commit -s -F msg.txt")

    def test_allows_a_message_file_that_does_not_exist(self):
        self.assert_allowed("git commit -F missing-message.txt")
        self.assert_allowed("gh issue comment 5 --body-file missing-body.md")

    def test_allows_a_message_file_outside_the_readable_scope(self):
        outside = tempfile.mkdtemp(prefix="outside-")
        path = os.path.join(outside, "msg.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("fix: close SQL injection\n")
        self.assert_allowed(f"git commit -F {path}")

    def test_denies_a_body_file_in_the_working_directory(self):
        path = os.path.join(self.public, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Reported by a CodeQL alert #4.\n")
        self.assert_denied("gh pr comment 9 --body-file body.md")

    def test_denies_a_body_file_in_the_session_scratch_scope(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        path = os.path.join(scratch, "body.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Reported by a CodeQL alert #4.\n")
        output = run_hook(
            "public_findings.py",
            bash_payload(f"gh pr comment 9 --body-file {path}", self.public),
            env=self.env(TMPDIR=scratch),
        )
        self.assertEqual(decision(output), "deny")

    def test_denies_a_piped_body_through_stdin(self):
        self.assert_denied("printf 'a vulnerability in the parser' | gh pr comment 9 --body-file -")

    def test_denies_a_commit_message_from_a_stdin_heredoc(self):
        command = "git commit -F - <<'EOF'\nfix: close SQL injection\nEOF"
        self.assert_denied(command)

    def test_skips_a_commit_in_a_fixture_under_the_session_scratch_scope(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        fixture = make_repo(scratch, "https://github.com/acme/widgets.git")
        output = run_hook(
            "public_findings.py",
            bash_payload("git commit -m 'fix: close SQL injection'", fixture),
            env=self.env(TMPDIR=scratch),
        )
        self.assertIsNone(decision(output))

    def test_denies_commit_flag_shapes(self):
        message = "'fix: close SQL injection'"
        commands = [
            f"git commit -am {message}",
            f"git commit -a -m {message}",
            f"git commit --amend -m {message}",
            f"git commit -sm {message}",
            f"git commit --message={message}",
            f"git commit --message {message}",
            "git commit -m'fix: close SQL injection'",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_allows_commit_flag_shapes_with_plain_wording(self):
        self.assert_allowed(f"git commit -am 'fix: {PLAIN_TITLE}'")
        self.assert_allowed("git commit --amend --no-edit")
        self.assert_allowed("git commit -a")

    def test_a_relative_git_c_path_is_read_against_the_payload_directory(self):
        name = os.path.basename(self.private)
        command = f"git -C ../{name} commit -m 'fix: close SQL injection'"
        self.assert_allowed(command, self.public)
        name = os.path.basename(self.public)
        self.assert_denied(f"git -C ../{name} commit -m 'fix: close SQL injection'", self.private)

    def test_denies_gh_api_post_to_an_issue_comment(self):
        self.assert_denied(
            "gh api repos/acme/widgets/issues/12/comments -f body='a path traversal in upload'"
        )
        self.assert_denied(
            "gh api --method POST repos/acme/widgets/issues -f title='Fix' -f body='CVE-2026-9'"
        )
        self.assert_denied("gh api -X PATCH repos/acme/widgets/pulls/3 -f body='exploit details'")
        self.assert_denied("gh api repos/acme/widgets/issues -f title='Fix' -f 'labels[]=security'")

    def test_gh_api_target_repository_comes_from_the_endpoint(self):
        self.assert_allowed(
            "gh api repos/acme/internal-tools/issues/2/comments -f body='SQL injection'"
        )

    def test_gh_api_placeholders_stand_for_the_origin_remote(self):
        body = "-f body='SQL injection in the parser'"
        endpoint = "repos/{owner}/{repo}/issues/2/comments"
        self.assert_denied(f"gh api {endpoint} {body}", self.public)
        self.assert_allowed(f"gh api {endpoint} {body}", self.private)

    def test_denies_graphql_mutations_that_write_text(self):
        for mutation in (
            "addComment",
            "createIssue",
            "updateIssue",
            "addPullRequestReview",
            "addPullRequestReviewComment",
            "updatePullRequest",
            "createPullRequest",
        ):
            with self.subTest(mutation=mutation):
                query = "mutation { " + mutation + '(input: {body: "SQL injection"}) { id } }'
                self.assert_denied(f"gh api graphql -f query={shlex.quote(query)}")
        self.assert_denied(
            "gh api graphql -f query='mutation($b: String!) { addComment(input: {body: $b}) "
            "{ clientMutationId } }' -f b='a CodeQL alert #5'"
        )

    def test_allows_graphql_reads_and_plain_mutations(self):
        self.assert_allowed("gh api graphql -f query='query { viewer { login } }'")
        query = 'mutation { addComment(input: {body: "resolve static analysis findings"}) { id } }'
        self.assert_allowed(f"gh api graphql -f query={shlex.quote(query)}")
        other = 'mutation { addStar(input: {starrableId: "x"}) { clientMutationId } }'
        self.assert_allowed(f"gh api graphql -f query={shlex.quote(other)} -f note='SQL injection'")

    def test_allows_gh_api_reads_and_other_endpoints(self):
        self.assert_allowed("gh api repos/acme/widgets/issues/12/comments")
        self.assert_allowed("gh api -X GET repos/acme/widgets/issues -f body='SQL injection'")
        self.assert_allowed("gh api repos/acme/widgets/topics -X PUT -f body='SQL injection'")

    def test_wrapper_prefixes_do_not_hide_the_write(self):
        for prefix in ("sudo ", "env GH_TOKEN=x ", "mise exec -- ", "/usr/local/bin/"):
            with self.subTest(prefix=prefix):
                self.assert_denied(f"{prefix}gh issue comment 5 --body 'SQL injection'")

    def test_a_quoted_semicolon_does_not_split_the_body(self):
        self.assert_denied("gh issue comment 5 --body 'first; then SQL injection && more'")
        self.assert_allowed("gh issue comment 5 --body 'first; second && third | fourth'")

    def test_any_part_of_a_chain_can_deny(self):
        self.assert_denied("git add . && git commit -m 'fix: close SQL injection'")

    def test_other_commands_are_allowed(self):
        self.assert_allowed("ls -la")
        self.assert_allowed("gh issue list --search vulnerability")
        self.assert_allowed("gh pr view 7")

    def test_plain_wording_never_asks_for_the_visibility(self):
        log = os.path.join(self.root, "lookups.log")
        self.assert_allowed(f"gh issue comment 5 --body '{PLAIN_TITLE}'", FAKE_LOOKUP_LOG=log)
        self.assertFalse(os.path.exists(log))

    def test_the_lookup_runs_once_per_repository_and_session(self):
        scratch = tempfile.mkdtemp(prefix="scratch-")
        log = os.path.join(self.root, "lookups.log")
        for _ in range(2):
            output = self.run_in(
                comment("SQL injection"), session="s1", TMPDIR=scratch, FAKE_LOOKUP_LOG=log
            )
            self.assertEqual(decision(output), "deny")
        self.run_in(comment("SQL injection"), session="s2", TMPDIR=scratch, FAKE_LOOKUP_LOG=log)
        with open(log, encoding="utf-8") as handle:
            self.assertEqual(handle.read().split(), ["acme/widgets", "acme/widgets"])

    def test_unparseable_input_prints_an_empty_response(self):
        self.assertEqual(run_hook("public_findings.py", {"tool_input": "not a dict"}), {})
        self.assertEqual(run_hook("public_findings.py", {}), {})
        self.assert_allowed("gh issue comment 5 --body 'unterminated SQL injection")


class VisibilityCacheTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="visibility-cache-")
        self.fake = os.path.join(self.root, "fake-visibility")
        self.log = os.path.join(self.root, "lookups.log")
        with open(self.fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_LOOKUP)
        os.chmod(self.fake, 0o755)
        patcher = mock.patch.dict(
            os.environ,
            {
                "TMPDIR": self.root,
                "AGENT_SKILLS_VISIBILITY_CMD": self.fake,
                "FAKE_LOOKUP_LOG": self.log,
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = [1000.0]
        clock = mock.patch.object(public_findings.time, "time", side_effect=lambda: self.clock[0])
        clock.start()
        self.addCleanup(clock.stop)

    def lookups(self):
        if not os.path.exists(self.log):
            return 0
        with open(self.log, encoding="utf-8") as handle:
            return len(handle.read().split())

    def test_a_public_answer_is_kept_for_an_hour(self):
        self.assertEqual(public_findings.visibility("acme/widgets", "s")[0], False)
        self.clock[0] += 3599
        public_findings.visibility("acme/widgets", "s")
        self.assertEqual(self.lookups(), 1)
        self.clock[0] += 2
        public_findings.visibility("acme/widgets", "s")
        self.assertEqual(self.lookups(), 2)

    def test_a_private_answer_is_kept_for_ten_minutes_only(self):
        self.assertEqual(public_findings.visibility("acme/internal-tools", "s")[0], True)
        self.clock[0] += 599
        public_findings.visibility("acme/internal-tools", "s")
        self.assertEqual(self.lookups(), 1)
        self.clock[0] += 2
        public_findings.visibility("acme/internal-tools", "s")
        self.assertEqual(self.lookups(), 2)

    def test_a_failure_is_kept_for_a_minute_only(self):
        private, error = public_findings.visibility("acme/flaky", "s")
        self.assertIsNone(private)
        self.assertIn("auth failed", error)
        self.clock[0] += 59
        self.assertEqual(public_findings.visibility("acme/flaky", "s"), (None, error))
        self.assertEqual(self.lookups(), 1)
        self.clock[0] += 2
        public_findings.visibility("acme/flaky", "s")
        self.assertEqual(self.lookups(), 2)

    def test_the_session_is_part_of_the_key(self):
        public_findings.visibility("acme/widgets", "one")
        public_findings.visibility("acme/widgets", "two")
        self.assertEqual(self.lookups(), 2)

    def test_an_odd_cache_file_counts_as_a_miss(self):
        path = public_findings.cache_path()
        key = public_findings.cache_key("s", "acme/widgets")
        odd_entries = [
            "text",
            {"at": "now", "private": False},
            {"at": True, "private": False},
            {"at": 2000.0, "private": False},
            {"at": 1000.0, "private": "yes"},
            {"at": 1000.0, "private": False, "error": 5},
        ]
        for entry in odd_entries:
            with self.subTest(entry=entry):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({key: entry}, handle)
                before = self.lookups()
                public_findings.visibility("acme/widgets", "s")
                self.assertEqual(self.lookups(), before + 1)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json {")
        before = self.lookups()
        public_findings.visibility("acme/widgets", "s")
        self.assertEqual(self.lookups(), before + 1)


if __name__ == "__main__":
    unittest.main()
