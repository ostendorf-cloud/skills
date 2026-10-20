#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/validate.py."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _load import load_module

validate = load_module("validate")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run(root: Path) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = validate.main(["--root", str(root)])
    return code, out.getvalue()


LONG_DESCRIPTION = (
    "This skill does something useful for testing and exists only to satisfy "
    "the sixty character minimum that validate enforces on every description."
)


class ValidateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write_skill(self, name: str = "myskill", frontmatter_name: str = "myskill") -> None:
        write(
            self.root / "skills" / "cat" / name / "SKILL.md",
            f"---\nname: {frontmatter_name}\ndescription: {LONG_DESCRIPTION}\n---\nBody.\n",
        )

    def _write_groupings(self, skills: list) -> None:
        write(
            self.root / "skills.sh.json",
            json.dumps(
                {"groupings": [{"title": "Group", "description": "Desc", "skills": skills}]}
            ),
        )

    def test_prints_ok_and_exits_zero_when_clean(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")

    def test_detects_bad_frontmatter_name(self) -> None:
        self._write_skill(name="myskill", frontmatter_name="wrong-name")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("does not match directory name", output)

    def test_detects_short_description(self) -> None:
        write(
            self.root / "skills" / "cat" / "myskill" / "SKILL.md",
            "---\nname: myskill\ndescription: too short\n---\nBody.\n",
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("minimum is 60", output)

    def test_detects_body_too_long(self) -> None:
        body = "\n".join(f"line {i}" for i in range(121))
        write(
            self.root / "skills" / "cat" / "myskill" / "SKILL.md",
            f"---\nname: myskill\ndescription: {LONG_DESCRIPTION}\n---\n{body}\n",
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("maximum is 120", output)

    def test_detects_typographic_quote(self) -> None:
        write(self.root / "README.md", "Text with a ’ curly quote.\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("typographic quote", output)

    def test_detects_emoji(self) -> None:
        write(self.root / "README.md", "Great work \U0001f389 done.\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("emoji", output)

    def test_detects_forbidden_word(self) -> None:
        write(self.root / "scripts" / "forbidden-words.txt", "secretword\n")
        body = "Mentions SecretWord here.\n"
        write(
            self.root / "skills" / "cat" / "myskill" / "SKILL.md",
            f"---\nname: myskill\ndescription: {LONG_DESCRIPTION}\n---\n{body}",
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("forbidden word 'secretword'", output)

    def test_detects_missing_hook_test(self) -> None:
        write(self.root / "hooks" / "my_hook.py", "# a hook\n")
        write(
            self.root / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "my-hook",
                            "script": "my_hook.py",
                            "event": "PreToolUse",
                            "matcher": "",
                            "decision": "deny",
                        }
                    ],
                }
            ),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("no test file hooks/tests/test_my_hook.py", output)

    def test_detects_hook_script_missing_from_disk(self) -> None:
        write(
            self.root / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "ghost-hook",
                            "script": "ghost.py",
                            "event": "PreToolUse",
                            "matcher": "",
                            "decision": "deny",
                        }
                    ],
                }
            ),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("script 'ghost.py' does not exist", output)

    def test_detects_unknown_hook_event_and_decision(self) -> None:
        write(self.root / "hooks" / "odd_hook.py", "# a hook\n")
        write(self.root / "hooks" / "tests" / "test_odd_hook.py", "# a test\n")
        write(
            self.root / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "odd-hook",
                            "script": "odd_hook.py",
                            "event": "OnFullMoon",
                            "matcher": "",
                            "decision": "veto",
                        }
                    ],
                }
            ),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("unknown event 'OnFullMoon'", output)
        self.assertIn("unknown decision 'veto'", output)

    def test_detects_ask_as_an_unknown_decision(self) -> None:
        write(self.root / "hooks" / "ask_hook.py", "# a hook\n")
        write(self.root / "hooks" / "tests" / "test_ask_hook.py", "# a test\n")
        write(
            self.root / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "ask-hook",
                            "script": "ask_hook.py",
                            "event": "PreToolUse",
                            "matcher": "",
                            "decision": "ask",
                        }
                    ],
                }
            ),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("unknown decision 'ask'", output)

    def test_detects_adr_numbering_gap(self) -> None:
        write(self.root / "docs" / "adr" / "0001-first.md", "# First\n")
        write(self.root / "docs" / "adr" / "0003-third.md", "# Third\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("numbering has a gap, expected 0002", output)

    def test_detects_adr_bad_name(self) -> None:
        write(self.root / "docs" / "adr" / "BadName.md", "# Bad\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("name must be NNNN-kebab-title.md", output)

    def test_detects_duplicate_skill_in_groupings(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill", "myskill"])
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("'myskill' is listed more than once", output)

    def test_detects_unlisted_skill(self) -> None:
        self._write_skill()
        write(self.root / "skills.sh.json", json.dumps({"groupings": []}))
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("skill 'myskill' is not listed", output)

    def test_detects_listed_skill_that_does_not_exist(self) -> None:
        self._write_groupings(["ghost-skill"])
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("lists 'ghost-skill', which does not exist", output)

    def test_detects_permission_allow_deny_overlap(self) -> None:
        write(
            self.root / "settings" / "claude.json",
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(ls:*)"]}}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("is in both permissions.allow and permissions.deny", output)

    def test_detects_missing_license_header(self) -> None:
        write(self.root / "scripts" / "helper.py", "print('hi')\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("missing license header", output)


if __name__ == "__main__":
    unittest.main()
