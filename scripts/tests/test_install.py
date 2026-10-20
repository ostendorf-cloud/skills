#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/install.py."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _load import load_module

install = load_module("install")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run(argv: list) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = install.main(argv)
    return code, out.getvalue()


class InstallTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Named "skills" like a real checkout: the installer recognizes its own hook
        # blocks by a literal "/skills/hooks/" path fragment on re-install.
        self.source = Path(self.tmp.name) / "skills"
        self.home = Path(self.tmp.name) / "home"
        self._write_minimal_source()

    def _write_minimal_source(self) -> None:
        write(
            self.source / "skills" / "testcat" / "test-skill" / "SKILL.md",
            "---\nname: test-skill\ndescription: a test skill\n---\nBody.\n",
        )
        write(
            self.source / "rules" / "baseline.md",
            "# Baseline\n\nRule one.\n",
        )
        write(
            self.source / "hooks" / "hooks.json",
            json.dumps(
                {
                    "version": 1,
                    "hooks": [
                        {
                            "id": "test-hook",
                            "script": "test_hook.py",
                            "event": "PreToolUse",
                            "matcher": "Bash",
                            "timeout": 10,
                            "decision": "deny",
                            "description": "A test hook.",
                        }
                    ],
                }
            ),
        )
        write(self.source / "hooks" / "test_hook.py", "#!/usr/bin/env python3\n")
        write(
            self.source / "settings" / "claude.json",
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": []}}),
        )
        write(
            self.source / "settings" / "claude-ci.json",
            json.dumps({"permissions": {"allow": [], "deny": []}}),
        )

    def _install(self, *extra: str) -> tuple:
        return run(["install", "--home", str(self.home), "--source", str(self.source), *extra])

    def test_install_links_skill_into_home_skills_dir(self) -> None:
        code, _ = self._install()
        self.assertEqual(code, 0)
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.is_symlink())
        expected = (self.source / "skills" / "testcat" / "test-skill").resolve()
        self.assertEqual(target.resolve(), expected)

    def test_copy_mode_copies_skill_directory(self) -> None:
        code, _ = self._install("--copy")
        self.assertEqual(code, 0)
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.is_dir())
        self.assertFalse(target.is_symlink())
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / install.MARKER_NAME).is_file())

    def test_install_writes_rules_file_and_agents_export(self) -> None:
        self._install()
        claude_md = self.home / ".claude" / "CLAUDE.md"
        agents_md = self.home / ".config" / "agent-skills" / "AGENTS.md"
        self.assertEqual(claude_md.read_text(), "# Baseline\n\nRule one.\n")
        self.assertEqual(agents_md.read_text(), "# Baseline\n\nRule one.\n")

    def test_install_backs_up_existing_claude_md_once(self) -> None:
        claude_md = self.home / ".claude" / "CLAUDE.md"
        write(claude_md, "old content\n")
        self._install()
        backup = Path(str(claude_md) + install.BACKUP_SUFFIX)
        self.assertEqual(backup.read_text(), "old content\n")

        # A second drift must not overwrite the first backup.
        claude_md.write_text("drifted again\n")
        self._install()
        self.assertEqual(backup.read_text(), "old content\n")

    def test_install_merges_settings_profile_and_hooks(self) -> None:
        self._install()
        settings = json.loads((self.home / ".claude" / "settings.json").read_text())
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls:*)"])
        block = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(block["matcher"], "Bash")
        command = block["hooks"][0]["command"]
        self.assertIn("python3", command)
        self.assertIn(str(self.source / "hooks" / "test_hook.py"), command)

    def test_install_keeps_foreign_hook_blocks(self) -> None:
        settings_path = self.home / ".claude" / "settings.json"
        write(
            settings_path,
            json.dumps(
                {
                    "hooks": {
                        "Notification": [
                            {"hooks": [{"type": "command", "command": "/usr/local/bin/foo"}]}
                        ]
                    }
                }
            ),
        )
        self._install()
        settings = json.loads(settings_path.read_text())
        self.assertEqual(
            settings["hooks"]["Notification"][0]["hooks"][0]["command"], "/usr/local/bin/foo"
        )

    def test_install_replaces_hook_blocks_from_old_source_path(self) -> None:
        settings_path = self.home / ".claude" / "settings.json"
        old_command = 'python3 "/Users/old/ai-setup/hooks/old_hook.py"'
        write(
            settings_path,
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": old_command}],
                            }
                        ]
                    }
                }
            ),
        )
        self._install()
        settings = json.loads(settings_path.read_text())
        commands = [
            handler["command"]
            for block in settings["hooks"]["PreToolUse"]
            for handler in block["hooks"]
        ]
        self.assertNotIn(old_command, commands)
        self.assertTrue(any("test_hook.py" in command for command in commands))

    def test_install_reports_conflict_for_foreign_skill_directory(self) -> None:
        foreign = self.home / ".claude" / "skills" / "test-skill"
        write(foreign / "README.md", "not ours\n")
        code, output = self._install()
        self.assertEqual(code, 1)
        self.assertIn("conflict", output)
        self.assertEqual((foreign / "README.md").read_text(), "not ours\n")

    def test_install_writes_state_file(self) -> None:
        self._install()
        state = json.loads((self.home / ".config" / "agent-skills" / "state.json").read_text())
        self.assertEqual(state["mode"], "link")
        self.assertEqual(state["profile"], "laptop")
        self.assertIn("test-skill", state["skills"])

    def test_status_in_sync_after_install_returns_zero(self) -> None:
        self._install()
        code, _ = run(["status", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 0)

    def test_status_reports_drift_when_rules_change_upstream(self) -> None:
        self._install()
        write(self.source / "rules" / "baseline.md", "# Baseline\n\nRule two.\n")
        code, output = run(["status", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 1)
        self.assertIn("rules   drift", output)

    def test_status_reports_copy_drift_when_skill_content_changes(self) -> None:
        self._install("--copy")
        write(
            self.source / "skills" / "testcat" / "test-skill" / "SKILL.md",
            "---\nname: test-skill\ndescription: changed\n---\nNew body.\n",
        )
        code, output = run(
            ["status", "--copy", "--home", str(self.home), "--source", str(self.source)]
        )
        self.assertEqual(code, 1)
        self.assertIn("test-skill updated", output)

    def test_uninstall_restores_claude_md_backup(self) -> None:
        claude_md = self.home / ".claude" / "CLAUDE.md"
        write(claude_md, "old content\n")
        self._install()
        run(["uninstall", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(claude_md.read_text(), "old content\n")
        self.assertFalse(Path(str(claude_md) + install.BACKUP_SUFFIX).exists())

    def test_uninstall_removes_tracked_skill_symlink(self) -> None:
        self._install()
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.exists())
        run(["uninstall", "--home", str(self.home), "--source", str(self.source)])
        self.assertFalse(target.exists())
        self.assertFalse(target.is_symlink())

    def test_uninstall_strips_installed_hook_blocks_when_no_backup_exists(self) -> None:
        self._install()
        run(["uninstall", "--home", str(self.home), "--source", str(self.source)])
        settings_path = self.home / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        self.assertNotIn("PreToolUse", settings.get("hooks", {}))

    def test_doctor_reports_missing_hook_script(self) -> None:
        self._install()
        (self.source / "hooks" / "test_hook.py").unlink()
        code, output = run(["doctor", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 1)
        self.assertIn("fail", output)
        self.assertIn("test_hook.py", output)

    def test_doctor_passes_after_a_clean_install(self) -> None:
        self._install()
        code, output = run(["doctor", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 0, output)
        self.assertIn("ok  settings.json contains the hook commands", output)

    def test_status_exits_zero_right_after_install(self) -> None:
        # merge_hooks must emit events in manifest order, the same order a first
        # install writes, or the very next status call reports drift for no reason.
        self._install()
        code, output = run(["status", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 0, output)

    def test_merge_hooks_preserves_manifest_order_over_alphabetical(self) -> None:
        existing = {
            "SessionStart": [{"hooks": [{"type": "command", "command": "a"}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "b"}]}],
        }
        composed = {
            "SessionStart": [{"hooks": [{"type": "command", "command": "a2"}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "b2"}]}],
        }
        merged = install.merge_hooks(existing, composed)
        self.assertEqual(list(merged.keys()), ["SessionStart", "PreToolUse"])

    def test_second_install_with_a_new_hook_does_not_backup_its_own_output(self) -> None:
        self._install()
        hooks_json = json.loads((self.source / "hooks" / "hooks.json").read_text())
        hooks_json["hooks"].append(
            {
                "id": "second-hook",
                "script": "second_hook.py",
                "event": "PreToolUse",
                "matcher": "Bash",
                "timeout": 10,
                "decision": "deny",
                "description": "A second test hook.",
            }
        )
        write(self.source / "hooks" / "hooks.json", json.dumps(hooks_json))
        write(self.source / "hooks" / "second_hook.py", "#!/usr/bin/env python3\n")

        self._install()
        settings_path = self.home / ".claude" / "settings.json"
        backup = Path(str(settings_path) + install.BACKUP_SUFFIX)
        self.assertFalse(backup.exists())

    def test_install_install_uninstall_leaves_no_hook_block(self) -> None:
        self._install()
        self._install()
        run(["uninstall", "--home", str(self.home), "--source", str(self.source)])
        settings_path = self.home / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        commands = [
            handler.get("command", "")
            for blocks in settings.get("hooks", {}).values()
            for block in blocks
            for handler in block.get("hooks", [])
        ]
        self.assertFalse(any(str(self.source) in command for command in commands))

    def test_install_replaces_legacy_skill_symlink(self) -> None:
        legacy_dir = Path(self.tmp.name) / "ai-setup" / "skills" / "testcat" / "test-skill"
        write(legacy_dir / "SKILL.md", "---\nname: test-skill\ndescription: old\n---\nOld.\n")
        target = self.home / ".claude" / "skills" / "test-skill"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(legacy_dir, target_is_directory=True)

        code, output = self._install()
        self.assertEqual(code, 0)
        self.assertIn("test-skill replaced legacy link", output)
        expected = (self.source / "skills" / "testcat" / "test-skill").resolve()
        self.assertEqual(target.resolve(), expected)

    def test_install_removes_legacy_skill_symlink_with_no_replacement(self) -> None:
        legacy_dir = Path(self.tmp.name) / "ai-setup" / "skills" / "testcat" / "old-skill"
        write(legacy_dir / "SKILL.md", "---\nname: old-skill\ndescription: old\n---\nOld.\n")
        target = self.home / ".claude" / "skills" / "old-skill"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(legacy_dir, target_is_directory=True)

        code, output = self._install()
        self.assertEqual(code, 0)
        self.assertIn("old-skill removed legacy link", output)
        self.assertFalse(target.exists())
        self.assertFalse(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
