#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/install.py."""

import contextlib
import io
import json
import py_compile
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _load import load_module

install = load_module("install")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def git_init(path: Path) -> str:
    """Turns path into a one-commit git checkout and returns that commit's hash."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def add_worktree(source: Path, branch: str) -> Path:
    """Adds a git worktree of source on a new branch and returns its path."""
    worktree = source.parent / f"{source.name}-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", branch, str(worktree)],
        cwd=source,
        check=True,
        capture_output=True,
    )
    return worktree


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
            json.dumps(
                {
                    "permissions": {
                        "allow": ["Bash(ls:*)"],
                        "deny": [
                            "Edit({{claude_dir}}/settings.json)",
                            "Edit({{claude_dir}}/CLAUDE.md)",
                            "Edit(~/.config/agent-skills/**)",
                        ],
                    }
                }
            ),
        )
        write(
            self.source / "settings" / "claude-ci.json",
            json.dumps({"permissions": {"allow": [], "deny": []}}),
        )

    def _install(self, *extra: str) -> tuple:
        return run(["install", "--home", str(self.home), "--source", str(self.source), *extra])

    def test_default_install_copies_skill_directory(self) -> None:
        code, _ = self._install()
        self.assertEqual(code, 0)
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.is_dir())
        self.assertFalse(target.is_symlink())
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / install.MARKER_NAME).is_file())

    def test_link_mode_links_skill_into_home_skills_dir(self) -> None:
        code, _ = self._install("--link")
        self.assertEqual(code, 0)
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.is_symlink())
        expected = (self.source / "skills" / "testcat" / "test-skill").resolve()
        self.assertEqual(target.resolve(), expected)

    def test_upgrade_from_a_linked_installation_replaces_the_symlink_with_a_copy(self) -> None:
        self._install("--link")
        target = self.home / ".claude" / "skills" / "test-skill"
        self.assertTrue(target.is_symlink())

        code, output = self._install()
        self.assertEqual(code, 0)
        self.assertIn("test-skill updated", output)
        self.assertFalse(target.is_symlink())
        self.assertTrue(target.is_dir())
        self.assertTrue((target / install.MARKER_NAME).is_file())
        source_skill = self.source / "skills" / "testcat" / "test-skill" / "SKILL.md"
        self.assertEqual((target / "SKILL.md").read_text(), source_skill.read_text())

        state = json.loads((self.home / ".config" / "agent-skills" / "state.json").read_text())
        self.assertEqual(state["mode"], "copy")

    def test_fresh_install_copies_hooks_into_their_own_install_directory(self) -> None:
        code, _ = self._install()
        self.assertEqual(code, 0)
        hooks_dir = self.home / ".claude" / install.OWN_HOOKS_DIRNAME
        self.assertTrue(hooks_dir.is_dir())
        self.assertTrue((hooks_dir / "test_hook.py").is_file())
        self.assertTrue((hooks_dir / install.MARKER_NAME).is_file())

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
        hooks_dir = self.home / ".claude" / install.OWN_HOOKS_DIRNAME
        self.assertIn(str(hooks_dir / "test_hook.py"), command)
        self.assertNotIn(str(self.source), command)

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
        self.assertEqual(state["mode"], "copy")
        self.assertEqual(state["profile"], "laptop")
        self.assertIn("test-skill", state["skills"])

    def test_install_records_the_source_commit_in_state(self) -> None:
        commit = git_init(self.source)
        self._install()
        state = json.loads((self.home / ".config" / "agent-skills" / "state.json").read_text())
        self.assertEqual(state["commit"], commit)

    def test_install_records_no_commit_when_source_is_not_a_git_checkout(self) -> None:
        self._install()
        state = json.loads((self.home / ".config" / "agent-skills" / "state.json").read_text())
        self.assertIsNone(state["commit"])

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
        self._install()
        write(
            self.source / "skills" / "testcat" / "test-skill" / "SKILL.md",
            "---\nname: test-skill\ndescription: changed\n---\nNew body.\n",
        )
        code, output = run(["status", "--home", str(self.home), "--source", str(self.source)])
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

    def test_uninstall_removes_the_copied_skill_and_hooks_directories(self) -> None:
        self._install()
        skill_target = self.home / ".claude" / "skills" / "test-skill"
        hooks_dir = self.home / ".claude" / install.OWN_HOOKS_DIRNAME
        self.assertTrue(skill_target.is_dir())
        self.assertTrue(hooks_dir.is_dir())

        code, output = run(["uninstall", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 0)
        self.assertIn("hooks   removed", output)
        self.assertFalse(skill_target.exists())
        self.assertFalse(hooks_dir.exists())

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

    def test_installation_keeps_working_after_the_source_checkout_is_removed(self) -> None:
        self._install()
        skill_target = self.home / ".claude" / "skills" / "test-skill"
        hooks_dir = self.home / ".claude" / install.OWN_HOOKS_DIRNAME
        hook_script = hooks_dir / "test_hook.py"

        shutil.rmtree(self.source)

        self.assertTrue(skill_target.is_dir())
        self.assertIn("a test skill", (skill_target / "SKILL.md").read_text())
        self.assertTrue(hook_script.is_file())
        py_compile.compile(str(hook_script), doraise=True)

        settings = json.loads((self.home / ".claude" / "settings.json").read_text())
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(str(hook_script), command)

        code, output = run(["doctor", "--home", str(self.home), "--source", str(self.source)])
        self.assertEqual(code, 1)
        self.assertIn(f"fail  recorded source exists ({self.source.resolve()})", output)
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

        code, output = self._install("--link")
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

    def test_install_from_a_worktree_of_the_same_repository_installs_its_skills(self) -> None:
        git_init(self.source)
        self._install()
        worktree = add_worktree(self.source, "feature")

        code, output = run(["install", "--home", str(self.home), "--source", str(worktree)])

        self.assertEqual(code, 0, output)
        self.assertNotIn("conflict", output)
        self.assertIn("test-skill replaced worktree link", output)
        target = self.home / ".claude" / "skills" / "test-skill"
        expected = (worktree / "skills" / "testcat" / "test-skill").resolve()
        self.assertEqual(target.resolve(), expected)

    def test_install_reports_conflict_for_a_symlink_into_an_unrelated_checkout(self) -> None:
        git_init(self.source)
        unrelated = Path(self.tmp.name) / "unrelated"
        write(
            unrelated / "skills" / "testcat" / "test-skill" / "SKILL.md",
            "---\nname: test-skill\ndescription: unrelated\n---\nBody.\n",
        )
        git_init(unrelated)
        foreign_target = unrelated / "skills" / "testcat" / "test-skill"
        target = self.home / ".claude" / "skills" / "test-skill"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(foreign_target, target_is_directory=True)

        code, output = self._install()

        self.assertEqual(code, 1)
        self.assertIn("test-skill conflict", output)
        self.assertEqual(target.resolve(), foreign_target.resolve())

    def test_install_reports_conflict_when_the_worktree_comparison_cannot_be_made(self) -> None:
        # self.source is never turned into a git checkout here, so neither side of
        # the comparison can be made: the installer must fall back to a conflict
        # exactly as it did before the worktree check existed.
        elsewhere = Path(self.tmp.name) / "elsewhere" / "test-skill"
        write(elsewhere / "README.md", "not ours\n")
        target = self.home / ".claude" / "skills" / "test-skill"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(elsewhere, target_is_directory=True)

        code, output = self._install()

        self.assertEqual(code, 1)
        self.assertIn("test-skill conflict", output)
        self.assertEqual(target.resolve(), elsewhere.resolve())

    def test_default_install_uses_unnamed_claude_dir_and_state_paths(self) -> None:
        self._install()

        self.assertTrue((self.home / ".claude" / "skills" / "test-skill").exists())
        claude_md = self.home / ".claude" / "CLAUDE.md"
        self.assertEqual(claude_md.read_text(), "# Baseline\n\nRule one.\n")
        self.assertTrue((self.home / ".claude" / "settings.json").is_file())

        config_dir = self.home / ".config" / "agent-skills"
        self.assertTrue((config_dir / "state.json").is_file())
        self.assertTrue((config_dir / "AGENTS.md").is_file())

        # No target was given: nothing gets a target-prefixed filename.
        self.assertFalse((config_dir / "work.state.json").exists())
        self.assertFalse((config_dir / "work.AGENTS.md").exists())
        self.assertFalse((config_dir / "work.local.json").exists())

    def test_two_targets_in_one_home_do_not_share_state_or_skills(self) -> None:
        personal_dir = self.home / "claude-personal"
        work_dir = self.home / "claude-work"
        config_dir = self.home / ".config" / "agent-skills"

        write(
            config_dir / "work.local.json",
            json.dumps({"permissions": {"allow": ["Bash(echo:*)"]}}),
        )

        self._install("--claude-dir", str(personal_dir))
        self._install("--claude-dir", str(work_dir), "--target", "work")

        self.assertTrue((personal_dir / "skills" / "test-skill").exists())
        self.assertTrue((work_dir / "skills" / "test-skill").exists())

        personal_state = json.loads((config_dir / "state.json").read_text())
        work_state = json.loads((config_dir / "work.state.json").read_text())
        self.assertIn("test-skill", personal_state["skills"])
        self.assertIn("test-skill", work_state["skills"])
        # The default target keeps the bare filename: an empty target must not be
        # prefixed into a dotfile the other commands would never look at.
        self.assertFalse((config_dir / ".state.json").exists())
        self.assertFalse((config_dir / ".AGENTS.md").exists())

        personal_settings = json.loads((personal_dir / "settings.json").read_text())
        work_settings = json.loads((work_dir / "settings.json").read_text())
        self.assertNotIn("Bash(echo:*)", personal_settings["permissions"]["allow"])
        self.assertIn("Bash(echo:*)", work_settings["permissions"]["allow"])

    def test_status_and_doctor_report_against_their_own_target_only(self) -> None:
        personal_dir = self.home / "claude-personal"
        work_dir = self.home / "claude-work"

        self._install("--claude-dir", str(personal_dir))
        self._install("--claude-dir", str(work_dir), "--target", "work")

        personal_status = run(
            [
                "status",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(personal_dir),
            ]
        )
        work_status = run(
            [
                "status",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(work_dir),
                "--target",
                "work",
            ]
        )
        self.assertEqual(personal_status[0], 0)
        self.assertEqual(work_status[0], 0)

        personal_doctor = run(
            [
                "doctor",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(personal_dir),
            ]
        )
        work_doctor = run(
            [
                "doctor",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(work_dir),
                "--target",
                "work",
            ]
        )
        self.assertEqual(personal_doctor[0], 0, personal_doctor[1])
        self.assertEqual(work_doctor[0], 0, work_doctor[1])

        # Drift written straight into one target's CLAUDE.md must not leak into the
        # other target's status check.
        write(work_dir / "CLAUDE.md", "drifted\n")
        personal_status_after = run(
            [
                "status",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(personal_dir),
            ]
        )
        work_status_after = run(
            [
                "status",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(work_dir),
                "--target",
                "work",
            ]
        )
        self.assertEqual(personal_status_after[0], 0)
        self.assertEqual(work_status_after[0], 1)
        self.assertIn("rules   drift", work_status_after[1])

    def test_uninstalling_one_target_leaves_the_other_intact(self) -> None:
        personal_dir = self.home / "claude-personal"
        work_dir = self.home / "claude-work"
        config_dir = self.home / ".config" / "agent-skills"

        self._install("--claude-dir", str(personal_dir))
        self._install("--claude-dir", str(work_dir), "--target", "work")

        work_settings_before = (work_dir / "settings.json").read_text()
        work_claude_md_before = (work_dir / "CLAUDE.md").read_text()

        run(
            [
                "uninstall",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(personal_dir),
            ]
        )

        self.assertFalse((personal_dir / "skills" / "test-skill").exists())
        self.assertFalse((personal_dir / "CLAUDE.md").is_file())
        self.assertFalse((config_dir / "state.json").exists())
        self.assertFalse((config_dir / "AGENTS.md").exists())

        self.assertTrue((work_dir / "skills" / "test-skill").exists())
        self.assertEqual((work_dir / "settings.json").read_text(), work_settings_before)
        self.assertEqual((work_dir / "CLAUDE.md").read_text(), work_claude_md_before)
        self.assertTrue((config_dir / "work.state.json").is_file())
        self.assertTrue((config_dir / "work.AGENTS.md").is_file())

    def _tree(self, root: Path) -> list:
        """Every entry below root with its content, for a before and after comparison."""
        snapshot = []
        for path in sorted(root.rglob("*")):
            name = str(path.relative_to(root))
            if path.is_symlink():
                snapshot.append((name, "link", str(path.readlink())))
            elif path.is_file():
                snapshot.append((name, "file", path.read_text()))
            else:
                snapshot.append((name, "dir", ""))
        return snapshot

    def test_install_records_the_claude_dir_it_installed_into(self) -> None:
        work_dir = self.home / ".claude-work"
        self._install("--claude-dir", str(work_dir), "--target", "work")

        state = json.loads((self.home / ".config" / "agent-skills" / "work.state.json").read_text())
        self.assertEqual(state["claude_dir"], str(work_dir.resolve()))

    def test_uninstall_refuses_a_claude_dir_other_than_the_recorded_one(self) -> None:
        personal_dir = self.home / ".claude-personal"
        work_dir = self.home / ".claude-work"
        self._install("--claude-dir", str(personal_dir))
        self._install("--claude-dir", str(work_dir), "--target", "work")

        personal_before = self._tree(personal_dir)
        work_before = self._tree(work_dir)

        # The work target, but pointed at the personal target's directory.
        code, output = run(
            [
                "uninstall",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--claude-dir",
                str(personal_dir),
                "--target",
                "work",
            ]
        )

        self.assertEqual(code, 1)
        self.assertIn("error", output)
        self.assertIn(str(work_dir.resolve()), output)
        self.assertIn(str(personal_dir.resolve()), output)
        self.assertEqual(self._tree(personal_dir), personal_before)
        self.assertEqual(self._tree(work_dir), work_before)
        config_dir = self.home / ".config" / "agent-skills"
        self.assertTrue((config_dir / "state.json").is_file())
        self.assertTrue((config_dir / "work.state.json").is_file())

    def test_second_target_without_its_own_claude_dir_is_refused(self) -> None:
        self._install()
        claude_dir = self.home / ".claude"
        before = self._tree(claude_dir)

        install_code, install_output = self._install("--target", "work")
        self.assertEqual(install_code, 1)
        self.assertIn("error", install_output)
        self.assertEqual(self._tree(claude_dir), before)

        config_dir = self.home / ".config" / "agent-skills"
        self.assertFalse((config_dir / "work.state.json").exists())

        # The directory still belongs to the default target, so uninstalling the name
        # that was never installed there must not remove the default installation.
        uninstall_code, uninstall_output = run(
            [
                "uninstall",
                "--home",
                str(self.home),
                "--source",
                str(self.source),
                "--target",
                "work",
            ]
        )
        self.assertEqual(uninstall_code, 1)
        self.assertIn("error", uninstall_output)
        self.assertEqual(self._tree(claude_dir), before)
        self.assertTrue((claude_dir / "skills" / "test-skill").exists())
        self.assertTrue((claude_dir / "CLAUDE.md").is_file())
        self.assertTrue((config_dir / "state.json").is_file())

    def test_status_and_doctor_report_a_claude_dir_mismatch(self) -> None:
        personal_dir = self.home / ".claude-personal"
        work_dir = self.home / ".claude-work"
        self._install("--claude-dir", str(personal_dir))
        self._install("--claude-dir", str(work_dir), "--target", "work")

        for command in ("status", "doctor"):
            code, output = run(
                [
                    command,
                    "--home",
                    str(self.home),
                    "--source",
                    str(self.source),
                    "--claude-dir",
                    str(personal_dir),
                    "--target",
                    "work",
                ]
            )
            self.assertEqual(code, 1, output)
            self.assertIn(str(work_dir.resolve()), output)

    def test_installed_settings_protect_the_directory_they_are_installed_into(self) -> None:
        work_dir = self.home / ".claude-work"
        self._install("--claude-dir", str(work_dir), "--target", "work")

        deny = json.loads((work_dir / "settings.json").read_text())["permissions"]["deny"]
        self.assertIn("Edit(~/.claude-work/settings.json)", deny)
        self.assertIn("Edit(~/.claude-work/CLAUDE.md)", deny)
        self.assertNotIn("Edit(~/.claude/settings.json)", deny)
        self.assertNotIn("Edit(~/.claude/CLAUDE.md)", deny)
        self.assertFalse(any(install.CLAUDE_DIR_PLACEHOLDER in entry for entry in deny))

    def test_default_install_keeps_the_home_relative_protection_paths(self) -> None:
        self._install()

        deny = json.loads((self.home / ".claude" / "settings.json").read_text())["permissions"][
            "deny"
        ]
        self.assertIn("Edit(~/.claude/settings.json)", deny)
        self.assertIn("Edit(~/.claude/CLAUDE.md)", deny)

    def test_install_rejects_a_target_that_is_not_a_plain_name(self) -> None:
        for target in ("../../escaped", "a/b", "..", "."):
            code, output = self._install("--target", target)
            self.assertEqual(code, 2, output)
            self.assertIn("invalid --target", output)

        self.assertFalse((self.home / ".config").exists())
        self.assertFalse((self.home / "escaped.state.json").exists())


if __name__ == "__main__":
    unittest.main()
