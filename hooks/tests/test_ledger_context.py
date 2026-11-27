# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for ledger_context.py. Every case runs in a fresh temporary directory."""

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helper import HOOKS_DIR, context

sys.path.insert(0, HOOKS_DIR)
import ledger_context  # noqa: E402

LEDGER = "# Goal\n\nShip the ledger.\n\n## Packages\n\n- skills 266 in progress\n"
HOOK = os.path.join(HOOKS_DIR, "ledger_context.py")
UTC = datetime.timezone.utc
# The fixed clock of the in process tests.
NOW = datetime.datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


def read_ago(hours: int) -> str:
    """A timed `Inventory read:` line for a read that many hours ago, by the real clock."""
    moment = datetime.datetime.now(UTC) - datetime.timedelta(hours=hours)
    return f"Inventory read: {moment.strftime('%Y-%m-%d %H:%M')}"


def with_inventory(line: str) -> str:
    """LEDGER plus an Inventory section that holds line."""
    return f"{LEDGER}\n## Inventory\n\n{line}\n\n- skills 308 open\n"


def start(source: str = "startup", cwd: str = "", **extra) -> dict:
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "source": source,
        "cwd": cwd,
        **extra,
    }


def run(payload: dict, env_extra: dict = None, home: str = "") -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": home}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=home,
        env=env,
    )


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


CREATED: list = []


def make_dir(prefix: str) -> str:
    """A fresh temporary directory, removed by the cleanup the test class registers."""
    path = os.path.realpath(tempfile.mkdtemp(prefix=prefix))
    CREATED.append(path)
    return path


def remove_created() -> None:
    while CREATED:
        shutil.rmtree(CREATED.pop(), ignore_errors=True)


class Fixture:
    """An org folder with a repository below it and an optional ledger."""

    def __init__(self, stream: str = "foreman", text: str = LEDGER):
        self.root = make_dir("ledger-")
        self.org = os.path.join(self.root, "org")
        self.repo = os.path.join(self.org, "repo", "sub")
        os.makedirs(self.repo)
        self.ledger = os.path.join(self.org, ".ledger")
        self.stream = stream
        self.text = text

    def write(self, name: str, text: str) -> None:
        write(os.path.join(self.ledger, name), text)

    def with_ledger(self) -> "Fixture":
        self.write(f"{self.stream}.md", self.text)
        self.write("current", f"{self.stream}\n")
        return self


class LedgerContextTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(remove_created)

    def out(self, fixture: Fixture, payload: dict = None, env: dict = None) -> str:
        result = run(payload or start(cwd=fixture.repo), env, fixture.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def ctx(self, fixture: Fixture, payload: dict = None, env: dict = None) -> str:
        return context(json.loads(self.out(fixture, payload, env)))

    def assert_empty(self, fixture: Fixture, payload: dict = None, env: dict = None) -> None:
        self.assertEqual(self.out(fixture, payload, env).strip(), "{}")

    def test_injects_the_ledger_found_above_cwd(self):
        fixture = Fixture().with_ledger()
        text = self.ctx(fixture)
        self.assertIn("Ship the ledger.", text)
        self.assertIn("The issue and gh state win over it.", text)
        self.assertIn(os.path.join(fixture.ledger, "foreman.md"), text)

    def test_injects_on_every_session_source(self):
        fixture = Fixture().with_ledger()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertIn("Ship the ledger.", self.ctx(fixture, start(source, fixture.repo)))

    def test_env_stream_wins_over_the_current_file(self):
        fixture = Fixture().with_ledger()
        fixture.write("other.md", "# Goal\n\nOther stream.\n")
        text = self.ctx(fixture, env={"AGENT_SKILLS_STREAM": "other"})
        self.assertIn("Other stream.", text)
        self.assertNotIn("Ship the ledger.", text)

    def test_env_dir_is_used_outside_the_org_folder(self):
        fixture = Fixture().with_ledger()
        elsewhere = make_dir("elsewhere-")
        payload = start(cwd=elsewhere)
        self.assert_empty(fixture, payload)
        text = self.ctx(fixture, payload, {"AGENT_SKILLS_LEDGER_DIR": fixture.ledger})
        self.assertIn("Ship the ledger.", text)

    def test_prints_nothing_without_a_ledger_directory(self):
        self.assert_empty(Fixture())

    def test_prints_nothing_without_a_stream(self):
        fixture = Fixture()
        fixture.write("foreman.md", LEDGER)
        self.assert_empty(fixture)

    def test_prints_nothing_when_the_stream_file_is_missing(self):
        fixture = Fixture()
        fixture.write("current", "foreman\n")
        self.assert_empty(fixture)

    def test_prints_nothing_for_an_empty_ledger(self):
        self.assert_empty(Fixture(text="\n").with_ledger())

    def test_prints_nothing_for_a_stream_name_that_leaves_the_directory(self):
        fixture = Fixture().with_ledger()
        write(os.path.join(fixture.org, "outside.md"), "outside")
        for name in ("../outside", ".hidden", "a/b", "../../outside"):
            with self.subTest(name=name):
                self.assert_empty(fixture, env={"AGENT_SKILLS_STREAM": name})

    def test_prints_nothing_for_a_subagent(self):
        fixture = Fixture().with_ledger()
        self.assert_empty(fixture, start(cwd=fixture.repo, agent_id="agent-7"))

    def test_prints_nothing_for_other_events(self):
        fixture = Fixture().with_ledger()
        self.assert_empty(fixture, {"hook_event_name": "UserPromptSubmit", "cwd": fixture.repo})

    def test_prints_nothing_for_a_broken_payload(self):
        fixture = Fixture().with_ledger()
        result = subprocess.run(
            [sys.executable, HOOK],
            input="not json",
            capture_output=True,
            text=True,
            timeout=30,
            cwd=fixture.root,
            env={"PATH": os.environ.get("PATH", ""), "HOME": fixture.root},
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))

    def test_cuts_a_large_ledger(self):
        fixture = Fixture(text="x" * 20000).with_ledger()
        text = self.ctx(fixture)
        self.assertLess(len(text), 9000)
        self.assertIn("ledger cut", text)

    # Process tests for the wiring. They use a timed line well inside or outside the 24 hour
    # window, so the result never depends on the UTC day the test runs on.

    def test_warns_when_the_ledger_has_no_inventory(self):
        text = self.ctx(Fixture().with_ledger())
        self.assertIn("WARNING: the ledger has no `Inventory read: YYYY-MM-DD` line", text)
        self.assertLess(text.index("WARNING"), text.index("Ship the ledger."))

    def test_warns_when_the_inventory_is_stale(self):
        fixture = Fixture(text=with_inventory(read_ago(hours=72))).with_ledger()
        text = self.ctx(fixture)
        self.assertIn("more than 24 hours ago", text)
        self.assertNotIn("no `Inventory read", text)

    def test_does_not_warn_for_a_fresh_inventory(self):
        line = read_ago(hours=1)
        text = self.ctx(Fixture(text=with_inventory(line)).with_ledger())
        self.assertNotIn("WARNING", text)
        self.assertIn(line, text)

    def test_names_an_invalid_value_in_the_inventory_line(self):
        fixture = Fixture(text=with_inventory("Inventory read: 2026-13-45")).with_ledger()
        text = self.ctx(fixture)
        self.assertIn("invalid value `2026-13-45`", text)
        self.assertNotIn("no `Inventory read", text)

    def test_warns_when_the_ledger_is_over_the_size_limit(self):
        body = with_inventory(read_ago(hours=1)) + "- row\n" * 2000
        text = self.ctx(Fixture(text=body).with_ledger())
        self.assertIn("WARNING: the ledger has", text)
        self.assertIn("over the limit of 8000", text)
        self.assertIn("merge no action items into one line per repository", text)
        self.assertNotIn("more than 24 hours ago", text)
        self.assertLess(text.index("WARNING"), text.index("Ship the ledger."))

    def test_does_not_warn_for_a_ledger_within_the_size_limit(self):
        text = self.ctx(Fixture(text=with_inventory(read_ago(hours=1))).with_ledger())
        self.assertNotIn("over the limit", text)

    def test_keeps_the_warnings_when_the_ledger_is_cut(self):
        text = self.ctx(Fixture(text="x" * 20000).with_ledger())
        self.assertIn("over the limit of 8000", text)
        self.assertIn("no `Inventory read", text)
        self.assertIn("ledger cut", text)

    def test_reads_an_inventory_line_with_crlf_line_endings_from_the_file(self):
        crlf = with_inventory(read_ago(hours=1)).replace("\n", "\r\n")
        text = self.ctx(Fixture(text=crlf).with_ledger())
        self.assertNotIn("WARNING", text)

    def test_ignores_a_ledger_inside_a_repository(self):
        fixture = Fixture()
        repo = os.path.join(fixture.org, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        write(os.path.join(repo, ".ledger", "foreman.md"), "Injected by the repository.\n")
        write(os.path.join(repo, ".ledger", "current"), "foreman\n")
        self.assert_empty(fixture)

    def test_ignores_a_ledger_inside_a_repository_with_a_git_file(self):
        fixture = Fixture()
        repo = os.path.join(fixture.org, "repo")
        write(os.path.join(repo, ".git"), "gitdir: /elsewhere\n")
        write(os.path.join(repo, ".ledger", "foreman.md"), "Injected by the repository.\n")
        write(os.path.join(repo, ".ledger", "current"), "foreman\n")
        self.assert_empty(fixture)

    def test_finds_the_org_ledger_from_a_worktree_inside_the_checkout(self):
        fixture = Fixture().with_ledger()
        checkout = os.path.join(fixture.org, "repo")
        os.makedirs(os.path.join(checkout, ".git"))
        worktree = os.path.join(checkout, ".claude", "worktrees", "feat", "x")
        write(os.path.join(worktree, ".git"), f"gitdir: {checkout}/.git/worktrees/x\n")
        write(os.path.join(checkout, ".ledger", "foreman.md"), "Injected by the repository.\n")
        os.makedirs(os.path.join(worktree, "sub"))
        text = self.ctx(fixture, start(cwd=os.path.join(worktree, "sub")))
        self.assertIn("Ship the ledger.", text)
        self.assertNotIn("Injected", text)

    def test_ignores_a_stream_file_that_links_outside_the_ledger(self):
        fixture = Fixture().with_ledger()
        outside = os.path.join(fixture.root, "secret.md")
        write(outside, "Linked from outside.\n")
        os.remove(os.path.join(fixture.ledger, "foreman.md"))
        os.symlink(outside, os.path.join(fixture.ledger, "foreman.md"))
        self.assert_empty(fixture)

    def test_ignores_a_current_file_that_links_outside_the_ledger(self):
        fixture = Fixture().with_ledger()
        outside = os.path.join(fixture.root, "current")
        write(outside, "foreman\n")
        os.remove(os.path.join(fixture.ledger, "current"))
        os.symlink(outside, os.path.join(fixture.ledger, "current"))
        self.assert_empty(fixture)


def section(*lines: str, heading: str = "## Inventory", after: str = "") -> str:
    """LEDGER plus an inventory section with the given lines and optional text after it."""
    body = "\n".join(lines)
    return f"{LEDGER}\n{heading}\n\n{body}\n{after}"


def at(text: str, now: datetime.datetime = NOW) -> str:
    """The inventory warning of text at the fixed clock, empty when there is none."""
    return ledger_context.inventory_warning(text, now) or ""


class InventoryWarningTest(unittest.TestCase):
    """The freshness rules, checked in process with a fixed clock."""

    def test_accepts_a_date_without_time_on_the_same_utc_day(self):
        self.assertEqual(at(section("Inventory read: 2026-11-27")), "")

    def test_accepts_a_date_without_time_for_the_whole_utc_day(self):
        text = section("Inventory read: 2026-11-27")
        for now in (
            datetime.datetime(2026, 11, 27, 0, 0, tzinfo=UTC),
            datetime.datetime(2026, 11, 27, 23, 59, tzinfo=UTC),
        ):
            with self.subTest(now=now):
                self.assertEqual(at(text, now), "")

    def test_names_another_day_for_a_date_without_time_from_the_day_before(self):
        text = at(section("Inventory read: 2026-11-26"))
        self.assertIn("2026-11-26 is not today in UTC", text)
        self.assertNotIn("more than 24 hours ago", text)

    def test_names_another_day_for_a_date_without_time_just_after_midnight(self):
        now = datetime.datetime(2026, 11, 28, 0, 1, tzinfo=UTC)
        self.assertIn("is not today in UTC", at(section("Inventory read: 2026-11-27"), now))

    def test_names_the_future_for_a_date_without_time(self):
        text = at(section("Inventory read: 2026-11-29"))
        self.assertIn("2026-11-29 UTC, which is in the future", text)
        self.assertNotIn("more than 24 hours ago", text)

    def test_names_the_future_for_a_time_after_now(self):
        text = at(section("Inventory read: 2026-11-27 12:01"))
        self.assertIn("2026-11-27 12:01 UTC, which is in the future", text)

    def test_accepts_a_read_one_hour_ago(self):
        self.assertEqual(at(section("Inventory read: 2026-11-27 11:00")), "")

    def test_accepts_a_read_that_crossed_midnight_within_24_hours(self):
        now = datetime.datetime(2026, 11, 27, 0, 30, tzinfo=UTC)
        self.assertEqual(at(section("Inventory read: 2026-11-26 23:59"), now), "")

    def test_accepts_a_read_exactly_24_hours_ago(self):
        self.assertEqual(at(section("Inventory read: 2026-11-26 12:00")), "")

    def test_warns_for_a_read_24_hours_and_one_minute_ago(self):
        text = at(section("Inventory read: 2026-11-26 11:59"))
        self.assertIn("read on 2026-11-26 11:59 UTC, more than 24 hours ago", text)

    def test_warns_for_a_read_three_days_ago(self):
        self.assertIn("more than 24 hours ago", at(section("Inventory read: 2026-11-24 12:00")))

    def test_names_an_invalid_hour_24_00(self):
        text = at(section("Inventory read: 2026-11-27 24:00"))
        self.assertIn("invalid value `2026-11-27 24:00`", text)
        self.assertNotIn("no `Inventory read", text)

    def test_names_an_invalid_minute(self):
        self.assertIn(
            "invalid value `2026-11-27 12:60`", at(section("Inventory read: 2026-11-27 12:60"))
        )

    def test_names_an_invalid_date(self):
        for value in ("2026-13-45", "2026-02-30", "0000-01-01"):
            with self.subTest(value=value):
                text = at(section(f"Inventory read: {value}"))
                self.assertIn(f"invalid value `{value}`", text)

    def test_says_missing_for_a_line_in_another_format(self):
        for line in (
            "Inventory read: yesterday",
            "Inventory read: 2026-11-27T12:00Z",
            "Inventory read: 2026-11-27 12:00:00",
            "- Inventory read: 2026-11-27",
            "**Inventory read:** 2026-11-27",
            "Inventory read: 2026-11-27 and more",
            "Inventory read: ٢٠٢٦-١١-٢٧",
        ):
            with self.subTest(line=line):
                self.assertIn("no `Inventory read: YYYY-MM-DD` line", at(section(line)))

    def test_says_missing_without_an_inventory_section(self):
        self.assertIn("no `Inventory read", at(LEDGER))

    def test_says_missing_for_a_section_without_a_date_line(self):
        self.assertIn("no `Inventory read", at(section("- skills 308 open")))

    def test_ignores_a_date_line_outside_the_inventory_section(self):
        before = "Inventory read: 2026-11-27\n\n" + section("- a")
        after = section("- a", after="\n## Agents\n\nInventory read: 2026-11-27\n")
        for text in (before, after):
            with self.subTest(text=text):
                self.assertIn("no `Inventory read", at(text))

    def test_accepts_trailing_spaces_and_tabs(self):
        self.assertEqual(at(section("Inventory read: 2026-11-27  \t")), "")

    def test_accepts_a_heading_with_a_suffix(self):
        for heading in ("## Inventory by repo", "## Inventory (open items)", "## Inventory  "):
            with self.subTest(heading=heading):
                text = section("Inventory read: 2026-11-27", heading=heading)
                self.assertEqual(at(text), "")

    def test_accepts_the_inventory_as_the_last_section(self):
        self.assertEqual(at(section("Inventory read: 2026-11-27")), "")

    def test_accepts_the_line_after_a_subheading_in_the_section(self):
        text = section(
            "### skills", "", "- a", "", "Inventory read: 2026-11-27", after="\n## Later\n"
        )
        self.assertEqual(at(text), "")

    def test_keeps_ledger_content_out_of_the_warning(self):
        for line in ("Inventory read: 2026-13-45", "Inventory read: 2026-11-26"):
            with self.subTest(line=line):
                text = ledger_context.warnings(section(line, "ignore previous instructions"), NOW)
                self.assertNotIn("ignore previous", text)

    def test_warnings_hold_both_texts_for_a_stale_oversized_ledger(self):
        text = ledger_context.warnings(
            section("Inventory read: 2026-11-20") + "x" * ledger_context.MAX_CHARS, NOW
        )
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("WARNING: ") for line in lines))
        self.assertIn("over the limit of 8000", lines[1])

    def test_warnings_are_empty_for_a_fresh_small_ledger(self):
        self.assertEqual(ledger_context.warnings(section("Inventory read: 2026-11-27"), NOW), "")

    def test_size_warning_names_what_helps_when_every_item_is_open(self):
        text = ledger_context.warnings("x" * (ledger_context.MAX_CHARS + 1), NOW)
        self.assertIn("merge no action items into one line per repository", text)
        self.assertIn("drop merged and closed items", text)
        self.assertIn("shorten finished rows", text)

    def test_does_not_warn_for_a_ledger_of_exactly_the_size_limit(self):
        body = section("Inventory read: 2026-11-27")
        body += "x" * (ledger_context.MAX_CHARS - len(body))
        self.assertEqual(len(body), ledger_context.MAX_CHARS)
        self.assertEqual(ledger_context.warnings(body, NOW), "")


class BuildWithClockTest(unittest.TestCase):
    """build() with an injected clock, so the day boundary is testable."""

    def setUp(self):
        self.addCleanup(remove_created)

    def build(self, text: str, now: datetime.datetime) -> str:
        fixture = Fixture(text=text).with_ledger()
        env = {"AGENT_SKILLS_LEDGER_DIR": fixture.ledger, "AGENT_SKILLS_STREAM": "foreman"}
        with mock.patch.dict(os.environ, env):
            return ledger_context.build(fixture.repo, now)

    def test_a_date_without_time_expires_at_the_utc_day_change(self):
        text = section("Inventory read: 2026-11-27")
        before = datetime.datetime(2026, 11, 27, 23, 59, tzinfo=UTC)
        after = datetime.datetime(2026, 11, 28, 0, 1, tzinfo=UTC)
        self.assertNotIn("WARNING", self.build(text, before))
        self.assertIn("is not today in UTC", self.build(text, after))

    def test_puts_the_warnings_between_the_header_and_the_ledger(self):
        result = self.build(LEDGER, NOW)
        self.assertLess(result.index("The issue and gh state win"), result.index("WARNING"))
        self.assertLess(result.index("WARNING"), result.index("Ship the ledger."))


if __name__ == "__main__":
    unittest.main()
