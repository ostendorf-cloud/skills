# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for skill_reminder.py."""

import glob
import json
import os
import sys
import unittest

from helper import HOOKS_DIR, context, run_hook

sys.path.insert(0, HOOKS_DIR)
import skill_reminder  # noqa: E402

SKILLS_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "skills")

# Trigger phrases per skill. The descriptions no longer list them, so this table is the single
# source. Every phrase must match its own skill, or sit in UNMATCHED_PHRASES with a reason.
PHRASES = {
    "ansible-conventions": (
        "write a playbook",
        "ansible role",
        "dynamic inventory",
        "ansible-lint",
        "check mode",
        "pre-flight guard",
        "Playbook schreiben",
        "Inventar generieren",
    ),
    "ci-conventions": (
        "Agent laeuft in CI",
        "unbeaufsichtigt in der Pipeline",
        "Workflow benennen",
        "GitHub Actions Workflow",
        "Tofu Pipeline",
        "mehrere Module planen",
    ),
    "ci-review": (
        "Pull Request aus der CI pruefen",
        "automatisierte Review",
        "Infrastruktur Pull Request",
        "Plan Kommentar pruefen",
    ),
    "container-images": (
        "Dockerfile schreiben",
        "Basisimage pinnen",
        "multi-arch build",
        "linux/arm64",
        "manifest list digest",
        "Containerimage veroeffentlichen",
        "mehrere Architekturen bauen",
        "base image digest",
    ),
    "git-conventions": (
        "branch name",
        "commit message",
        "rebase",
        "force push",
        "pull request",
        "revert",
        "worktree",
        "Branch anlegen",
        "Commit schreiben",
        "Pull Request erstellen",
        "Force Push",
        "Worktree starten",
    ),
    "repo-conventions": (
        "new repository",
        "repository layout",
        "mise.toml",
        "Taskfile",
        "where does this script go",
        "Repository anlegen",
        "Tool-Version pinnen",
    ),
    "secrets-handling": (
        "secret",
        "token",
        "credential",
        "kubeconfig",
        "leaked key",
        "Secret",
        "Zugangsdaten",
        "geleakter Token",
    ),
    "website-conventions": (
        "new website",
        "build a website",
        "build a landing page",
        "write an imprint",
        "write a privacy policy",
        "Impressum schreiben",
        "Datenschutzerklaerung schreiben",
        "Webseite bauen",
        "Webseite pruefen",
    ),
    "writing-style": (
        "rewrite this",
        "house style",
        "test name",
        "commit message",
        "pull request body",
        "issue body",
        "Text umschreiben",
        "Hausstil",
        "Commit-Nachricht",
    ),
    "adr": ("Architekturentscheidung dokumentieren", "ADR schreiben"),
    "agents-md": (
        "nested AGENTS.md",
        "trim the AGENTS.md",
        "AGENTS.md is too long",
        "lint:agents-md",
        "AGENTS.md kuerzen",
    ),
    "concept-doc": ("Konzept schreiben", "Feature-Konzept vor der Umsetzung"),
    "post-mortem": ("post mortem", "postmortem", "incident report", "Vorfall", "Ausfall"),
    "readme": ("README schreiben", "README aktualisieren"),
    "go-conventions": ("Go schreiben", "Go-Konventionen"),
    "go-lint": ("Go linten",),
    "go-tests": ("Go-Tests schreiben", "Testabdeckung"),
    "helm-chart": (
        "write a chart",
        "helm template",
        "values.yaml",
        "helm lint",
        "helm-unittest",
        "Ingress",
        "Gateway API",
        "HTTPRoute",
        "Helm Chart schreiben",
        "Chart Werte",
        "Chart Version",
    ),
    "k8s-debug": (
        "pod crash looping",
        "pending pod",
        "helm release failed",
        "service unreachable",
        "Pod startet nicht",
        "Fehler im Cluster",
    ),
    "kubernetes-conventions": (
        "helm_release",
        "install a chart",
        "CRD",
        "namespace",
        "network policy",
        "pod security",
        "Ingress",
        "Gateway API",
        "HTTPRoute",
        "Kubernetes Workload",
        "Namespace anlegen",
        "Secret einbinden",
    ),
    "talos-ops": (
        "talos upgrade",
        "machine config",
        "talosctl",
        "etcd quorum",
        "apply-config",
        "Talos Node aktualisieren",
        "Node neu starten",
    ),
    "agents": (
        "spawn an agent",
        "run this in parallel",
        "clean up the agents",
        "Subagenten einsetzen",
        "Agenten aufraeumen",
    ),
    "skills-config": (
        "set up the skills config",
        "validate agent-skills.json",
        "Konfiguration pruefen",
        "Repo-Konfiguration anlegen",
    ),
    "python-conventions": ("Python schreiben", "Python-Konventionen"),
    "conformance-checks": ("eigene Konvention pruefen", "Policy schreiben"),
    "fix-ci": ("CI reparieren", "Workflow debuggen"),
    "lint": (
        "lint",
        "format",
        "run linters",
        "Code linten",
        "Code formatieren",
        "Linter laufen lassen",
    ),
    "security-review": ("security review", "sicherheitscheck", "check this for vulnerabilities"),
    "test": ("add tests", "Tests ausfuehren", "Tests ergaenzen"),
    "testing-conventions": ("Testkonventionen", "Tests schreiben"),
    "release-conventions": ("Release-Konventionen", "Versionierung festlegen"),
    "release": ("Release veroeffentlichen", "Version freigeben"),
    "commit": (
        "commit this",
        "split these commits",
        "commit the changes",
        "das committen",
        "Commits aufteilen",
    ),
    "deps": (
        "triage dependency PRs",
        "merge renovate PRs",
        "update dependencies",
        "Dependency-PRs triagieren",
        "Abhaengigkeiten aktualisieren",
    ),
    "pr": ("open a pull request", "update the pull request", "PR erstellen", "PR aktualisieren"),
    "prune-branches": (
        "clean up branches",
        "delete merged branches",
        "prune branches",
        "Branches aufraeumen",
        "alte Branches loeschen",
    ),
    "review": (
        "review this",
        "review the pull request",
        "request changes",
        "Code Review",
        "PR reviewen",
    ),
    "worktree": (
        "create a worktree",
        "parallel session",
        "remove the worktree",
        "Worktree anlegen",
        "Worktree entfernen",
    ),
    "github-as-code": (
        "github provider",
        "repository settings",
        "rulesets",
        "labels as code",
        "org settings",
        "github app",
        "app permissions",
        "Repo-Einstellungen",
        "GitHub-App anlegen",
    ),
    "opentofu-conventions": (
        "write tofu",
        "opentofu module",
        "variables.tf",
        "provider block",
        "state backend",
        "tofu plan",
        "tofu apply",
        "Tofu Code schreiben",
        "Variablen Datei",
        "Terraform Code",
        "Statedatei",
    ),
    "tofu-module": (
        "new module",
        "extract a module",
        "module README",
        "module inputs",
        "module outputs",
        "neues Modul",
        "Modul extrahieren",
        "Modul Variablen",
    ),
    "tofu-plan": (
        "tofu plan",
        "tofu apply",
        "review a plan",
        "infrastructure change",
        "drift",
        "Plan erstellen",
        "Tofu anwenden",
        "Drift pruefen",
    ),
    "handoff": ("write a handoff", "hand this off", "Uebergabe schreiben", "Zwischenstand sichern"),
    "implement": (
        "implement issue 42",
        "work this issue",
        "address the review feedback",
        "Issue umsetzen",
        "Ticket abarbeiten",
    ),
    "issue": (
        "open an issue",
        "create a ticket",
        "file a bug",
        "Issue erstellen",
        "Ticket anlegen",
    ),
    "plan": ("write a plan", "plan this issue", "Plan schreiben", "Vorgehen planen"),
    "propose-rule": (
        "propose a rule change",
        "this should be a rule",
        "Baseline anpassen",
        "Regel vorschlagen",
    ),
    "refine-issue": (
        "refine this issue",
        "groom the backlog",
        "Issue schaerfen",
        "Ticket verfeinern",
    ),
    "tldr": (
        "give me a tldr",
        "summarize this",
        "write the PR description",
        "kurz zusammenfassen",
        "Status geben",
    ),
    "user-story": (
        "write a user story",
        "turn this into a story",
        "check this story",
        "User Story schreiben",
    ),
    "work-queue": (
        "drain the queue",
        "work the issues",
        "run the work loop",
        "Warteschlange abarbeiten",
        "Issues automatisch bearbeiten",
    ),
    "work-review": (
        "review issue 42",
        "check the PR for issue 42",
        "Issue 42 review",
        "PR gegenpruefen",
    ),
}

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
    ("lint", "lint"): "single verb",
    ("lint", "format"): "single verb",
    ("helm-chart", "Ingress"): "owned by kubernetes-conventions",
    ("helm-chart", "Gateway API"): "owned by kubernetes-conventions",
    ("helm-chart", "HTTPRoute"): "owned by kubernetes-conventions",
    ("kubernetes-conventions", "namespace"): "single noun",
    ("worktree", "parallel session"): "noun phrase",
    ("tofu-plan", "infrastructure change"): "noun phrase",
    ("tofu-plan", "drift"): "single noun",
}


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
            ("the AGENTS.md is too long, move parts into a nested AGENTS.md", "agents-md"),
            ("AGENTS.md kuerzen", "agents-md"),
            ("why does lint:agents-md warn", "agents-md"),
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

    def test_every_listed_phrase_matches_its_own_skill(self):
        missing = []
        for skill, phrases in PHRASES.items():
            for phrase in phrases:
                if (skill, phrase) in UNMATCHED_PHRASES:
                    continue
                if skill not in skill_reminder.matches(phrase):
                    missing.append((skill, phrase))
        self.assertEqual(missing, [])

    def test_allow_list_names_only_phrases_that_still_fail(self):
        stale = []
        for skill, phrase in UNMATCHED_PHRASES:
            if skill in skill_reminder.matches(phrase):
                stale.append((skill, phrase))
        self.assertEqual(stale, [])

    def test_allow_list_names_only_phrases_listed_in_phrases(self):
        listed = {(skill, phrase) for skill, phrases in PHRASES.items() for phrase in phrases}
        self.assertEqual(sorted(set(UNMATCHED_PHRASES) - listed), [])

    def test_every_skill_has_listed_phrases(self):
        skills = {
            os.path.basename(os.path.dirname(path))
            for path in glob.glob(os.path.join(SKILLS_DIR, "*", "*", "SKILL.md"))
        }
        self.assertTrue(skills, "no skills found")
        self.assertEqual(sorted(skills - {s for s, p in PHRASES.items() if p}), [])

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

    def test_matches_website_tasks(self):
        cases = [
            "Impressum fuer die Seite schreiben",
            "build a new website",
            "build a website for the club",
            "write an imprint for this site",
            "write a privacy policy",
            "Datenschutzerklaerung schreiben",
            "Webseite pruefen",
        ]
        for prompt in cases:
            self.assertIn("website-conventions", skill_reminder.matches(prompt), prompt)

    def test_stays_quiet_on_website_talk_that_is_no_task(self):
        cases = [
            "the website is down",
            "check the agbase config",
            "privacy of the token",
            "the imprint is long",
        ]
        for prompt in cases:
            self.assertNotIn("website-conventions", skill_reminder.matches(prompt), prompt)

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
