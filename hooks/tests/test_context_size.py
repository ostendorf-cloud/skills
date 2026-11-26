# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for context_size.py."""

import json
import os
import tempfile
import unittest
from typing import Optional

from helper import context, run_hook


def record(tokens: int, sidechain: bool = False, kind: str = "assistant") -> str:
    """A transcript line whose usage sums to tokens."""
    usage = {
        "input_tokens": 2,
        "cache_creation_input_tokens": 24155,
        "cache_read_input_tokens": tokens - 24157,
        "output_tokens": 603,
    }
    return json.dumps(
        {"type": kind, "isSidechain": sidechain, "message": {"usage": usage}},
    )


class ContextSizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="context-size-")
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")
        self.state_dir = os.path.join(self.tmp, "state")
        os.makedirs(self.state_dir)

    def write(self, lines: list, path: Optional[str] = None) -> None:
        with open(path or self.transcript, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def run_prompt(self, session: str = "session-a", warn: Optional[str] = None, **extra) -> str:
        env = {**os.environ, "TMPDIR": self.state_dir}
        env.pop("AGENT_SKILLS_CONTEXT_WARN", None)
        if warn is not None:
            env["AGENT_SKILLS_CONTEXT_WARN"] = warn
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "transcript_path": self.transcript,
            "prompt": "continue",
            **extra,
        }
        return context(run_hook("context_size.py", payload, env=env))

    def test_stays_quiet_below_the_threshold(self):
        self.write([record(149999)])
        self.assertEqual(self.run_prompt(), "")

    def test_warns_at_the_threshold(self):
        self.write([record(150000)])
        message = self.run_prompt()
        self.assertIn("150k", message)
        self.assertIn("handoff", message)
        self.assertIn("/clear", message)

    def test_warns_only_once_within_the_same_band(self):
        self.write([record(150000)])
        self.assertNotEqual(self.run_prompt(), "")
        self.write([record(150000), record(199000)])
        self.assertEqual(self.run_prompt(), "")

    def test_warns_again_in_the_next_band(self):
        self.write([record(150000)])
        self.assertNotEqual(self.run_prompt(), "")
        self.write([record(150000), record(200000)])
        self.assertIn("200k", self.run_prompt())

    def test_keeps_the_band_per_session(self):
        self.write([record(160000)])
        self.assertNotEqual(self.run_prompt(session="a"), "")
        self.assertNotEqual(self.run_prompt(session="b"), "")

    def test_warns_again_after_the_context_shrank_below_the_threshold(self):
        self.write([record(160000)])
        self.assertNotEqual(self.run_prompt(), "")
        self.write([record(160000), record(30000)])
        self.assertEqual(self.run_prompt(), "")
        self.write([record(160000), record(30000), record(160000)])
        self.assertNotEqual(self.run_prompt(), "")

    def test_zero_disables_the_warning(self):
        self.write([record(400000)])
        self.assertEqual(self.run_prompt(warn="0"), "")

    def test_environment_overrides_the_threshold(self):
        self.write([record(60000)])
        self.assertEqual(self.run_prompt(), "")
        self.assertIn("60k", self.run_prompt(warn="50000"))

    def test_invalid_threshold_falls_back_to_the_default(self):
        self.write([record(160000)])
        self.assertNotEqual(self.run_prompt(warn="lots"), "")

    def test_stays_quiet_when_the_transcript_is_missing(self):
        self.assertEqual(self.run_prompt(), "")

    def test_stays_quiet_without_a_transcript_path(self):
        env = {**os.environ, "TMPDIR": self.state_dir}
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "a"}
        self.assertEqual(context(run_hook("context_size.py", payload, env=env)), "")

    def test_skips_garbage_lines(self):
        self.write([record(170000), "not json", "{broken", '{"usage": 1}', "[1, 2]", ""])
        self.assertIn("170k", self.run_prompt())

    def test_skips_sidechain_records(self):
        self.write([record(170000), record(20000, sidechain=True)])
        self.assertIn("170k", self.run_prompt())

    def test_ignores_records_that_are_not_assistant_records(self):
        self.write([record(170000), record(20000, kind="user")])
        self.assertIn("170k", self.run_prompt())

    def test_uses_the_last_assistant_record(self):
        self.write([record(170000), record(40000)])
        self.assertEqual(self.run_prompt(), "")

    def test_stays_quiet_for_a_subagent_payload(self):
        self.write([record(170000)])
        self.assertEqual(self.run_prompt(agent_id="agent-1"), "")

    def test_warns_when_the_state_file_cannot_be_written(self):
        self.write([record(170000)])
        # A directory where the state file belongs makes the read and the write fail.
        os.makedirs(os.path.join(self.state_dir, "agent-skills-context-a.json"))
        env = {**os.environ, "TMPDIR": self.state_dir}
        env.pop("AGENT_SKILLS_CONTEXT_WARN", None)
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "a",
            "transcript_path": self.transcript,
        }
        self.assertIn("170k", context(run_hook("context_size.py", payload, env=env)))

    def test_reads_a_large_file_only_from_its_tail(self):
        # About 40 MB of lines before the last record. The first line is a record that
        # would warn if the head were read, and the last record is below the threshold.
        filler = json.dumps({"type": "user", "message": {"content": "x" * 1_000_000}})
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write(record(400000) + "\n")
            for _ in range(40):
                handle.write(filler + "\n")
            handle.write(record(20000) + "\n")
        self.assertEqual(self.run_prompt(), "")

    def test_finds_a_record_that_spans_several_chunks(self):
        big = json.dumps(
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "content": "y" * 300_000,
                    "usage": {"input_tokens": 170000},
                },
            }
        )
        self.write([record(20000), big])
        self.assertIn("170k", self.run_prompt())


if __name__ == "__main__":
    unittest.main()
