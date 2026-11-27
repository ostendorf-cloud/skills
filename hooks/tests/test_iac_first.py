# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for iac_first.py."""

import os
import subprocess
import tempfile
import unittest

from helper import bash_payload, decision, reason, run_hook


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

    def test_refusal_names_the_github_module_and_an_issue(self):
        for command in [
            "gh repo create ostendorf-cloud/new-repo --private",
            "gh label clone ostendorf-cloud/skills",
            "gh repo create --help",
        ]:
            output = run_hook("iac_first.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)
            self.assertIn("issue in the infrastructure repository", reason(output), command)
            self.assertIn("github module", reason(output), command)

    def test_allows_label_ruleset_secret_and_variable_reads(self):
        for command in [
            "gh label list",
            "gh ruleset view 1",
            "gh ruleset list",
            "gh secret list",
            "gh variable list",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_a_label_mutation_called_by_absolute_path(self):
        for command in [
            "gh label create bug --color ff0000",
            "/opt/homebrew/bin/gh label create bug --color ff0000",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_label_mutation_whose_command_name_is_quoted(self):
        for command in [
            "'gh' label create bug --color ff0000",
            '"gh" label create bug --color ff0000',
            "'/opt/homebrew/bin/gh' label create bug --color ff0000",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_gh_label_mutation_with_flag_before_subcommand(self):
        for command in [
            "gh label -R owner/repo create bug",
            "gh label --repo=owner/repo delete bug --yes",
            "gh label --color ff0000 create bug",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_label_list_with_flag_before_subcommand(self):
        self.assertIsNone(
            decision(run_hook("iac_first.py", bash_payload("gh label -R owner/repo list")))
        )

    def test_denies_gh_mutation_with_flag_before_subcommand(self):
        for command in [
            "gh repo --description 'new description' edit ostendorf-cloud/skills",
            "gh repo --visibility=private edit ostendorf-cloud/skills",
            "gh secret -R ostendorf-cloud/skills set MY_SECRET --body value",
            "gh secret --repo=ostendorf-cloud/skills delete MY_SECRET",
            "gh variable -R ostendorf-cloud/skills set MY_VAR --body value",
            "gh variable --repo=ostendorf-cloud/skills delete MY_VAR",
            "gh alias --clobber=true set co 'pr checkout'",
            "gh extension --pin v1.0.0 install owner/gh-extension",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_reads_with_flag_before_subcommand(self):
        for command in [
            "gh repo --branch main view ostendorf-cloud/skills",
            "gh secret -R ostendorf-cloud/skills list",
            "gh variable --repo=ostendorf-cloud/skills list",
            "gh extension --force=true list",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_gh_mutation_with_flag_before_the_noun(self):
        for command in [
            "gh --repo owner/repo secret set TOKEN value",
            "gh --repo=owner/repo variable set MY_VAR --body value",
            "gh --color ff0000 label create bug",
            "gh --description x repo edit ostendorf-cloud/skills",
            "gh --clobber=true alias set co 'pr checkout'",
            "gh --pin v1.0.0 extension install owner/gh-extension",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_reads_with_flag_before_the_noun(self):
        for command in [
            "gh --repo owner/repo secret list",
            "gh --repo=owner/repo variable list",
            "gh --branch main repo view ostendorf-cloud/skills",
            "gh --color ff0000 label list",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_gh_release_with_flag_before_the_noun(self):
        repo = git_repo(with_release_me=True)
        for command in [
            "gh --notes x release create v1.0.0",
            "gh --repo=ostendorf-cloud/skills release edit v1.0.0",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_gh_release_list_with_flag_before_the_noun(self):
        repo = git_repo(with_release_me=True)
        self.assertIsNone(
            decision(
                run_hook("iac_first.py", bash_payload("gh --limit 2 release list", repo)),
            )
        )

    def test_denies_gh_api_writes_with_flag_before_api(self):
        for command in [
            "gh --method PATCH api repos/ostendorf-cloud/skills/rulesets/1",
            "gh --method=PATCH api repos/ostendorf-cloud/skills/rulesets/1",
            "gh --hostname github.com api -X POST orgs/ostendorf-cloud",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_api_reads_with_flag_before_api(self):
        for command in [
            "gh --method GET api rate_limit",
            "gh --hostname github.com api repos/ostendorf-cloud/skills",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_gh_api_graphql_mutation_with_flag_before_api(self):
        for command in [
            "gh --field query=mutation api graphql",
            (
                "gh --hostname github.com api graphql -f query='mutation { "
                "mergePullRequest(input: {}) { clientMutationId } }'"
            ),
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_gh_api_graphql_query_with_flag_before_api(self):
        command = "gh --hostname github.com api graphql -f query='query { viewer { login } }'"
        self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))))

    def test_denies_a_gh_part_whose_quoting_does_not_parse(self):
        command = 'gh repo edit ostendorf-cloud/skills --description "unclosed'
        self.assertEqual(decision(run_hook("iac_first.py", bash_payload(command))), "deny")

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
            "gh api -X PATCH repos/ostendorf-cloud/skills/pulls/42",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/merge",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/comments",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/requested_reviewers",
            "gh api -X PUT repos/ostendorf-cloud/skills/pulls/42/reviews",
            "gh api -X DELETE repos/ostendorf-cloud/skills/pulls/42/reviews",
            "gh api -X PUT repos/ostendorf-cloud/skills/pulls/42/reviews/7/dismissals",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/reviews/7/events",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/reviews/7",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/reviews/",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/reviews?x=1",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/x/reviews",
            "gh api -X POST repos/ostendorf-cloud/skills/pulls/42/reviews/../merge",
            "sudo gh api -X POST repos/ostendorf-cloud/skills/pulls/42/merge",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_allows_posting_a_review_through_the_api(self):
        for command in [
            "gh api --method POST repos/ostendorf-cloud/skills/pulls/42/reviews",
            "gh api -X POST /repos/ostendorf-cloud/skills/pulls/42/reviews",
            "gh api repos/o/r/pulls/7/reviews --method POST -f event=COMMENT -f body=ok",
            "gh api -X POST repos/o/r/pulls/7/reviews --input review.json",
            "mise exec -- gh api -X POST repos/o/r/pulls/7/reviews -f event=APPROVE",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_allows_resolving_a_review_thread(self):
        for command in [
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "PRRT_x"}) { thread { isResolved } } }\'',
            "gh api graphql -f query='mutation($id: ID!) { resolveReviewThread(input: "
            "{threadId: $id}) { thread { isResolved } } }' -f id=PRRT_x",
            "gh api graphql -F query='mutation Resolve { r: resolveReviewThread(input: "
            '{threadId: "PRRT_x"}) { thread { id } } }\'',
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_allows_resolving_a_review_thread_with_braces_in_strings_and_comments(self):
        for command in [
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "PRRT_x", clientMutationId: "a{b"}) { thread { id } } }\'',
            "gh api graphql -f query='mutation {\n# a { comment\nresolveReviewThread(input: "
            '{threadId: """x { y"""}) { thread { id } } }\'',
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_denies_a_second_mutation_hidden_by_braces_in_strings_or_comments(self):
        for command in [
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "{"}) { thread { id } } mergePullRequest(input: '
            '{pullRequestId: "}"}) { clientMutationId } }\'',
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "x"}) { thread { id } } mergePullRequest(input: '
            '{pullRequestId: "{"}) { clientMutationId } x: __typename }\'',
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "x", clientMutationId: "{"}) { thread { id } } '
            "mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: "
            '{threadId: "}"}) { thread { id } } } mutation { mergePullRequest(input: {}) '
            "{ clientMutationId } }'",
            "gh api graphql -f query='mutation { a: resolveReviewThread(input: "
            '{threadId: """{"""}) { thread { id } } '
            "mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: {}) { thread { id } } "
            "# }\nmergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: \"x}) "
            "{ thread { id } } mergePullRequest(input: {}) { clientMutationId } }'",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_resolving_a_review_thread_with_an_input_file(self):
        for command in [
            "gh api graphql -f query='mutation { resolveReviewThread(input: {}) "
            "{ thread { id } } }' --input body.json",
            "gh api graphql --input=body.json -f query='mutation { resolveReviewThread(input: {}) "
            "{ thread { id } } }'",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_every_other_graphql_mutation(self):
        for command in [
            "gh api graphql -f query='mutation { unresolveReviewThread(input: {}) { "
            "clientMutationId } }'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: {}) { "
            "clientMutationId } mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { mergePullRequest(input: {}) { "
            "clientMutationId } }'",
            "gh api graphql -f query='mutation { merge: resolveReviewThread(input: {}) { "
            "clientMutationId } } mutation Other { mergePullRequest(input: {}) { "
            "clientMutationId } }'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: {}) { "
            "clientMutationId } }' -f note='mutation'",
            "gh api graphql -f query='mutation { resolveReviewThread(input: {}) { thread { "
            "id } } }' -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { ...Merge } fragment Merge on Mutation { "
            "mergePullRequest(input: {}) { clientMutationId } }'",
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

    def test_denies_gh_release_with_flag_before_subcommand(self):
        repo = git_repo(with_release_me=True)
        for command in [
            "gh release -R ostendorf-cloud/skills create v1.0.0",
            "gh release --repo=ostendorf-cloud/skills edit v1.0.0",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), "deny", command
            )

    def test_allows_gh_release_list_with_flag_before_subcommand(self):
        repo = git_repo(with_release_me=True)
        self.assertIsNone(
            decision(
                run_hook(
                    "iac_first.py",
                    bash_payload("gh release -R ostendorf-cloud/skills list", repo),
                )
            )
        )

    def test_denies_a_noun_mutation_behind_a_wrapper_prefix(self):
        for command in [
            "gh label create bug --color d73a4a",
            "sudo gh label create bug --color d73a4a",
            "sudo -u ci gh repo edit owner/repo --visibility private",
            "doas gh secret set DEPLOY_KEY --body value",
            "env GH_HOST=github.example.com gh variable set REGION --body eu",
            "mise exec -- gh label delete bug",
            "mise exec gh@2 -- gh label delete bug",
            "nice -n 10 gh repo create owner/repo --private",
            "nohup gh label edit bug --color 000000",
            "time gh secret delete DEPLOY_KEY",
            "sudo /opt/homebrew/bin/gh label create bug --color d73a4a",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_alias_or_extension_mutation_behind_a_wrapper_prefix(self):
        for command in [
            "gh alias set prs 'pr list'",
            "sudo gh alias set prs 'pr list'",
            "mise exec -- gh extension install owner/gh-extension",
            "nice -n 10 gh extension upgrade --all",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_api_write_behind_a_wrapper_prefix(self):
        for command in [
            "gh api -X PATCH repos/owner/repo",
            "sudo gh api -X PATCH repos/owner/repo",
            "env GH_TOKEN=x gh api --method PUT repos/owner/repo/rulesets/1",
            "mise exec -- gh api -X POST orgs/owner",
            "nice -n 10 gh api -X DELETE repos/owner/repo/labels/bug",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_an_api_pull_request_write_behind_a_wrapper_prefix(self):
        for command in [
            "gh api -X PUT repos/owner/repo/pulls/1/merge",
            "sudo gh api -X PUT repos/owner/repo/pulls/1/merge",
            "mise exec -- gh api -X PATCH repos/owner/repo/pulls/1",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_graphql_mutation_behind_a_wrapper_prefix(self):
        for command in [
            "gh api graphql -f query='mutation { enablePullRequestAutoMerge }'",
            "sudo gh api graphql -f query='mutation { enablePullRequestAutoMerge }'",
            "mise exec -- gh api graphql -f query='mutation { enablePullRequestAutoMerge }'",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command))), "deny", command
            )

    def test_denies_a_release_mutation_behind_a_wrapper_prefix(self):
        repo = git_repo(with_release_me=True)
        for command in [
            "gh release create v1.0.0",
            "sudo gh release create v1.0.0",
            "mise exec -- gh release create v1.0.0",
            "nice -n 10 gh release delete v1.0.0",
        ]:
            self.assertEqual(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), "deny", command
            )

    def test_denies_an_unparseable_gh_part_behind_a_wrapper_prefix(self):
        for command in [
            'gh repo edit owner/repo --description "unclosed',
            'sudo gh repo edit owner/repo --description "unclosed',
        ]:
            output = run_hook("iac_first.py", bash_payload(command))
            self.assertEqual(decision(output), "deny", command)

    def test_allows_reads_behind_a_wrapper_prefix(self):
        for command in [
            "gh label list",
            "sudo gh label list",
            "sudo -u ci gh repo view owner/repo",
            "doas gh secret list",
            "env GH_HOST=github.example.com gh variable list",
            "mise exec -- gh api repos/owner/repo",
            "mise exec gh@2 -- gh alias list",
            "nice -n 10 gh extension list",
            "nohup gh api graphql -f query='query { viewer { login } }'",
            "time gh pr list",
            "sudo gh api -X PATCH repos/owner/repo/issues/1",
        ]:
            self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))), command)

    def test_allows_a_release_read_behind_a_wrapper_prefix(self):
        repo = git_repo(with_release_me=True)
        for command in [
            "gh release list",
            "sudo gh release list",
            "mise exec -- gh release view v1.0.0",
        ]:
            self.assertIsNone(
                decision(run_hook("iac_first.py", bash_payload(command, repo))), command
            )

    def test_allows_a_mutation_behind_an_unlisted_wrapper(self):
        command = "timeout 5 gh label create bug --color d73a4a"
        self.assertIsNone(decision(run_hook("iac_first.py", bash_payload(command))))

    def test_allows_gh_release_without_a_release_tool_configured(self):
        repo = git_repo(with_release_please=False, with_release_me=False)
        self.assertIsNone(
            decision(run_hook("iac_first.py", bash_payload("gh release create v1.0.0", repo)))
        )


if __name__ == "__main__":
    unittest.main()
