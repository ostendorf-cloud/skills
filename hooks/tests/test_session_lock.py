# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for session_lock.py."""

import os
import subprocess
import tempfile
import time
import unittest

from helper import context, run_hook


def git_repo() -> str:
    path = tempfile.mkdtemp(prefix="session-lock-")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, capture_output=True)
    return path


def sessions_dir(repo: str) -> str:
    return os.path.join(repo, ".git", "agent-skills", "sessions")


class SessionLockTest(unittest.TestCase):
    def test_records_a_session_file_on_start(self):
        repo = git_repo()
        payload = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-a"}
        run_hook("session_lock.py", payload)
        self.assertTrue(os.path.isfile(os.path.join(sessions_dir(repo), "session-a")))

    def test_stays_quiet_when_no_other_session_is_live(self):
        repo = git_repo()
        payload = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-a"}
        self.assertEqual(context(run_hook("session_lock.py", payload)), "")

    def test_warns_about_another_live_session_in_the_same_checkout(self):
        repo = git_repo()
        first = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-a"}
        run_hook("session_lock.py", first)

        second = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-b"}
        message = context(run_hook("session_lock.py", second))
        self.assertIn("session-a", message)
        self.assertIn("worktree", message)

    def test_ignores_a_session_recorded_for_a_different_checkout(self):
        repo = git_repo()
        other_repo = git_repo()
        first = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-a"}
        run_hook("session_lock.py", first)

        second = {
            "hook_event_name": "SessionStart",
            "cwd": other_repo,
            "session_id": "session-b",
        }
        self.assertEqual(context(run_hook("session_lock.py", second)), "")

    def test_removes_the_session_file_on_end(self):
        repo = git_repo()
        start = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-a"}
        run_hook("session_lock.py", start)
        self.assertTrue(os.path.isfile(os.path.join(sessions_dir(repo), "session-a")))

        end = {"hook_event_name": "SessionEnd", "cwd": repo, "session_id": "session-a"}
        run_hook("session_lock.py", end)
        self.assertFalse(os.path.isfile(os.path.join(sessions_dir(repo), "session-a")))

    def test_removes_a_session_file_older_than_a_day(self):
        repo = git_repo()
        directory = sessions_dir(repo)
        os.makedirs(directory, exist_ok=True)
        stale_path = os.path.join(directory, "session-old")
        with open(stale_path, "w", encoding="utf-8") as handle:
            handle.write(f"cwd={repo}\nstarted={int(time.time()) - 90000}\npid=1\n")

        payload = {"hook_event_name": "SessionStart", "cwd": repo, "session_id": "session-new"}
        run_hook("session_lock.py", payload)
        self.assertFalse(os.path.isfile(stale_path))

    def test_skips_silently_outside_a_git_repository(self):
        directory = tempfile.mkdtemp(prefix="session-lock-no-git-")
        payload = {"hook_event_name": "SessionStart", "cwd": directory, "session_id": "session-a"}
        self.assertEqual(context(run_hook("session_lock.py", payload)), "")


if __name__ == "__main__":
    unittest.main()
