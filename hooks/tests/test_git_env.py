# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Importing the test helper must cut off a signing setup that cannot sign."""

import os
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

FAILING_SIGNING_CONFIG = """[commit]
\tgpgsign = true
[gpg]
\tformat = ssh
[gpg "ssh"]
\tprogram = /usr/bin/false
[user]
\tsigningkey = not-a-real-key
"""

# Imports the helper the way a test module does, then commits with plain git and the
# inherited environment.
CHILD = """
import subprocess, sys
import helper  # noqa: F401
repo = sys.argv[1]
for args in (
    ["init", "-q"],
    ["config", "user.email", "t@example.com"],
    ["config", "user.name", "t"],
    ["commit", "-q", "--allow-empty", "-m", "chore: init"],
):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, timeout=30)
"""


class GitEnvTest(unittest.TestCase):
    def test_importing_the_helper_lets_a_plain_git_commit_succeed_under_a_failing_signer(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(tmp, "failing-sign.gitconfig")
            with open(config, "w", encoding="utf-8") as handle:
                handle.write(FAILING_SIGNING_CONFIG)
            repo = os.path.join(tmp, "repo")
            os.mkdir(repo)
            env = dict(os.environ, GIT_CONFIG_GLOBAL=config)
            env.pop("GIT_CONFIG_SYSTEM", None)
            env.pop("GIT_CONFIG_NOSYSTEM", None)
            result = subprocess.run(
                [sys.executable, "-c", CHILD, repo],
                cwd=TESTS_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
