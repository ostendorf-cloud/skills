# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for ask_owner.py.

The transcript fixtures copy the record shapes of a real Claude Code session, with
synthetic content: a user record holds a string or a text item, a tool result is a user
record whose content holds a tool_result item, and a question tool call is a tool_use
block named AskUserQuestion inside an assistant record.
"""

import json
import os
import tempfile
import unittest
from typing import Any, Optional

from helper import run_hook

STATUS_TABLE = (
    "| Repo | Issue | Status | Next |\n"
    "|---|---|---|---|\n"
    "| skills | 295 | review | **Merge PR 301** |\n"
)


def user(text: str = "continue", meta: bool = False) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
    }
    if meta:
        record["isMeta"] = True
    return record


def tool_result() -> dict[str, Any]:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
        },
    }


def assistant(*items: dict[str, Any], sidechain: bool = False) -> dict[str, Any]:
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "content": list(items)},
    }


TEXT = {"type": "text", "text": "Done."}
BASH = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}
ASK = {
    "type": "tool_use",
    "id": "t2",
    "name": "AskUserQuestion",
    "input": {"questions": [{"question": "Merge?", "options": []}]},
}


class AskOwnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="ask-owner-")
        self.transcript = os.path.join(self.tmp, "transcript.jsonl")

    def stop(
        self,
        message: str,
        records: list,
        env_extra: Optional[dict[str, str]] = None,
        **extra: Any,
    ) -> dict[str, Any]:
        with open(self.transcript, "w", encoding="utf-8") as handle:
            handle.write("\n".join(json.dumps(r) for r in records) + "\n")
        env = {k: v for k, v in os.environ.items() if k != "CI"}
        env.update(env_extra or {})
        payload = {
            "hook_event_name": "Stop",
            "session_id": "session-a",
            "transcript_path": self.transcript,
            "last_assistant_message": message,
            "stop_hook_active": False,
            **extra,
        }
        return run_hook("ask_owner.py", payload, env=env)

    def test_allows_a_bold_owner_step_when_the_turn_asked(self):
        records = [user(), assistant(ASK), tool_result(), assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_blocks_a_bold_owner_step_without_a_question_tool_call(self):
        records = [user(), assistant(BASH), tool_result(), assistant(TEXT)]
        output = self.stop(STATUS_TABLE, records)
        self.assertEqual(output.get("decision"), "block")
        self.assertIn("question tool", output.get("reason", ""))

    def test_blocks_a_line_that_starts_with_a_bold_span(self):
        records = [user(), assistant(TEXT)]
        output = self.stop("**Now for you:** merge the pull request.\n", records)
        self.assertEqual(output.get("decision"), "block")

    def test_a_question_in_an_earlier_turn_does_not_count(self):
        records = [user(), assistant(ASK), tool_result(), user("next"), assistant(TEXT)]
        output = self.stop(STATUS_TABLE, records)
        self.assertEqual(output.get("decision"), "block")

    def test_a_meta_user_record_does_not_start_a_turn(self):
        records = [
            user(),
            assistant(ASK),
            tool_result(),
            user("reminder", meta=True),
            assistant(TEXT),
        ]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_a_task_notification_after_the_question_does_not_start_a_turn(self):
        notice = user("<task-notification>\n<task-id>b1</task-id>\n</task-notification>")
        records = [user(), assistant(ASK), tool_result(), notice, assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_a_task_notification_in_a_text_item_does_not_start_a_turn(self):
        notice = user()
        notice["message"]["content"] = [
            {"type": "text", "text": "<task-notification>x</task-notification>"}
        ]
        records = [user(), assistant(ASK), tool_result(), notice, assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_a_record_with_an_origin_does_not_start_a_turn(self):
        peer = user("[Subagent hand-back] report")
        peer["origin"] = {"kind": "peer"}
        records = [user(), assistant(ASK), tool_result(), peer, assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_a_typed_prompt_with_a_human_origin_starts_a_turn(self):
        typed = user("next question")
        typed["origin"] = {"kind": "human"}
        records = [user(), assistant(ASK), tool_result(), assistant(TEXT), typed, assistant(TEXT)]
        output = self.stop(STATUS_TABLE, records)
        self.assertEqual(output.get("decision"), "block")

    def test_a_task_notification_origin_does_not_start_a_turn(self):
        notice = user("finished")
        notice["origin"] = {"kind": "task-notification", "producer": "bash", "runId": "r1"}
        records = [user(), assistant(ASK), tool_result(), notice, assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records), {})

    def test_blocks_a_bold_step_in_a_list_item_or_quote(self):
        records = [user(), assistant(TEXT)]
        for line in (
            "- **Merge PR 298**",
            "* **Merge PR 298**",
            "+ **Merge PR 298**",
            "1. **Merge PR 298**",
            "> **Merge PR 298**",
            "  - **Merge PR 298**",
        ):
            with self.subTest(line=line):
                output = self.stop(f"For you now:\n{line}\n", records)
                self.assertEqual(output.get("decision"), "block")

    def test_allows_a_list_item_with_bold_in_the_middle(self):
        message = "- Check that **CI** is green.\n"
        self.assertEqual(self.stop(message, [user(), assistant(TEXT)]), {})

    def test_a_subagent_record_is_ignored(self):
        records = [user(), assistant(ASK, sidechain=True), assistant(TEXT)]
        output = self.stop(STATUS_TABLE, records)
        self.assertEqual(output.get("decision"), "block")

    def test_allows_bold_in_the_middle_of_a_sentence(self):
        records = [user(), assistant(TEXT)]
        self.assertEqual(self.stop("The check is **green** on the head.\n", records), {})

    def test_allows_a_bold_table_header_row(self):
        message = "| **Repo** | **Status** |\n|---|---|\n| skills | review |\n"
        self.assertEqual(self.stop(message, [user(), assistant(TEXT)]), {})

    def test_allows_a_heading_and_bold_inside_code(self):
        message = "## **Status**\n\n```\n**Merge**\n```\nNothing to do for you.\n"
        self.assertEqual(self.stop(message, [user(), assistant(TEXT)]), {})

    def test_silent_when_unattended(self):
        records = [user(), assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records, env_extra={"CI": "true"}), {})

    def test_silent_when_the_stop_was_already_blocked(self):
        records = [user(), assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records, stop_hook_active=True), {})

    def test_silent_for_a_subagent(self):
        records = [user(), assistant(TEXT)]
        self.assertEqual(self.stop(STATUS_TABLE, records, agent_id="a1"), {})
        self.assertEqual(self.stop(STATUS_TABLE, records, agent_type="implementer"), {})

    def test_silent_when_the_transcript_is_missing(self):
        output = run_hook(
            "ask_owner.py",
            {
                "hook_event_name": "Stop",
                "transcript_path": os.path.join(self.tmp, "absent.jsonl"),
                "last_assistant_message": STATUS_TABLE,
            },
        )
        self.assertEqual(output, {})


if __name__ == "__main__":
    unittest.main()
