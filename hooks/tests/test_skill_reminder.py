# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for skill_reminder.py."""

import glob
import json
import os
import re
import sys
import unittest

from helper import HOOKS_DIR, context, run_hook

sys.path.insert(0, HOOKS_DIR)
import skill_reminder  # noqa: E402

SKILLS_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "skills")

# Words that only occur in the English "Use when ..." clause of a description. The German
# phrases at the end of a description without a "Trigger phrases:" list follow the last
# item that holds one of them.
CLAUSE_WORDS = re.compile(r"\b(when|or|needs|including|before|after|use)\b", re.IGNORECASE)

# Phrases from a description that the hook deliberately does not match, with the reason.
# A bare noun or a phrase another skill owns would make the reminder match almost every
# prompt about the repository.
UNMATCHED_PHRASES = {
    ("git-conventions", "commit message"): "owned by the commit skill",
    ("git-conventions", "Commit schreiben"): "owned by the commit skill",
    ("git-conventions", "pull request"): "single noun",
    ("git-conventions", "Pull Request erstellen"): "owned by the pr skill",
    ("git-conventions", "rebase"): "single verb, also matched in status talk",
    ("git-conventions", "revert"): "single verb",
    ("git-conventions", "worktree"): "single noun",
    ("git-conventions", "Worktree starten"): "owned by the worktree skill",
    ("repo-conventions", "mise.toml"): "file name, named in unrelated prompts",
    ("repo-conventions", "Taskfile"): "file name, named in unrelated prompts",
    ("secrets-handling", "secret"): "single noun",
    ("secrets-handling", "Secret"): "single noun",
    ("secrets-handling", "token"): "single noun",
    ("secrets-handling", "credential"): "single noun",
    ("writing-style", "test name"): "noun phrase",
    ("writing-style", "commit message"): "owned by the commit skill",
    ("writing-style", "pull request body"): "owned by the pr skill",
    ("writing-style", "issue body"): "owned by the issue skill",
    ("writing-style", "Commit-Nachricht"): "owned by the commit skill",
    ("post-mortem", "Vorfall"): "single noun",
    ("post-mortem", "Ausfall"): "single noun",
    ("go-tests", "Testabdeckung"): "owned by the test skill",
    ("testing-conventions", "Tests schreiben"): "owned by the test skill",
    ("lint", "format"): "single verb",
    ("helm-chart", "Ingress"): "owned by kubernetes-conventions",
    ("helm-chart", "Gateway API"): "owned by kubernetes-conventions",
    ("helm-chart", "HTTPRoute"): "owned by kubernetes-conventions",
    ("kubernetes-conventions", "namespace"): "single noun",
    ("worktree", "parallel session"): "noun phrase",
    ("tofu-plan", "infrastructure change"): "noun phrase",
    ("tofu-plan", "drift"): "single noun",
}


def description(path: str) -> str:
    """The frontmatter description of a skill file as one line."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    values = []
    collecting = False
    for line in lines[1:]:
        if line.startswith("---"):
            break
        if line.startswith("description:"):
            collecting = True
            values.append(line[len("description:") :].strip())
        elif collecting and (line.startswith(" ") or not line.strip()):
            values.append(line.strip())
        else:
            collecting = False
    return " ".join(value for value in values if value and value != ">-")


def trigger_phrases(text: str) -> list:
    """The explicit trigger phrases of a description, else its trailing German phrases."""
    if "Trigger phrases:" in text:
        tail = text.split("Trigger phrases:", 1)[1]
        return [item.strip() for item in tail.strip().rstrip(".").split(", ") if item.strip()]
    sentence = text.rstrip(".").rsplit(". ", 1)[-1]
    phrases = []
    for item in reversed(sentence.split(", ")):
        if CLAUSE_WORDS.search(item) or item.startswith('"'):
            break
        phrases.append(item.strip())
    return list(reversed(phrases))


def prompt_payload(prompt: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}


class SkillReminderTest(unittest.TestCase):
    def test_names_the_matching_skill(self):
        cases = [
            ("can you commit this?", "commit"),
            ("open a pull request for the branch", "pr"),
            ("ci is red again", "fix-ci"),
            ("write an adr for this decision", "adr"),
            ("kannst du das committen?", "commit"),
            ("the tofu plan looks wrong", "opentofu-conventions"),
            ("run a security review on this branch", "security-review"),
            ("is CVE-2024-12345 relevant for this dependency", "security-review"),
            ("open a pull request for this branch", "pr"),
            ("PR aufmachen", "pr"),
            ("Issue erstellen fuer den Bug", "issue"),
            ("create an issue for the flaky job", "issue"),
            ("run golangci-lint", "go-lint"),
            ("rebase onto main", "git-conventions"),
            ("let's create a new tofu module for this", "tofu-module"),
            ("I need to rebase this branch", "git-conventions"),
            ("set up a new repository with AGENTS.md", "repo-conventions"),
            ("please rewrite this in the house style", "writing-style"),
            ("fix the github actions workflow", "ci-conventions"),
            ("bump the version using semver", "release-conventions"),
            ("update the repository settings for this org", "github-as-code"),
            ("we need new rulesets on the default branch", "github-as-code"),
            ("can you write an ansible playbook for this", "ansible-conventions"),
            ("write up the post mortem for last night's outage", "post-mortem"),
            ("I need to review this golang package", "go-conventions"),
            ("writing some go code for a cli", "go-conventions"),
            ("adding a new go module to the repo", "go-conventions"),
            ("let's write a go test for this function", "go-tests"),
            ("switch this to a table driven test", "go-tests"),
            ("testing in go with httptest", "go-tests"),
            ("golangci-lint is failing in ci", "go-lint"),
            ("run gofumpt on this file", "go-lint"),
        ]
        for prompt, skill in cases:
            self.assertIn(
                skill, context(run_hook("skill_reminder.py", prompt_payload(prompt))), prompt
            )

    def test_security_review_comes_before_review(self):
        message = context(
            run_hook("skill_reminder.py", prompt_payload("do a security review of this PR"))
        )
        self.assertIn("security-review", message)

    def test_go_tests_and_go_lint_outrank_their_generic_counterpart(self):
        prompt = "please run go test and then run the tests again"
        message = context(run_hook("skill_reminder.py", prompt_payload(prompt)))
        self.assertEqual(self.names(message), ["go-tests", "test"])

        prompt = "run golangci-lint and then run the linter again"
        message = context(run_hook("skill_reminder.py", prompt_payload(prompt)))
        self.assertEqual(self.names(message), ["go-lint", "lint"])

    @staticmethod
    def names(message: str) -> list:
        return message.split(": ", 1)[1].split(". Load")[0].split(", ")

    def test_stays_quiet_without_a_match(self):
        for prompt in ["what time is it", "explain this function to me", ""]:
            self.assertEqual(
                context(run_hook("skill_reminder.py", prompt_payload(prompt))), "", prompt
            )

    def test_stays_quiet_on_single_nouns(self):
        for prompt in [
            "the issue is in the branch",
            "the pr has a failing test",
            "where is the secret stored in the workflow",
            "this hook needs a token and a plan",
            "was ist der Stand beim Review",
        ]:
            self.assertEqual(
                context(run_hook("skill_reminder.py", prompt_payload(prompt))), "", prompt
            )

    def test_long_german_status_prompt_matches_at_most_one_skill(self):
        prompt = (
            "Bitte lass uns starten die Skills und Claude Settings so zu ueberarbeiten, "
            "dass meine Token Usage deutlich weniger wird. Es gibt einige Pull Requests "
            "und Issues, raeume nach dem Merge Branch und Worktree auf und setze Labels."
        )
        message = context(run_hook("skill_reminder.py", prompt_payload(prompt)))
        self.assertLessEqual(len(self.names(message)) if message else 0, 1)

    def test_every_description_phrase_matches_its_own_skill(self):
        missing = []
        seen = set()
        for path in sorted(glob.glob(os.path.join(SKILLS_DIR, "*", "*", "SKILL.md"))):
            skill = os.path.basename(os.path.dirname(path))
            for phrase in trigger_phrases(description(path)):
                key = (skill, phrase)
                seen.add(key)
                if key in UNMATCHED_PHRASES:
                    continue
                if skill not in skill_reminder.matches(phrase):
                    missing.append(key)
        self.assertEqual(missing, [])
        self.assertTrue(seen, "no trigger phrases found")

    def test_allow_list_names_only_phrases_that_still_fail(self):
        stale = []
        for skill, phrase in UNMATCHED_PHRASES:
            if skill in skill_reminder.matches(phrase):
                stale.append((skill, phrase))
        self.assertEqual(stale, [])

    def test_allow_list_names_only_phrases_in_a_description(self):
        present = set()
        for path in glob.glob(os.path.join(SKILLS_DIR, "*", "*", "SKILL.md")):
            skill = os.path.basename(os.path.dirname(path))
            present.update((skill, phrase) for phrase in trigger_phrases(description(path)))
        self.assertEqual(sorted(set(UNMATCHED_PHRASES) - present), [])

    def test_matches_phrases_from_the_work_loop_skills(self):
        cases = [
            ("review issue 42", "work-review"),
            ("Issue 42 review", "work-review"),
            ("PR gegenpruefen", "work-review"),
            ("refine this issue", "refine-issue"),
            ("Ticket verfeinern", "refine-issue"),
            ("work this issue", "implement"),
            ("address the review feedback", "implement"),
            ("implement the feature", "implement"),
            ("fix CI", "fix-ci"),
            ("CI reparieren", "fix-ci"),
            ("Workflow debuggen", "fix-ci"),
            ("Subagenten einsetzen", "agents"),
            ("Agenten aufraeumen", "agents"),
            ("run this in parallel", "agents"),
            ("Warteschlange abarbeiten", "work-queue"),
            ("Version freigeben", "release"),
            ("validate agent-skills.json", "skills-config"),
            ("Python schreiben", "python-conventions"),
            ("Go schreiben", "go-conventions"),
            ("Go linten", "go-lint"),
            ("Dockerfile schreiben", "container-images"),
            ("multi-arch build", "container-images"),
            ("base image digest", "container-images"),
        ]
        for prompt, skill in cases:
            self.assertIn(skill, skill_reminder.matches(prompt), prompt)

    def test_words_the_hint_without_ordering_a_load(self):
        message = context(run_hook("skill_reminder.py", prompt_payload("open a pull request")))
        self.assertEqual(
            message, "Skills that may apply: pr. Load one only when the task needs it."
        )

    def test_never_blocks_a_prompt(self):
        output = run_hook(
            "skill_reminder.py", prompt_payload("commit and open a pull request and cut a release")
        )
        self.assertNotIn("permissionDecision", json.dumps(output))

    def test_caps_the_number_of_skills(self):
        prompt = (
            "commit this, open a pull request, create an issue, write an adr, "
            "run the tests, run the linter, renovate, tofu"
        )
        message = context(run_hook("skill_reminder.py", prompt_payload(prompt)))
        self.assertEqual(len(self.names(message)), 2)


if __name__ == "__main__":
    unittest.main()
