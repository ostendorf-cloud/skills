#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Install, update and check the skills baseline for Claude Code."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_SUFFIX = ".before-agent-skills"
# Stands in for the directory an install writes into, wherever the shipped settings name it.
CLAUDE_DIR_PLACEHOLDER = "{{claude_dir}}"
MARKER_NAME = ".agent-skills-checksum"
OWN_HOOK_MARKERS = ("/ai-setup/hooks/", "/skills/hooks/")
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
LEGACY_SKILL_MARKER = "/ai-setup/skills/"


@dataclass
class Skill:
    """One skill directory found in the source tree."""

    name: str
    category: str
    path: Path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def target_file(home: Path, target: str, name: str) -> Path:
    """Path to a home-anchored, per-target file. Empty target keeps today's bare filename."""
    filename = f"{target}.{name}" if target else name
    return home / ".config" / "agent-skills" / filename


def target_label(target: str) -> str:
    return f"target '{target}'" if target else "the default target"


def resolve_dir(path: Path) -> Path:
    return path.expanduser().resolve()


def source_commit(source: Path) -> str | None:
    """The commit source's checkout is at, or None when it is not a git checkout.

    Recorded into the state file so a session-start hook can later tell an installed
    copy apart from the checkout it came from, offline and without trusting a
    timestamp.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def read_state(home: Path, target: str) -> dict[str, Any] | None:
    path = target_file(home, target, "state.json")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def installed_targets(home: Path) -> list[tuple[str, dict[str, Any]]]:
    """Every target that has a state file in this home, as (target name, state) pairs."""
    config_dir = home / ".config" / "agent-skills"
    if not config_dir.is_dir():
        return []
    names = [path.name[: -len(".state.json")] for path in sorted(config_dir.glob("*.state.json"))]
    if (config_dir / "state.json").is_file():
        names.insert(0, "")
    found: list[tuple[str, dict[str, Any]]] = []
    for name in names:
        state = read_state(home, name)
        if state is not None:
            found.append((name, state))
    return found


def claude_dir_mismatch(home: Path, target: str, claude_dir: Path) -> str | None:
    """Compare the claude_dir recorded at install time against the one this run asks for.

    Returns an error message when they differ. Returns None when they match, when the
    target has no state file, or when the state file predates the recorded field.
    """
    state = read_state(home, target)
    if not state:
        return None
    recorded = state.get("claude_dir")
    if not recorded:
        return None
    wanted = resolve_dir(claude_dir)
    if Path(recorded) == wanted:
        return None
    return (
        f"{target_label(target)} was installed into {recorded}, "
        f"but --claude-dir points at {wanted}. "
        "Pass the recorded --claude-dir, or the --target that owns this directory. "
        "To move a target, uninstall it first. Nothing was changed."
    )


def claude_dir_owner(home: Path, target: str, claude_dir: Path) -> str | None:
    """Returns an error message when another target already owns claude_dir.

    A directory belongs to exactly one target. Without this check a second target
    installed into the same directory overwrites the first one's files and its uninstall
    then removes them.
    """
    wanted = resolve_dir(claude_dir)
    for name, state in installed_targets(home):
        if name == target:
            continue
        recorded = state.get("claude_dir")
        if recorded and Path(recorded) == wanted:
            return (
                f"{wanted} is the installation of {target_label(name)}, "
                f"not of {target_label(target)}. Point --claude-dir at a directory of its "
                "own, or name the owning target with --target. Nothing was changed."
            )
    return None


def discover_skills(source: Path) -> list[Skill]:
    skills_root = source / "skills"
    if not skills_root.is_dir():
        return []
    skills: list[Skill] = []
    for category_dir in sorted(skills_root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue
        for skill_dir in sorted(category_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skills.append(Skill(name=skill_dir.name, category=category_dir.name, path=skill_dir))
    return skills


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(file.relative_to(path).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def inspect_target(target: Path, source: Path) -> str:
    """Classify an installed skill entry: missing, stale, owned_link, owned_copy,
    legacy, conflict.

    "legacy" is a symlink the previous installer created, pointing into a checkout
    path that still contains "/ai-setup/skills/" rather than this installer's source.
    """
    if target.is_symlink():
        if not target.exists():
            return "stale"
        resolved = target.resolve()
        try:
            resolved.relative_to(source.resolve())
        except ValueError:
            if LEGACY_SKILL_MARKER in str(resolved):
                return "legacy"
            return "conflict"
        return "owned_link"
    if not target.exists():
        return "missing"
    if target.is_dir():
        if (target / MARKER_NAME).is_file():
            return "owned_copy"
        return "conflict"
    return "conflict"


def install_skill(skill: Skill, target: Path, mode: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        target.symlink_to(skill.path, target_is_directory=True)
        return
    shutil.copytree(skill.path, target)
    (target / MARKER_NAME).write_text(tree_hash(skill.path) + "\n")


def sync_skill(skill: Skill, skills_dir: Path, source: Path, mode: str, dry_run: bool) -> str:
    """Bring one skill entry in line with the source. Returns one of the sync states."""
    target = skills_dir / skill.name
    state = inspect_target(target, source)

    if state == "conflict":
        return "conflict"

    if state in ("missing", "stale"):
        if not dry_run:
            if state == "stale":
                target.unlink()
            install_skill(skill, target, mode)
        return "installed"

    if state == "legacy":
        if not dry_run:
            target.unlink()
            install_skill(skill, target, mode)
        return "replaced legacy link"

    if state == "owned_link":
        if mode == "link" and target.resolve() == skill.path.resolve():
            return "unchanged"
        if not dry_run:
            target.unlink()
            install_skill(skill, target, mode)
        return "updated"

    # state == "owned_copy"
    if mode == "copy":
        marker = target / MARKER_NAME
        current = marker.read_text().strip() if marker.is_file() else None
        if current == tree_hash(skill.path):
            return "unchanged"
    if not dry_run:
        shutil.rmtree(target)
        install_skill(skill, target, mode)
    return "updated"


def prune_skills(
    skills_dir: Path, keep: set[str], source: Path, dry_run: bool
) -> list[tuple[str, str]]:
    """Remove managed skill entries that are no longer in the source.

    Returns (name, status) pairs, status being "removed" or, for a legacy link with no
    replacement among the current skills, "removed legacy link".
    """
    removed: list[tuple[str, str]] = []
    if not skills_dir.is_dir():
        return removed
    for entry in sorted(skills_dir.iterdir()):
        if entry.name in keep or entry.name.startswith("."):
            continue
        state = inspect_target(entry, source)
        if state not in ("owned_link", "owned_copy", "stale", "legacy"):
            continue
        if not dry_run:
            if entry.is_symlink() or entry.is_file():
                entry.unlink()
            else:
                shutil.rmtree(entry)
        status = "removed legacy link" if state == "legacy" else "removed"
        removed.append((entry.name, status))
    return removed


def normalize_text(content: str) -> str:
    return content.strip() + "\n"


def install_rules(source: Path, claude_dir: Path, dry_run: bool) -> tuple[str, str | None]:
    """Write rules/baseline.md to claude_dir/CLAUDE.md. Returns (action, backup path or None)."""
    content = normalize_text((source / "rules" / "baseline.md").read_text())
    dest = claude_dir / "CLAUDE.md"
    backup = Path(str(dest) + BACKUP_SUFFIX)

    if not dest.is_file():
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        return "created", None

    existing = dest.read_text()
    if existing == content:
        return "unchanged", None

    backed_up = None
    if not backup.is_file():
        backed_up = str(backup)
        if not dry_run:
            backup.write_text(existing)
    if not dry_run:
        dest.write_text(content)
    return "overwritten", backed_up


def export_agents(source: Path, home: Path, target: str, dry_run: bool) -> None:
    content = normalize_text((source / "rules" / "baseline.md").read_text())
    dest = target_file(home, target, "AGENTS.md")
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)


def deep_merge(base: Any, overlay: Any) -> Any:
    """Recursively merge overlay onto base. Dicts recurse, everything else is replaced."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    return overlay


def claude_dir_rule_path(claude_dir: Path, home: Path) -> str:
    """Render claude_dir for a permission rule: home relative as "~/..." so the installed
    file still works on another machine, absolute when it sits outside home."""
    expanded = claude_dir.expanduser()
    for base in (home.expanduser(), resolve_dir(home)):
        try:
            return "~/" + expanded.relative_to(base).as_posix()
        except ValueError:
            continue
    return str(expanded)


def substitute_claude_dir(value: Any, rule_path: str) -> Any:
    """Replace the claude_dir placeholder in every string of a settings tree.

    The shipped profile cannot name the install directory, so rules that protect a
    target's own settings.json and CLAUDE.md carry the placeholder and are bound to the
    directory this run installs into.
    """
    if isinstance(value, str):
        return value.replace(CLAUDE_DIR_PLACEHOLDER, rule_path)
    if isinstance(value, dict):
        return {key: substitute_claude_dir(item, rule_path) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute_claude_dir(item, rule_path) for item in value]
    return value


def load_profile_settings(source: Path, profile: str) -> dict[str, Any]:
    name = "claude.json" if profile == "laptop" else "claude-ci.json"
    return read_json(source / "settings" / name)


def load_local_overlay(home: Path, target: str) -> dict[str, Any] | None:
    path = target_file(home, target, "local.json")
    if not path.is_file():
        return None
    return read_json(path)


def load_hook_manifest(source: Path) -> list[dict[str, Any]]:
    path = source / "hooks" / "hooks.json"
    if not path.is_file():
        return []
    return read_json(path).get("hooks", [])


def build_hook_blocks(hooks: list[dict[str, Any]], source: Path) -> dict[str, list[dict[str, Any]]]:
    """Build the Claude Code settings hook blocks, grouped by event and matcher."""
    order: list[tuple[str, str]] = []
    handlers: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for hook in hooks:
        key = (hook["event"], hook.get("matcher", ""))
        if key not in handlers:
            handlers[key] = []
            order.append(key)
        script = (source / "hooks" / hook["script"]).resolve()
        handler: dict[str, Any] = {"type": "command", "command": f'python3 "{script}"'}
        if hook.get("timeout"):
            handler["timeout"] = hook["timeout"]
        handlers[key].append(handler)

    result: dict[str, list[dict[str, Any]]] = {}
    for event, matcher in order:
        block: dict[str, Any] = {"hooks": handlers[(event, matcher)]}
        if matcher:
            block["matcher"] = matcher
        result.setdefault(event, []).append(block)
    return result


def compose_settings(
    profile_settings: dict[str, Any], hook_blocks: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    composed = copy.deepcopy(profile_settings)
    if not hook_blocks:
        return composed
    events = composed.setdefault("hooks", {})
    for event, blocks in hook_blocks.items():
        events[event] = events.get(event, []) + blocks
    return composed


def block_is_own(block: dict[str, Any]) -> bool:
    for handler in block.get("hooks", []):
        command = handler.get("command", "")
        if any(marker in command for marker in OWN_HOOK_MARKERS):
            return True
    return False


def strip_own_hooks(data: dict[str, Any]) -> bool:
    """Removes own hook blocks from data's "hooks" object in place. Returns whether
    anything was removed, so the caller can tell a genuine change from a no-op."""
    hooks_obj = data.get("hooks")
    changed = False
    if isinstance(hooks_obj, dict):
        for event in list(hooks_obj.keys()):
            kept = [block for block in hooks_obj[event] if not block_is_own(block)]
            if len(kept) != len(hooks_obj[event]):
                changed = True
            if kept:
                hooks_obj[event] = kept
            else:
                del hooks_obj[event]
        if not hooks_obj:
            data.pop("hooks", None)
    return changed


def merge_hooks(existing_hooks: dict[str, Any], composed_hooks: dict[str, Any]) -> dict[str, Any]:
    """Merges composed_hooks into existing_hooks, keeping foreign blocks.

    Emits events in the existing file's order, then any event only composed_hooks has,
    in manifest order, the same order a first install writes. Sorting the keys instead
    would make every status check after the first install report drift for no reason.
    """
    order = list(existing_hooks)
    order += [event for event in composed_hooks if event not in existing_hooks]

    result: dict[str, Any] = {}
    for event in order:
        kept = [block for block in existing_hooks.get(event, []) if not block_is_own(block)]
        result[event] = kept + composed_hooks.get(event, [])
    return result


def merge_into_existing(existing: dict[str, Any], composed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in composed.items():
        if key == "hooks":
            merged["hooks"] = merge_hooks(existing.get("hooks", {}), value)
        else:
            merged[key] = value
    return merged


def install_settings(
    source: Path, claude_dir: Path, home: Path, target: str, profile: str, dry_run: bool
) -> tuple[str, str | None, int, int]:
    """Merge the profile settings and the hook manifest into claude_dir/settings.json."""
    profile_settings = load_profile_settings(source, profile)
    if profile == "laptop":
        overlay = load_local_overlay(home, target)
        if overlay is not None:
            profile_settings = deep_merge(profile_settings, overlay)
    profile_settings = substitute_claude_dir(
        profile_settings, claude_dir_rule_path(claude_dir, home)
    )

    hooks = load_hook_manifest(source)
    hook_blocks = build_hook_blocks(hooks, source)
    composed = compose_settings(profile_settings, hook_blocks)

    dest = claude_dir / "settings.json"
    backup = Path(str(dest) + BACKUP_SUFFIX)

    if not dest.is_file():
        new_content = json.dumps(composed, indent=2) + "\n"
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new_content)
        return "created", None, len(composed), len(hooks)

    existing_raw = dest.read_text()
    try:
        existing = json.loads(existing_raw)
    except json.JSONDecodeError:
        existing = {}
    merged = merge_into_existing(existing, composed)
    new_content = json.dumps(merged, indent=2) + "\n"

    if new_content == existing_raw:
        return "unchanged", None, len(composed), len(hooks)

    existing_has_own_hooks = any(
        block_is_own(block) for blocks in existing.get("hooks", {}).values() for block in blocks
    )

    backed_up = None
    if not backup.is_file() and not existing_has_own_hooks:
        backed_up = str(backup)
        if not dry_run:
            backup.write_text(existing_raw)
    if not dry_run:
        dest.write_text(new_content)
    return "overwritten", backed_up, len(composed), len(hooks)


def write_state(
    home: Path,
    target: str,
    claude_dir: Path,
    source: Path,
    profile: str,
    mode: str,
    skill_names: set[str],
    backups: dict[str, str],
    dry_run: bool,
) -> None:
    if dry_run:
        return
    path = target_file(home, target, "state.json")
    data = {
        "source": str(source),
        "claude_dir": str(resolve_dir(claude_dir)),
        "profile": profile,
        "mode": mode,
        "skills": sorted(skill_names),
        "commit": source_commit(source),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backups": backups,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def collect_backups(claude_dir: Path) -> dict[str, str]:
    backups: dict[str, str] = {}
    claude_md_backup = claude_dir / ("CLAUDE.md" + BACKUP_SUFFIX)
    if claude_md_backup.is_file():
        backups["claude_md"] = str(claude_md_backup)
    settings_backup = claude_dir / ("settings.json" + BACKUP_SUFFIX)
    if settings_backup.is_file():
        backups["settings_json"] = str(settings_backup)
    return backups


def cmd_install(args: argparse.Namespace) -> tuple[list[str], int]:
    lines: list[str] = []
    refusal = claude_dir_mismatch(args.home, args.target, args.claude_dir) or claude_dir_owner(
        args.home, args.target, args.claude_dir
    )
    if refusal:
        return [f"error   {refusal}"], 1

    mode = "copy" if args.copy else "link"
    skills = discover_skills(args.source)
    skills_dir = args.claude_dir / "skills"
    if not args.dry_run:
        skills_dir.mkdir(parents=True, exist_ok=True)

    installed_names: set[str] = set()
    conflicts = False
    for skill in skills:
        status = sync_skill(skill, skills_dir, args.source, mode, args.dry_run)
        lines.append(f"skill   {skill.name} {status}")
        if status == "conflict":
            conflicts = True
        else:
            installed_names.add(skill.name)

    keep = {s.name for s in skills}
    for name, status in prune_skills(skills_dir, keep, args.source, args.dry_run):
        lines.append(f"skill   {name} {status}")

    rules_action, rules_backup = install_rules(args.source, args.claude_dir, args.dry_run)
    lines.append(f"rules   {rules_action}")
    if rules_backup:
        lines.append(f"rules   previous file kept at {rules_backup}")

    export_agents(args.source, args.home, args.target, args.dry_run)
    lines.append("agents  exported")

    settings_action, settings_backup, keys, hook_count = install_settings(
        args.source, args.claude_dir, args.home, args.target, args.profile, args.dry_run
    )
    lines.append(f"settings {settings_action} keys={keys} hooks={hook_count}")
    if settings_backup:
        lines.append(f"settings previous file kept at {settings_backup}")

    write_state(
        args.home,
        args.target,
        args.claude_dir,
        args.source,
        args.profile,
        mode,
        installed_names,
        collect_backups(args.claude_dir),
        args.dry_run,
    )
    lines.append("state   written" if not args.dry_run else "state   skipped in dry run")

    return lines, 1 if conflicts else 0


def cmd_status(args: argparse.Namespace) -> tuple[list[str], int]:
    lines: list[str] = []
    mismatch = claude_dir_mismatch(args.home, args.target, args.claude_dir)
    if mismatch:
        return [f"error   {mismatch}"], 1

    drift = False
    mode = "copy" if args.copy else "link"
    skills = discover_skills(args.source)
    skills_dir = args.claude_dir / "skills"

    for skill in skills:
        status = sync_skill(skill, skills_dir, args.source, mode, dry_run=True)
        if status == "unchanged":
            lines.append(f"skill   {skill.name} in sync")
        else:
            lines.append(f"skill   {skill.name} {status}")
            drift = True

    rules_action, _ = install_rules(args.source, args.claude_dir, dry_run=True)
    if rules_action == "unchanged":
        lines.append("rules   in sync")
    else:
        lines.append(f"rules   drift ({rules_action})")
        drift = True

    settings_action, _, keys, hook_count = install_settings(
        args.source, args.claude_dir, args.home, args.target, args.profile, dry_run=True
    )
    if settings_action == "unchanged":
        lines.append(f"settings in sync keys={keys} hooks={hook_count}")
    else:
        lines.append(f"settings drift ({settings_action}) keys={keys} hooks={hook_count}")
        drift = True

    return lines, 1 if drift else 0


def cmd_doctor(args: argparse.Namespace) -> tuple[list[str], int]:
    lines: list[str] = []
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        lines.append(f"{'ok' if ok else 'fail'}  {label}")
        if not ok:
            failures += 1

    version = ".".join(str(part) for part in sys.version_info[:3])
    check(sys.version_info >= (3, 9), f"python3 >= 3.9 ({version})")
    for tool in ("git", "jq", "mise"):
        check(shutil.which(tool) is not None, f"{tool} on PATH")

    hooks = load_hook_manifest(args.source)
    for hook in hooks:
        script = args.source / "hooks" / hook["script"]
        compiles = False
        if script.is_file():
            try:
                py_compile.compile(str(script), doraise=True)
                compiles = True
            except py_compile.PyCompileError:
                compiles = False
        check(compiles, f"hook script {hook['script']} exists and compiles")

    settings_path = args.claude_dir / "settings.json"
    settings_ok = False
    commands_present = not hooks
    if settings_path.is_file():
        try:
            settings_data = json.loads(settings_path.read_text())
            settings_ok = True
        except json.JSONDecodeError:
            settings_ok = False
            settings_data = {}
        if settings_ok and hooks:
            hook_blocks = build_hook_blocks(hooks, args.source)
            installed_commands = {
                handler.get("command")
                for blocks in settings_data.get("hooks", {}).values()
                for block in blocks
                for handler in block.get("hooks", [])
            }
            commands_present = all(
                handler["command"] in installed_commands
                for blocks in hook_blocks.values()
                for block in blocks
                for handler in block["hooks"]
            )
    check(settings_ok, "settings.json is valid JSON")
    check(commands_present, "settings.json contains the hook commands")

    skills_dir = args.claude_dir / "skills"
    broken = []
    if skills_dir.is_dir():
        broken = [e.name for e in skills_dir.iterdir() if e.is_symlink() and not e.exists()]
    check(not broken, "no broken skill symlinks" + (f" ({', '.join(broken)})" if broken else ""))

    mismatch = claude_dir_mismatch(args.home, args.target, args.claude_dir)
    check(mismatch is None, mismatch or "state records the claude-dir in use")

    overlay_path = target_file(args.home, args.target, "local.json")
    overlay_ok = True
    if overlay_path.is_file():
        try:
            json.loads(overlay_path.read_text())
        except json.JSONDecodeError:
            overlay_ok = False
    check(overlay_ok, "local overlay is valid JSON")

    return lines, 1 if failures else 0


def cmd_uninstall(args: argparse.Namespace) -> tuple[list[str], int]:
    lines: list[str] = []
    home = args.home
    claude_dir = args.claude_dir
    # The recorded claude_dir decides what gets removed. Without these guards a target
    # name and a --claude-dir that drifted apart would wipe another target's installation:
    # the first guard catches the wrong directory for this target, the second a directory
    # that belongs to a different target.
    refusal = claude_dir_mismatch(home, args.target, claude_dir) or claude_dir_owner(
        home, args.target, claude_dir
    )
    if refusal:
        return [f"error   {refusal}"], 1

    state_path = target_file(home, args.target, "state.json")
    state = read_state(home, args.target)

    skills_dir = claude_dir / "skills"
    if state:
        source = Path(state.get("source", ""))
        for name in state.get("skills", []):
            target = skills_dir / name
            if not target.exists() and not target.is_symlink():
                continue
            if inspect_target(target, source) not in ("owned_link", "owned_copy", "stale"):
                continue
            if not args.dry_run:
                if target.is_symlink() or target.is_file():
                    target.unlink()
                else:
                    shutil.rmtree(target)
            lines.append(f"skill   {name} removed")

    claude_md = claude_dir / "CLAUDE.md"
    claude_backup = Path(str(claude_md) + BACKUP_SUFFIX)
    if claude_backup.is_file():
        lines.append("rules   restored from backup")
        if not args.dry_run:
            shutil.move(str(claude_backup), str(claude_md))
    elif claude_md.is_file():
        lines.append("rules   removed")
        if not args.dry_run:
            claude_md.unlink()

    settings_path = claude_dir / "settings.json"
    settings_backup = Path(str(settings_path) + BACKUP_SUFFIX)
    if settings_backup.is_file():
        # A stale backup can itself carry own hook blocks, when an earlier install run
        # mistook its own output for the user's original file. Strip them on restore
        # regardless, so uninstall never leaves the hooks wired.
        try:
            backup_data = json.loads(settings_backup.read_text())
        except json.JSONDecodeError:
            backup_data = None
        lines.append("settings restored from backup")
        if isinstance(backup_data, dict):
            strip_own_hooks(backup_data)
            if not args.dry_run:
                settings_path.write_text(json.dumps(backup_data, indent=2) + "\n")
                settings_backup.unlink()
        elif not args.dry_run:
            shutil.move(str(settings_backup), str(settings_path))
    elif settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            data = {}
        changed = strip_own_hooks(data)
        if changed:
            lines.append("settings hooks removed, rest kept")
            if not args.dry_run:
                settings_path.write_text(json.dumps(data, indent=2) + "\n")
        else:
            lines.append("settings no installed hooks found, left untouched")

    agents_md = target_file(home, args.target, "AGENTS.md")
    if agents_md.is_file():
        lines.append("agents  export removed")
        if not args.dry_run:
            agents_md.unlink()

    if state_path.is_file():
        lines.append("state   removed")
        if not args.dry_run:
            state_path.unlink()

    return lines, 0


COMMANDS = {
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "status": cmd_status,
    "doctor": cmd_doctor,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py", description="Install the skills baseline for Claude Code."
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--profile", choices=["laptop", "ci"], default="laptop")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--claude-dir", type=Path, default=None)
    parser.add_argument("--target", type=str, default="")
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--copy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def invalid_target(target: str) -> str | None:
    """A target is interpolated into a filename, so it has to be a plain name."""
    if not target:
        return None
    if target in (".", "..") or not TARGET_PATTERN.match(target):
        return (
            f"invalid --target '{target}': use letters, digits, dot, dash or "
            "underscore only, with no path separator and no '..'."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    target_error = invalid_target(args.target)
    if target_error:
        print(f"error   {target_error}")
        return 2

    args.home = (args.home or Path(os.environ.get("HOME", str(Path.home())))).expanduser()
    args.claude_dir = (args.claude_dir or (args.home / ".claude")).expanduser()
    default_source = Path(__file__).resolve().parent.parent
    args.source = (args.source or default_source).expanduser().resolve()

    lines, code = COMMANDS[args.command](args)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
