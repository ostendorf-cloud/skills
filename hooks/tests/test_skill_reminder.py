# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for skill_reminder.py."""

import json
import unittest

from helper import context, run_hook


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
            ("any known cve in this dependency", "security-review"),
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

    def test_stays_quiet_without_a_match(self):
        for prompt in ["what time is it", "explain this function to me", ""]:
            self.assertEqual(
                context(run_hook("skill_reminder.py", prompt_payload(prompt))), "", prompt
            )

    def test_never_blocks_a_prompt(self):
        output = run_hook(
            "skill_reminder.py", prompt_payload("commit and open a pull request and cut a release")
        )
        self.assertNotIn("permissionDecision", json.dumps(output))

    def test_caps_the_number_of_skills(self):
        prompt = "commit, pull request, release, issue, adr, review, tests, lint, renovate, tofu"
        named = context(run_hook("skill_reminder.py", prompt_payload(prompt))).split(": ", 1)[1]
        count = len(named.split(". Load")[0].split(", "))
        self.assertLessEqual(count, 4)


if __name__ == "__main__":
    unittest.main()
