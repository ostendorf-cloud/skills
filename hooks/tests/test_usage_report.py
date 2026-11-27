# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for usage_report.py. The fixture is synthetic, never a real transcript."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helper import HOOKS_DIR

sys.path.insert(0, HOOKS_DIR)
import usage_report  # noqa: E402

SCRIPT = os.path.join(HOOKS_DIR, "usage_report.py")
SECRET_TEXT = "SECRET-PROMPT-TEXT-DO-NOT-PRINT"
SESSION = "aaaaaaaa-1111-2222-3333-444444444444"


def assistant(ts, model, usage, msg_id, cwd="/work/skills", agent_id=None, agent=None):
    record = {
        "type": "assistant",
        "sessionId": SESSION,
        "timestamp": ts,
        "cwd": cwd,
        "requestId": f"req-{msg_id}",
        "isSidechain": agent_id is not None,
        "message": {
            "id": msg_id,
            "model": model,
            "content": [{"type": "text", "text": SECRET_TEXT}],
            "usage": {
                "input_tokens": usage[0],
                "output_tokens": usage[1],
                "cache_read_input_tokens": usage[2],
                "cache_creation_input_tokens": usage[3],
            },
        },
    }
    if agent_id:
        record["agentId"] = agent_id
        record["attributionAgent"] = agent
    return record


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def build_fixture(root: Path):
    project = root / "-work-skills"
    main = [
        assistant("2026-11-20T10:00:00.000Z", "claude-opus-5-5", (10, 100, 0, 200000), "m1"),
        assistant("2026-11-20T10:00:05.000Z", "claude-opus-5-5", (5, 50, 200000, 1000), "m2"),
        # Same message written twice while streaming: counted once.
        assistant("2026-11-20T10:00:05.000Z", "claude-opus-5-5", (5, 50, 200000, 1000), "m2"),
        # Rebuild after an idle gap of more than five minutes.
        assistant("2026-11-21T09:00:00.000Z", "claude-opus-5-5", (1, 20, 0, 150000), "m3"),
        {"type": "user", "sessionId": SESSION, "message": {"content": SECRET_TEXT}},
        {
            "type": "system",
            "subtype": "compact_boundary",
            "sessionId": SESSION,
            "compactMetadata": {"trigger": "auto", "preTokens": 900000, "postTokens": 20000},
        },
        "not json at all",
    ]
    path = project / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) if isinstance(r, dict) else r for r in main]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sub = project / SESSION / "subagents"
    write_jsonl(
        sub / "agent-abc12345.jsonl",
        [
            assistant(
                "2026-11-20T10:01:00.000Z",
                "claude-sonnet-5-5",
                (3, 30, 1000, 500),
                "s1",
                agent_id="abc12345",
                agent="implementer",
            ),
            assistant(
                "2026-11-20T10:01:10.000Z",
                "claude-sonnet-5-5",
                (3, 40, 1500, 0),
                "s2",
                agent_id="abc12345",
                agent="implementer",
            ),
        ],
    )
    (sub / "agent-abc12345.meta.json").write_text(json.dumps({"agentType": "implementer"}))


def run_report(root, *extra):
    return subprocess.run(
        [sys.executable, SCRIPT, "--root", str(root), "--days", "0", *extra],
        capture_output=True,
        text=True,
        timeout=30,
    )


class UsageReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        build_fixture(self.root)

    def test_collects_each_request_once(self):
        requests, compactions = usage_report.collect(self.root)
        self.assertEqual(len(requests), 5)
        self.assertEqual(len(compactions), 1)
        self.assertEqual(compactions[0].pre_tokens, 900000)

    def test_marks_subagent_requests_with_their_type(self):
        requests, _ = usage_report.collect(self.root)
        subs = [r for r in requests if r.kind == "subagent"]
        self.assertEqual({r.agent_type for r in subs}, {"implementer"})
        self.assertEqual(len(subs), 2)

    def test_prints_every_table(self):
        result = run_report(self.root, "--miss-threshold", "100000")
        self.assertEqual(result.returncode, 0, result.stderr)
        for title in (
            "## By session",
            "## By kind and model",
            "## By agent type",
            "## By day (UTC)",
            "## By repository",
            "## Cache misses",
            "## Agents by length",
            "## Main session prompt size",
        ):
            self.assertIn(title, result.stdout)

    def test_never_prints_message_content(self):
        result = run_report(self.root)
        self.assertNotIn(SECRET_TEXT, result.stdout)
        self.assertNotIn(SECRET_TEXT, result.stderr)

    def test_sums_tokens_by_kind(self):
        requests, _ = usage_report.collect(self.root)
        groups = usage_report.grouped(requests, lambda r: r.kind, {})
        self.assertEqual(groups["main"].count, 3)
        self.assertEqual(groups["main"].output, 170)
        self.assertEqual(groups["subagent"].output, 70)
        self.assertEqual(groups["subagent"].cache_read, 2500)

    def test_counts_cache_misses_after_an_idle_gap(self):
        requests, _ = usage_report.collect(self.root)
        text = usage_report.cache_misses(requests, 100000, 0)
        self.assertIn("aaaaaaaa", text)
        # Two rebuilds, one of them after more than five minutes.
        row = [line for line in text.splitlines() if "aaaaaaaa" in line][0]
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[1:], ["2", "1", "350,000"])

    def test_reports_compaction_size_and_peak_prompt(self):
        requests, compactions = usage_report.collect(self.root)
        text = usage_report.prompt_sizes(requests, compactions, 0)
        self.assertIn("900,000", text)
        self.assertIn("201,005", text)

    def test_folds_a_worktree_into_its_repository(self):
        name = usage_report.repository_name("/home/x/skills/.claude/worktrees/fix/258-a")
        self.assertEqual(name, "skills")
        self.assertEqual(usage_report.repository_name(""), "unknown")

    def test_cost_needs_a_price_file(self):
        self.assertIn("Cost is not shown", run_report(self.root).stdout)
        prices = self.root / "prices.json"
        prices.write_text(
            json.dumps({"opus": {"input": 10, "output": 100, "cache_read": 1, "cache_create": 12}})
        )
        result = run_report(self.root, "--prices", str(prices))
        self.assertNotIn("Cost is not shown", result.stdout)
        self.assertIn("cost", result.stdout)
        self.assertIn("n/a", result.stdout)

    def test_filters_by_session_prefix_and_repository(self):
        none = run_report(self.root, "--session", "zzzz")
        self.assertEqual(none.stdout.count("No data."), 8)
        other = run_report(self.root, "--repository", "other")
        self.assertIn("No data.", other.stdout)

    def test_empty_root_prints_empty_tables(self):
        with tempfile.TemporaryDirectory() as empty:
            result = run_report(empty)
        self.assertEqual(result.returncode, 0)
        self.assertIn("No data.", result.stdout)


if __name__ == "__main__":
    unittest.main()
