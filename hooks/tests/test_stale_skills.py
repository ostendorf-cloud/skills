# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for stale_skills.py."""

import json
import os
import subprocess
import tempfile
import unittest

from helper import context, run_hook


def run_git(args: list, cwd: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def checkout() -> str:
    """A git checkout with one commit, no remote."""
    path = tempfile.mkdtemp(prefix="stale-skills-checkout-")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def commit_of(path: str) -> str:
    return run_git(["rev-parse", "HEAD"], path)


def write_state(home: str, source: str, commit: str, target: str = "") -> None:
    directory = os.path.join(home, ".config", "agent-skills")
    os.makedirs(directory, exist_ok=True)
    name = f"{target}.state.json" if target else "state.json"
    data = {"source": source, "commit": commit}
    with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def start_payload() -> dict:
    return {"hook_event_name": "SessionStart", "cwd": os.getcwd(), "session_id": "session-a"}


def run_with_home(home: str) -> dict:
    env = {**os.environ, "HOME": home}
    return run_hook("stale_skills.py", start_payload(), env=env)


class StaleSkillsTest(unittest.TestCase):
    def test_stays_quiet_when_installed_commit_matches_the_checkout(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        source = checkout()
        write_state(home, source, commit_of(source))
        self.assertEqual(context(run_with_home(home)), "")

    def test_warns_when_installed_commit_differs_from_the_checkout(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        source = checkout()
        write_state(home, source, "0" * 40)
        message = context(run_with_home(home))
        self.assertIn("task install", message)
        self.assertIn(commit_of(source)[:12], message)

    def test_stays_quiet_when_no_state_file_exists(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        self.assertEqual(context(run_with_home(home)), "")

    def test_stays_quiet_when_the_recorded_source_no_longer_exists_on_disk(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        write_state(home, "/no/such/checkout", "0" * 40)
        self.assertEqual(context(run_with_home(home)), "")

    def test_stays_quiet_when_the_recorded_source_is_not_a_git_checkout(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        source = tempfile.mkdtemp(prefix="stale-skills-not-git-")
        write_state(home, source, "0" * 40)
        self.assertEqual(context(run_with_home(home)), "")

    def test_warns_when_the_checkout_is_behind_origin_main(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        remote = checkout()
        source = tempfile.mkdtemp(prefix="stale-skills-clone-")
        subprocess.run(["git", "clone", "-q", remote, source], check=True, capture_output=True)
        run_git(
            [
                "-c",
                "user.email=t@example.com",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "second",
            ],
            remote,
        )
        subprocess.run(["git", "fetch", "-q"], cwd=source, check=True, capture_output=True)

        write_state(home, source, commit_of(source))
        message = context(run_with_home(home))
        self.assertIn("origin/main", message)
        self.assertIn("Pull", message)

    def test_warns_with_both_lines_when_both_causes_apply(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        remote = checkout()
        source = tempfile.mkdtemp(prefix="stale-skills-clone-")
        subprocess.run(["git", "clone", "-q", remote, source], check=True, capture_output=True)
        run_git(
            [
                "-c",
                "user.email=t@example.com",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "second",
            ],
            remote,
        )
        subprocess.run(["git", "fetch", "-q"], cwd=source, check=True, capture_output=True)

        write_state(home, source, "0" * 40)
        message = context(run_with_home(home))
        self.assertIn("task install", message)
        self.assertIn("origin/main", message)
        self.assertEqual(len(message.splitlines()), 2)

    def test_stays_quiet_when_origin_was_never_fetched(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        remote = checkout()
        source = checkout()
        subprocess.run(
            ["git", "remote", "add", "origin", remote],
            cwd=source,
            check=True,
            capture_output=True,
        )
        write_state(home, source, commit_of(source))
        self.assertEqual(context(run_with_home(home)), "")

    def test_deduplicates_a_source_shared_by_several_targets(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        source = checkout()
        write_state(home, source, "0" * 40)
        write_state(home, source, "0" * 40, target="work")
        message = context(run_with_home(home))
        self.assertEqual(message.count("task install"), 1)

    def test_ignores_events_other_than_session_start(self):
        home = tempfile.mkdtemp(prefix="stale-skills-home-")
        source = checkout()
        write_state(home, source, "0" * 40)
        env = {**os.environ, "HOME": home}
        payload = {"hook_event_name": "SessionEnd", "cwd": os.getcwd(), "session_id": "a"}
        self.assertEqual(context(run_hook("stale_skills.py", payload, env=env)), "")


if __name__ == "__main__":
    unittest.main()
