# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for iac_first.py."""

import os
import subprocess
import tempfile
import unittest

from helper import bash_payload, decision, run_hook


def git_repo(with_release_please: bool = False, with_release_me: bool = False) -> str:
    path = tempfile.mkdtemp(prefix="iac-first-")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, capture_output=True)
    if with_release_please:
        with open(
            os.path.join(path, "release-please-config.json"), "w", encoding="utf-8"
        ) as handle:
            handle.write("{}\n")
    if with_release_me:
        with open(os.path.join(path, "release-me.yaml"), "w", encoding="utf-8") as handle:
            handle.write("initial-version: 0.1.0\n")
    return path


class IacFirstTest(unittest.TestCase):
    def test_allows_reads(self):
        for command in [
            "gh repo view",
            "gh api repos/ostendorf-cloud/skills",
            "gh api -X GET repos/ostendorf-cloud/skills/labels",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_repository_and_org_writes(self):
        for command in [
            "gh repo edit --description 'new description'",
            "gh repo delete ostendorf-cloud/skills",
            "gh repo create ostendorf-cloud/new-repo",
            "gh label create bug --color ff0000",
            "gh label delete bug --yes",
            "gh secret set MY_SECRET --body value",
            "gh secret delete MY_SECRET",
            "gh variable set MY_VAR --body value",
            "gh variable delete MY_VAR",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_label_ruleset_secret_and_variable_reads(self):
        for command in [
            "gh label list",
            "gh ruleset view 1",
            "gh ruleset list",
            "gh secret list",
            "gh variable list",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_gh_api_writes_to_protected_paths(self):
        for command in [
            "gh api -X PATCH repos/ostendorf-cloud/skills",
            "gh api --method POST repos/ostendorf-cloud/skills/labels",
            "gh api -X PUT repos/ostendorf-cloud/skills/branches/main/protection",
            "gh api -X POST orgs/ostendorf-cloud",
            "gh api -X POST user/repos",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_gh_api_writes_to_pull_request_paths(self):
        for command in [
            "gh api -X PUT repos/ostendorf-cloud/skills/pulls/42/merge",
            "gh api --method POST repos/ostendorf-cloud/skills/pulls/42/reviews",
            "gh api -X PATCH repos/ostendorf-cloud/skills/pulls/42",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_gh_api_graphql_mutation(self):
        command = (
            "gh api graphql -f query='mutation { mergePullRequest(input: {}) { "
            "clientMutationId } }'"
        )
        self.assertEqual(decision(run_hook("iac_first.py", bash_payload(command))), "deny")

    def test_allows_gh_api_graphql_query(self):
        command = "gh api graphql -f query='query { viewer { login } }'"
        self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))))

    def test_denies_gh_repo_rename_and_set_default(self):
        for command in [
            "gh repo rename new-name",
            "gh repo set-default ostendorf-cloud/skills",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_gh_alias_and_extension_writes(self):
        for command in [
            "gh alias set co 'pr checkout'",
            "gh alias delete co",
            "gh extension install owner/gh-extension",
            "gh extension exec my-extension",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_alias_and_extension_reads(self):
        for command in ["gh alias list", "gh extension list"]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_allows_gh_api_delete_to_an_unprotected_path(self):
        self.assertIsNone(
            decision(
                run_hook(
                    "iac_first.py",
                    bash_payload("gh api -X DELETE repos/ostendorf-cloud/skills/issues/comments/1"),
                )
            )
        )

    def test_denies_gh_release_when_release_please_is_configured(self):
        repo = git_repo(with_release_please=True)
        for command in ["gh release create v1.0.0", "gh release edit v1.0.0"]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_gh_release_when_release_me_is_configured(self):
        repo = git_repo(with_release_me=True)
        for command in ["gh release create v1.0.0", "gh release edit v1.0.0"]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_gh_release_without_a_release_tool_configured(self):
        repo = git_repo(with_release_please=False, with_release_me=False)
        self.assertIsNone(
            decision(run_hook("iac_first.py", bash_payload("gh release create v1.0.0", repo)))
        )


if __name__ == "__main__":
    unittest.main()
