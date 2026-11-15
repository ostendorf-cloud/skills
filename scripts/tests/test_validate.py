#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/validate.py."""

import contextlib
import io
import json
import subprocess
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


def git_commit_all(root: Path) -> None:
    """Initialises a git repository at root and commits everything written so far."""
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "chore: init"], cwd=root, check=True, capture_output=True
    )


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

    def test_detects_hook_script_not_directly_under_hooks(self) -> None:
        write(self.root / "hooks" / "sub" / "nested.py", "# a hook\n")
        write(
            self.root / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "nested-hook",
                            "script": "sub/nested.py",
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
        self.assertIn(
            "script 'sub/nested.py' is not a top level file directly under hooks/", output
        )

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

    def test_detects_unknown_key_in_the_repository_config(self) -> None:
        write(
            self.root / "agent-skills.schema.json",
            json.dumps(
                {
                    "$schema": "x",
                    "additionalProperties": False,
                    "properties": {
                        "verify": {"type": "string"},
                        "pr": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"draft": {"type": "boolean"}},
                        },
                    },
                }
            ),
        )
        write(
            self.root / ".agent-skills.json",
            json.dumps({"verify": "task check", "pr": {"draft": "yes"}, "colour": "red"}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn(".agent-skills.json: unknown key colour", output)
        self.assertIn(".agent-skills.json.pr.draft: expected boolean", output)

    def test_accepts_a_repository_config_matching_the_schema(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps(
                {
                    "$schema": "x",
                    "additionalProperties": False,
                    "properties": {
                        "verify": {"type": "string"},
                        "work": {
                            "oneOf": [{"type": "boolean", "const": False}, {"type": "object"}]
                        },
                    },
                }
            ),
        )
        write(self.root / ".agent-skills.json", json.dumps({"verify": "task check", "work": False}))
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")

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

    def test_detects_write_rule_that_the_harness_never_matches(self) -> None:
        write(
            self.root / "settings" / "claude.json",
            json.dumps({"permissions": {"allow": [], "deny": ["Write(~/.claude/settings.json)"]}}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn(
            "'Write(~/.claude/settings.json)' in permissions.deny is never matched", output
        )

    def test_detects_permissions_that_are_not_an_object(self) -> None:
        write(self.root / "settings" / "claude.json", json.dumps({"permissions": ["Bash(ls:*)"]}))
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("claude.json: permissions must be an object", output)

    def test_detects_ask_list_that_is_not_an_array(self) -> None:
        write(
            self.root / "settings" / "claude.json",
            json.dumps({"permissions": {"allow": [], "ask": "Bash(gh pr merge:*)", "deny": []}}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("claude.json: permissions.ask must be an array", output)

    def test_detects_notebook_edit_rule_in_the_ask_list(self) -> None:
        write(
            self.root / "settings" / "claude.json",
            json.dumps(
                {"permissions": {"allow": [], "ask": ["NotebookEdit(docs/**)"], "deny": []}}
            ),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("'NotebookEdit(docs/**)' in permissions.ask is never matched", output)

    def test_detects_write_rule_in_the_local_overlay_example(self) -> None:
        write(
            self.root / "settings" / "local.example.json",
            json.dumps({"permissions": {"deny": ["Write(~/notes/**)"]}}),
        )
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("local.example.json: 'Write(~/notes/**)' in permissions.deny", output)

    def test_allows_a_bare_write_tool_rule(self) -> None:
        write(
            self.root / "settings" / "claude.json",
            json.dumps({"permissions": {"allow": [], "deny": ["Write"]}}),
        )
        _, output = run(self.root)
        self.assertNotIn("is never matched", output)

    def _laptop_profile(self) -> dict:
        path = Path(__file__).resolve().parents[2] / "settings" / "claude.json"
        return json.loads(path.read_text())

    def test_profile_allow_read_is_exactly_code_and_the_known_hosts_files(self) -> None:
        allow_read = self._laptop_profile()["sandbox"]["filesystem"]["allowRead"]
        self.assertEqual(
            sorted(allow_read),
            ["~/.ssh/known_hosts", "~/.ssh/known_hosts2", "~/Code"],
        )

    def test_profile_keeps_ssh_directory_and_key_files_denied(self) -> None:
        profile = self._laptop_profile()
        files = profile["sandbox"]["credentials"]["files"]
        self.assertIn({"path": "~/.ssh", "mode": "deny"}, files)
        deny = profile["permissions"]["deny"]
        for rule in (
            "Read(~/.ssh/**)",
            "Read(**/id_rsa)",
            "Read(**/id_ed25519)",
            "Read(**/*.pem)",
            "Read(**/*.key)",
        ):
            self.assertIn(rule, deny)
        deny_read = profile["sandbox"]["filesystem"]["denyRead"]
        self.assertIn("**/*.pem", deny_read)
        self.assertIn("**/*.key", deny_read)

    def test_profile_sets_xdg_runtime_dir_to_the_harness_temp_dir(self) -> None:
        env = self._laptop_profile()["env"]
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/tmp/claude")

    def test_profile_allows_writing_only_the_macos_user_temp_dirs(self) -> None:
        writes = self._laptop_profile()["sandbox"]["filesystem"]["allowWrite"]
        self.assertIn("/private/var/folders/*/*/T", writes)
        folders = [entry for entry in writes if "var/folders" in entry]
        self.assertEqual(folders, ["/private/var/folders/*/*/T"])

    def test_detects_missing_license_header(self) -> None:
        write(self.root / "scripts" / "helper.py", "print('hi')\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("missing license header", output)

    def test_detects_yml_file(self) -> None:
        write(self.root / ".github" / "workflows" / "lint.yml", "name: lint\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn(
            ".github/workflows/lint.yml: uses the .yml extension, rename to .yaml", output
        )

    def test_ignores_yml_file_inside_worktrees(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        write(self.root / ".worktrees" / "feat-x" / "mise.yml", "tools: {}\n")
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")

    def test_ignores_yml_file_inside_claude_worktrees(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        write(self.root / ".claude" / "worktrees" / "feat-x" / "mise.yml", "tools: {}\n")
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")

    def test_ignores_vendored_yml_in_gitignored_directory(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        write(self.root / ".gitignore", "vendor/\n")
        git_commit_all(self.root)
        write(self.root / "vendor" / "lib.yml", "vendored: true\n")
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")

    def test_detects_untracked_yml_file_in_a_git_repository(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        git_commit_all(self.root)
        write(self.root / ".github" / "workflows" / "lint.yml", "name: lint\n")
        code, output = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn(".github/workflows/lint.yml: uses the .yml extension", output)

    def test_allows_funding_and_dependabot_yml_exceptions(self) -> None:
        self._write_skill()
        self._write_groupings(["myskill"])
        write(self.root / "hooks" / "hooks.json", json.dumps({"version": 1, "hooks": []}))
        write(
            self.root / "agent-skills.schema.json",
            json.dumps({"$schema": "x", "properties": {}}),
        )
        write(self.root / ".github" / "FUNDING.yml", "github: [octocat]\n")
        write(self.root / ".github" / "dependabot.yml", "version: 2\n")
        git_commit_all(self.root)
        code, output = run(self.root)
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
