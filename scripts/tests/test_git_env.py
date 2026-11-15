# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Importing the test loader must cut off a signing setup that cannot sign."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

TESTS_DIR = Path(__file__).resolve().parent

FAILING_SIGNING_CONFIG = """[commit]
\tgpgsign = true
[gpg]
\tformat = ssh
[gpg "ssh"]
\tprogram = /usr/bin/false
[user]
\tsigningkey = not-a-real-key
"""

# Imports the loader the way a test module does, then commits with plain git and the
# inherited environment.
CHILD = """
import subprocess, sys
import _load  # noqa: F401
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
    def test_importing_the_loader_lets_a_plain_git_commit_succeed_under_a_failing_signer(self):
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "failing-sign.gitconfig"
            config.write_text(FAILING_SIGNING_CONFIG)
            repo = Path(tmp) / "repo"
            repo.mkdir()
            env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config))
            env.pop("GIT_CONFIG_SYSTEM", None)
            env.pop("GIT_CONFIG_NOSYSTEM", None)
            result = subprocess.run(
                [sys.executable, "-c", CHILD, str(repo)],
                cwd=TESTS_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
