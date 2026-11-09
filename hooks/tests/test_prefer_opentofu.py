# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for prefer_opentofu.py."""

import json
import os
import subprocess
import tempfile
import unittest

from helper import bash_payload, decision, run_hook


def git_repo(config=None):
    path = tempfile.mkdtemp(prefix="prefer-opentofu-")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, capture_output=True)
    if config is not None:
        with open(os.path.join(path, ".agent-skills.json"), "w", encoding="utf-8") as handle:
            json.dump(config, handle)
    return path


class PreferOpenTofuTest(unittest.TestCase):
    def test_allows_tofu_and_unrelated_commands(self):
        for command in ["tofu plan", "tofu apply -auto-approve", "grep -rn terraform docs/"]:
            self.assertIsNone(
                decision(run_hook("prefer_opentofu.py", bash_payload(command))), command
            )

    def test_denies_terraform_by_default(self):
        repo = git_repo()
        for command in ["terraform plan", "sudo terraform apply", "cd infra && terraform init"]:
            self.assertEqual(
                decision(run_hook("prefer_opentofu.py", bash_payload(command, repo))),
                "deny",
                command,
            )

    def test_denies_terraform_behind_a_quoted_name_or_a_wrapper(self):
        repo = git_repo()
        for command in [
            '"terraform" plan',
            "/usr/local/bin/terraform plan",
            "sudo -u ci terraform apply",
            "nice -n 10 terraform apply",
            "mise exec -- terraform plan",
        ]:
            self.assertEqual(
                decision(run_hook("prefer_opentofu.py", bash_payload(command, repo))),
                "deny",
                command,
            )

    def test_allows_a_command_whose_name_only_ends_in_terraform(self):
        repo = git_repo()
        for command in ["myterraform plan", "terraformer import aws", "tfterraform plan"]:
            self.assertIsNone(
                decision(run_hook("prefer_opentofu.py", bash_payload(command, repo))), command
            )

    def test_allows_terraform_when_configured(self):
        repo = git_repo({"iac": "terraform"})
        self.assertIsNone(
            decision(run_hook("prefer_opentofu.py", bash_payload("terraform plan", repo)))
        )


if __name__ == "__main__":
    unittest.main()
