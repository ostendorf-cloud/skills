#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Checks skill and agent style, hooks, settings, groupings, ADRs, license headers, YAML
extensions."""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
from pathlib import Path

MIN_DESCRIPTION_LENGTH = 60
MAX_BODY_LINES = 120
SKIPPED_DIRS = {".git", "node_modules"}

FORBIDDEN_CHARS = {
    "–": "en dash",
    "—": "em dash",
    "‘": "typographic quote",
    "’": "typographic quote",
    "“": "typographic quote",
    "”": "typographic quote",
}

KNOWN_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "SessionStart",
    "SessionEnd",
    "Stop",
    "SubagentStop",
    "PreCompact",
    "Notification",
}
KNOWN_DECISIONS = {"deny", "context"}
# The values Claude Code takes for a command hook's onFailure, from v2.1.295 on.
KNOWN_ON_FAILURE = {"continue", "block"}
# Only Edit(path) and Read(path) rules are consulted for file access. A path rule on one of
# these tools is accepted by the harness and never used.
UNMATCHED_PATH_RULE_PREFIXES = ("Write(", "NotebookEdit(", "MultiEdit(", "Glob(")

FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

LICENSE_LINES = (
    "# Copyright 2026 Simon Ostendorf",
    "# SPDX-License-Identifier: Apache-2.0",
)

YAML_EXTENSION_EXCEPTIONS = {
    Path(".github/FUNDING.yml"),
    Path(".github/dependabot.yml"),
}


def is_emoji(char: str) -> bool:
    code = ord(char)
    if code in (0x2705, 0x274C):
        return True
    ranges = ((0x1F300, 0x1FAFF), (0x1F000, 0x1F2FF), (0x2600, 0x27BF))
    return any(low <= code <= high for low, high in ranges)


def iter_skill_dirs(root: Path) -> list[Path]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return []
    dirs: list[Path] = []
    for category_dir in sorted(skills_root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue
        for skill_dir in sorted(category_dir.iterdir()):
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                dirs.append(skill_dir)
    return dirs


BLOCK_SCALAR_HEADS = (">", ">-", ">+", "|", "|-", "|+")


def parse_frontmatter(lines: list[str]) -> dict[str, str]:
    """Parses the simple subset of YAML frontmatter skills use: scalars and block scalars."""
    data: dict[str, str] = {}
    index = 0
    while index < len(lines):
        match = FRONTMATTER_KEY.match(lines[index])
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if value not in BLOCK_SCALAR_HEADS:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            data[key] = value
            index += 1
            continue

        folded = value.startswith(">")
        block: list[str] = []
        base_indent: int | None = None
        index += 1
        while index < len(lines):
            raw = lines[index]
            if raw.strip() == "":
                block.append("")
                index += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if base_indent is None:
                base_indent = indent
            if indent < base_indent:
                break
            block.append(raw[base_indent:])
            index += 1
        data[key] = " ".join(seg for seg in block if seg).strip() if folded else "\n".join(block)
    return data


def split_frontmatter_lines(text: str) -> tuple[list[str] | None, str]:
    """The raw frontmatter lines between the two --- markers, and the body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None, text
    return lines[1:end], "\n".join(lines[end + 1 :])


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    lines, body = split_frontmatter_lines(text)
    if lines is None:
        return None, body
    return parse_frontmatter(lines), body


BLOCK_SCALAR_HEAD = re.compile(r"^[>|][-+0-9]*(\s+#.*)?$")
PLAIN_SCALAR_INDICATORS = "[{*&!@`%|>"


def quoted_problem(text: str) -> str | None:
    """What is wrong with a quoted scalar that starts at text[0], or None when it is fine.

    A double quoted value escapes a quote with a backslash, a single quoted one by
    doubling it. A quote that is not escaped closes the value, so whatever follows it
    must be whitespace or a ' #' comment.
    """
    quote = text[0]
    position = 1
    while position < len(text):
        char = text[position]
        if quote == '"' and char == "\\":
            position += 2
            continue
        if char == quote:
            if quote == "'" and text[position + 1 : position + 2] == "'":
                position += 2
                continue
            break
        position += 1
    else:
        return "quoted value is not closed"
    rest = text[position + 1 :]
    if not rest.strip() or (rest[0] in " \t" and rest.lstrip().startswith("#")):
        return None
    return f"text after the closing quote, escape a {quote} inside the value " + (
        "with a backslash" if quote == '"' else "by doubling it"
    )


def frontmatter_problems(lines: list[str]) -> list[str]:
    """Values a YAML parser rejects or misreads, in the shapes frontmatter uses here.

    parse_frontmatter is lenient on purpose. This is the strict half: a plain scalar
    that continues on following indented lines, or that holds ': ' or ' #', is an error
    in a real parser or silently cut short. The accepted shapes are one line, a block
    scalar (> or |) and a quoted value. Nested maps and lists, flow collections and
    values that start with a YAML indicator are not inspected.
    """
    problems: list[str] = []
    index = 0
    while index < len(lines):
        match = FRONTMATTER_KEY.match(lines[index])
        index += 1
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        following = index
        while following < len(lines) and (
            lines[following].strip() == "" or lines[following].startswith((" ", "\t"))
        ):
            following += 1
        continuation = [line for line in lines[index:following] if line.strip()]
        if not value or BLOCK_SCALAR_HEAD.match(value) or value[0] in PLAIN_SCALAR_INDICATORS:
            index = following
            continue
        if value[0] in "\"'":
            text = "\n".join([value, *(line.strip() for line in lines[index:following])])
            index = following
            problem = quoted_problem(text)
            if problem:
                problems.append(f"frontmatter {key}: {problem}")
            continue
        if continuation:
            problems.append(
                f"frontmatter {key}: plain value continues on the next line, "
                "use one line, a block scalar (>) or quotes"
            )
            index = following
        elif ": " in value or value.endswith(":"):
            problems.append(
                f"frontmatter {key}: plain value contains ': ', use a block scalar (>) or quotes"
            )
        elif " #" in value:
            problems.append(
                f"frontmatter {key}: plain value contains ' #', which starts a comment, "
                "use a block scalar (>) or quotes"
            )
    return problems


def check_skills(root: Path) -> list[str]:
    findings: list[str] = []
    for skill_dir in iter_skill_dirs(root):
        skill_md = skill_dir / "SKILL.md"
        rel = skill_md.relative_to(root)
        if not skill_md.is_file():
            findings.append(f"{rel}: missing SKILL.md")
            continue
        text = skill_md.read_text()
        frontmatter, body = split_frontmatter(text)
        if frontmatter is None:
            findings.append(f"{rel}: missing frontmatter")
            continue
        raw_lines, _ = split_frontmatter_lines(text)
        findings.extend(f"{rel}: {problem}" for problem in frontmatter_problems(raw_lines or []))
        name = frontmatter.get("name")
        if name != skill_dir.name:
            findings.append(f"{rel}: frontmatter name {name!r} does not match directory name")
        description = frontmatter.get("description", "")
        if len(description) < MIN_DESCRIPTION_LENGTH:
            findings.append(
                f"{rel}: description is {len(description)} characters, "
                f"minimum is {MIN_DESCRIPTION_LENGTH}"
            )
        body_lines = body.splitlines()
        if len(body_lines) > MAX_BODY_LINES:
            findings.append(f"{rel}: body is {len(body_lines)} lines, maximum is {MAX_BODY_LINES}")
    return findings


def check_agents(root: Path) -> list[str]:
    """Subagent definitions under agents/: strict frontmatter, name is the file stem."""
    agents_root = root / "agents"
    if not agents_root.is_dir():
        return []
    findings: list[str] = []
    for path in sorted(agents_root.glob("*.md")):
        rel = path.relative_to(root)
        text = path.read_text()
        frontmatter, _ = split_frontmatter(text)
        if frontmatter is None:
            findings.append(f"{rel}: missing frontmatter")
            continue
        raw_lines, _ = split_frontmatter_lines(text)
        findings.extend(f"{rel}: {problem}" for problem in frontmatter_problems(raw_lines or []))
        name = frontmatter.get("name")
        if name != path.stem:
            findings.append(f"{rel}: frontmatter name {name!r} does not match the file name")
        if not frontmatter.get("description"):
            findings.append(f"{rel}: description is missing")
    return findings


def scan_characters(path: Path, root: Path) -> list[str]:
    findings: list[str] = []
    rel = path.relative_to(root)
    reported: set[str] = set()
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        for char in line:
            label = FORBIDDEN_CHARS.get(char)
            if label is None and is_emoji(char):
                label = "emoji"
            if label and label not in reported:
                reported.add(label)
                findings.append(f"{rel}:{number}: contains a {label}")
    return findings


def find_agents_files(root: Path) -> list[Path]:
    """The root AGENTS.md and every nested one, skipping vendored and worktree directories."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel = current.relative_to(root).as_posix()
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIPPED_DIRS and posixpath.join(rel, d) != ".claude/worktrees"
        )
        if "AGENTS.md" in filenames:
            found.append(current / "AGENTS.md")
    return found


def check_characters(root: Path) -> list[str]:
    paths: list[Path] = []
    if (root / "skills").is_dir():
        paths.extend(sorted((root / "skills").rglob("*.md")))
    if (root / "rules").is_dir():
        paths.extend(sorted((root / "rules").glob("*.md")))
    if (root / "agents").is_dir():
        paths.extend(sorted((root / "agents").glob("*.md")))
    if (root / "docs").is_dir():
        paths.extend(sorted((root / "docs").rglob("*.md")))
    readme = root / "README.md"
    if readme.is_file():
        paths.append(readme)
    paths.extend(find_agents_files(root))

    findings: list[str] = []
    for path in paths:
        findings.extend(scan_characters(path, root))
    return findings


def load_forbidden_words(root: Path) -> list[str]:
    path = root / "scripts" / "forbidden-words.txt"
    if not path.is_file():
        return []
    return [line.strip().lower() for line in path.read_text().splitlines() if line.strip()]


def check_forbidden_words(root: Path) -> list[str]:
    words = load_forbidden_words(root)
    if not words:
        return []

    targets: list[Path] = []
    if (root / "skills").is_dir():
        targets.extend(sorted((root / "skills").rglob("SKILL.md")))
    baseline = root / "rules" / "baseline.md"
    if baseline.is_file():
        targets.append(baseline)

    findings: list[str] = []
    for path in targets:
        rel = path.relative_to(root)
        reported: set[str] = set()
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            lowered = line.lower()
            for word in words:
                if word not in reported and word in lowered:
                    reported.add(word)
                    findings.append(f"{rel}:{number}: contains forbidden word '{word}'")
    return findings


def check_groupings(root: Path) -> list[str]:
    path = root / "skills.sh.json"
    if not path.is_file():
        return ["skills.sh.json: missing"]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"skills.sh.json: invalid JSON: {exc}"]

    known = {skill_dir.name for skill_dir in iter_skill_dirs(root)}
    listed: dict[str, int] = {}
    findings: list[str] = []
    for grouping in data.get("groupings", []):
        title = grouping.get("title")
        if not title:
            findings.append("skills.sh.json: a grouping is missing a title")
        if not grouping.get("description"):
            findings.append(f"skills.sh.json: grouping {title!r} is missing a description")
        skills = grouping.get("skills")
        if not skills:
            findings.append(f"skills.sh.json: grouping {title!r} has an empty skills array")
            continue
        for name in skills:
            listed[name] = listed.get(name, 0) + 1
            if name not in known:
                findings.append(f"skills.sh.json: lists '{name}', which does not exist")

    for name, count in sorted(listed.items()):
        if count > 1:
            findings.append(f"skills.sh.json: '{name}' is listed more than once")
    for name in sorted(known - listed.keys()):
        findings.append(f"skills.sh.json: skill '{name}' is not listed")
    return findings


def check_hooks_manifest(root: Path) -> list[str]:
    path = root / "hooks" / "hooks.json"
    if not path.is_file():
        return ["hooks/hooks.json: missing"]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"hooks/hooks.json: invalid JSON: {exc}"]

    hooks_dir = root / "hooks"
    tests_dir = hooks_dir / "tests"
    ids: dict[str, int] = {}
    findings: list[str] = []
    for entry in data.get("hooks", []):
        hook_id = entry.get("id", "")
        ids[hook_id] = ids.get(hook_id, 0) + 1

        script = entry.get("script", "")
        # The installer copies every hook script into the installed copy with a flat
        # listing of hooks/, so a script named with a path separator would exist on
        # disk and still never be installed.
        if len(Path(script).parts) != 1:
            findings.append(
                f"hooks/hooks.json: {hook_id}: script '{script}' is not a top level "
                "file directly under hooks/"
            )
        elif not (hooks_dir / script).is_file():
            findings.append(f"hooks/hooks.json: {hook_id}: script '{script}' does not exist")

        stem = script[:-3] if script.endswith(".py") else script
        test_path = tests_dir / f"test_{stem}.py"
        if not test_path.is_file():
            rel_test = test_path.relative_to(root)
            findings.append(f"hooks/hooks.json: {hook_id}: no test file {rel_test}")

        event = entry.get("event")
        if event not in KNOWN_EVENTS:
            findings.append(f"hooks/hooks.json: {hook_id}: unknown event '{event}'")

        decision = entry.get("decision")
        if decision not in KNOWN_DECISIONS:
            findings.append(f"hooks/hooks.json: {hook_id}: unknown decision '{decision}'")

        on_failure = entry.get("onFailure")
        if on_failure is not None and on_failure not in KNOWN_ON_FAILURE:
            findings.append(f"hooks/hooks.json: {hook_id}: unknown onFailure '{on_failure}'")

    for hook_id, count in sorted(ids.items()):
        if count > 1:
            findings.append(f"hooks/hooks.json: id '{hook_id}' is used more than once")
    return findings


def check_settings(root: Path) -> list[str]:
    settings_dir = root / "settings"
    if not settings_dir.is_dir():
        return []

    findings: list[str] = []
    for path in sorted(settings_dir.glob("*.json")):
        rel = path.relative_to(root)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            findings.append(f"{rel}: invalid JSON: {exc}")
            continue
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            findings.append(f"{rel}: permissions must be an object")
            continue
        findings.extend(unmatched_path_rules(rel, permissions))
        if path.name not in ("claude.json", "claude-ci.json"):
            continue
        allow = permissions.get("allow")
        deny = permissions.get("deny")
        if not isinstance(allow, list):
            findings.append(f"{rel}: permissions.allow must be an array")
            allow = []
        if not isinstance(deny, list):
            findings.append(f"{rel}: permissions.deny must be an array")
            deny = []
        if "ask" in permissions and not isinstance(permissions["ask"], list):
            findings.append(f"{rel}: permissions.ask must be an array")
        for entry in sorted(set(allow) & set(deny)):
            findings.append(f"{rel}: '{entry}' is in both permissions.allow and permissions.deny")
    return findings


def unmatched_path_rules(rel: Path, permissions: dict) -> list[str]:
    """Path rules the permission checks never consult. The overlay is included because
    the installer merges it into the installed settings."""
    findings: list[str] = []
    for list_name in ("allow", "ask", "deny"):
        entries = permissions.get(list_name)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry.startswith(UNMATCHED_PATH_RULE_PREFIXES):
                findings.append(
                    f"{rel}: '{entry}' in permissions.{list_name} is never matched, "
                    "a file rule is written as Edit(path) for every editing tool or "
                    "Read(path) for Glob"
                )
    return findings


def check_schema(root: Path) -> list[str]:
    path = root / "agent-skills.schema.json"
    if not path.is_file():
        return ["agent-skills.schema.json: missing"]
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"agent-skills.schema.json: invalid JSON: {exc}"]

    findings: list[str] = []
    if "$schema" not in data:
        findings.append("agent-skills.schema.json: missing $schema")
    if "properties" not in data:
        findings.append("agent-skills.schema.json: missing properties")
    findings.extend(check_config_against_schema(root, data))
    return findings


def check_config_against_schema(root: Path, schema: dict) -> list[str]:
    """Checks the repository's own .agent-skills.json: known keys and matching types."""
    path = root / ".agent-skills.json"
    if not path.is_file():
        return []
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f".agent-skills.json: invalid JSON: {exc}"]
    if not isinstance(config, dict):
        return [".agent-skills.json: top level must be an object"]
    return _check_object(config, schema, ".agent-skills.json")


_JSON_TYPES = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "array": list,
    "object": dict,
}


def _check_object(value: dict, schema: dict, where: str) -> list[str]:
    findings: list[str] = []
    properties = schema.get("properties", {})
    for key, item in value.items():
        if key not in properties:
            if schema.get("additionalProperties") is False:
                findings.append(f"{where}: unknown key {key}")
            continue
        findings.extend(_check_value(item, properties[key], f"{where}.{key}"))
    return findings


def _check_value(value: object, schema: dict, where: str) -> list[str]:
    if "oneOf" in schema:
        for option in schema["oneOf"]:
            if not _check_value(value, option, where):
                return []
        return [f"{where}: matches none of the allowed shapes"]
    expected = schema.get("type")
    if expected is None:
        return []
    names = expected if isinstance(expected, list) else [expected]
    if "const" in schema and value != schema["const"]:
        return [f"{where}: must be {schema['const']!r}"]
    if isinstance(value, bool) and "boolean" not in names:
        return [f"{where}: expected {', '.join(names)}"]
    if not any(isinstance(value, _JSON_TYPES[name]) for name in names if name in _JSON_TYPES):
        return [f"{where}: expected {', '.join(names)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: must be one of {', '.join(map(str, schema['enum']))}"]
    if isinstance(value, dict) and "properties" in schema:
        return _check_object(value, schema, where)
    return []


def check_adrs(root: Path) -> list[str]:
    adr_dir = root / "docs" / "adr"
    if not adr_dir.is_dir():
        return []

    findings: list[str] = []
    numbers: dict[int, str] = {}
    for path in sorted(adr_dir.glob("*.md")):
        match = ADR_NAME.match(path.name)
        if not match:
            findings.append(f"docs/adr/{path.name}: name must be NNNN-kebab-title.md")
            continue
        number = int(match.group(1))
        if number in numbers:
            findings.append(
                f"docs/adr/{path.name}: number {number:04d} is already used by {numbers[number]}"
            )
            continue
        numbers[number] = path.name

    for index, number in enumerate(sorted(numbers), start=1):
        if number != index:
            findings.append(
                f"docs/adr/{numbers[number]}: numbering has a gap, expected {index:04d}"
            )
            break
    return findings


def check_license_headers(root: Path) -> list[str]:
    findings: list[str] = []
    for directory in (root / "hooks", root / "scripts"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_dir() or path.suffix not in (".py", ".sh"):
                continue
            head = path.read_text().splitlines()[:3]
            if not all(line in head for line in LICENSE_LINES):
                rel = path.relative_to(root)
                findings.append(f"{rel}: missing license header in the first 3 lines")
    return findings


def _is_worktree_path(parts: tuple) -> bool:
    """Whether parts contains the old .worktrees segment or the new .claude/worktrees pair."""
    if ".worktrees" in parts:
        return True
    return any(
        parts[index] == ".claude" and parts[index + 1] == "worktrees"
        for index in range(len(parts) - 1)
    )


def list_yml_files(root: Path) -> list[Path]:
    """Lists tracked and untracked *.yml files, respecting .gitignore, or walks without git."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.yml"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        paths = [root / line for line in result.stdout.splitlines() if line]
    else:
        paths = sorted(root.rglob("*.yml"))
    return [
        path
        for path in paths
        if not _is_worktree_path(path.relative_to(root).parts)
        and ".git" not in path.relative_to(root).parts
    ]


def check_yaml_extension(root: Path) -> list[str]:
    findings: list[str] = []
    for path in list_yml_files(root):
        rel = path.relative_to(root)
        if rel in YAML_EXTENSION_EXCEPTIONS:
            continue
        findings.append(f"{rel}: uses the .yml extension, rename to .yaml")
    return findings


# Files directly under the installed skills directory, besides the skill directories.
# scripts/install.py installs exactly these.
INSTALLED_SKILLS_FILES = {"README.md"}
INSTALLED_SKILLS_PREFIX = "~/.claude/"
# A path token that names a Markdown file below a "skills/" directory, with any prefix.
SKILLS_FILE_TOKEN = re.compile(r"[\w$~{}.\/-]*skills/[\w./-]+\.md")
SKILLS_SPLIT = re.compile(r"^(?P<prefix>(?:.*/)?)skills/(?P<rest>.+)$")


def normalise_reference(token: str) -> str:
    """Spell $HOME, ${HOME} and ~ alike and resolve "." and ".." segments."""
    token = token.replace("${HOME}", "~").replace("$HOME", "~")
    return posixpath.normpath(token)


def check_skill_references(root: Path) -> list[str]:
    """A skill may cite a file under skills/ only by a path the installed layout provides.

    The installed layout holds the skill directories and INSTALLED_SKILLS_FILES under
    ~/.claude/skills. A path into a repository checkout, such as skills/README.md, is
    not there after install. A repository layout path with a subdirectory, such as
    skills/<category>/<name>/SKILL.md, is prose about the repository and is not checked.
    """
    findings: list[str] = []
    skill_dirs = {path.name: path for path in iter_skill_dirs(root)}
    for skill_dir in skill_dirs.values():
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        rel = skill_md.relative_to(root)
        for number, line in enumerate(skill_md.read_text().splitlines(), start=1):
            for token in SKILLS_FILE_TOKEN.findall(line):
                split = SKILLS_SPLIT.match(normalise_reference(token))
                if split is None:
                    continue
                prefix, rest = split.group("prefix"), split.group("rest")
                head, _, tail = rest.partition("/")
                where = f"{rel}:{number}: `{token}`"
                if prefix == INSTALLED_SKILLS_PREFIX:
                    if not tail and rest in INSTALLED_SKILLS_FILES:
                        continue
                    if tail and head in skill_dirs and (skill_dirs[head] / tail).is_file():
                        continue
                    findings.append(
                        f"{where} is not installed, scripts/install.py provides "
                        f"{sorted(INSTALLED_SKILLS_FILES)} and the skill directories"
                    )
                elif not tail:
                    findings.append(
                        f"{where} is a repository path that does not exist after install, "
                        f"use `~/.claude/skills/{rest}`"
                    )
    return findings


CHECKS = (
    check_skills,
    check_skill_references,
    check_agents,
    check_characters,
    check_forbidden_words,
    check_groupings,
    check_hooks_manifest,
    check_settings,
    check_schema,
    check_adrs,
    check_license_headers,
    check_yaml_extension,
)


def run(root: Path) -> list[str]:
    findings: list[str] = []
    for check in CHECKS:
        findings.extend(check(root))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate.py", description="Check this repository.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    findings = run(args.root.resolve())
    if not findings:
        print("ok")
        return 0
    for finding in findings:
        print(finding)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
