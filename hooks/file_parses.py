#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PostToolUse hook on Write or Edit. Reports a YAML, JSON or TOML file that no longer
parses after the write. Skips files under .worktrees and a templates file that holds
Go template syntax.
"""

import json
import os
import shutil
import subprocess
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PostToolUse"

YAML_SUFFIXES = (".yaml", ".yml")
NO_PARSER = "no parser available"


def should_skip(path: str, text: str) -> bool:
    """Whether path is a worktree file or a Go template that happens to end in .yaml."""
    parts = os.path.normpath(path).split(os.sep)
    if ".worktrees" in parts:
        return True
    return "templates" in parts and "{{" in text


def first_line(text: str) -> str:
    stripped = text.strip()
    return stripped.splitlines()[0] if stripped else text


def validate_yaml(path: str) -> Optional[str]:
    """None when path parses as YAML, else the parser's complaint or NO_PARSER."""
    yq = shutil.which("yq")
    if yq:
        try:
            result = subprocess.run(
                [yq, "--exit-status", ".", path], capture_output=True, text=True, timeout=15
            )
        except Exception as error:
            return first_line(str(error))
        return None if result.returncode == 0 else first_line(result.stderr or result.stdout)

    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return NO_PARSER

    try:
        with open(path, encoding="utf-8") as handle:
            yaml.safe_load(handle)
    except Exception as error:
        return first_line(str(error))
    return None


def validate_json(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as handle:
            json.load(handle)
    except Exception as error:
        return first_line(str(error))
    return None


def validate_toml(path: str) -> Optional[str]:
    """None when path parses as TOML, else the parser's complaint or NO_PARSER."""
    try:
        import tomllib  # noqa: PLC0415
    except ImportError:
        return NO_PARSER

    try:
        with open(path, "rb") as handle:
            tomllib.load(handle)
    except Exception as error:
        return first_line(str(error))
    return None


def main() -> int:
    payload = _common.read_payload()
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path or not os.path.isfile(path):
        return _common.emit_empty()

    suffix = os.path.splitext(path)[1].lower()
    if suffix not in (*YAML_SUFFIXES, ".json", ".toml"):
        return _common.emit_empty()

    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return _common.emit_empty()

    if should_skip(path, text):
        return _common.emit_empty()

    if suffix in YAML_SUFFIXES:
        problem = validate_yaml(path)
    elif suffix == ".json":
        problem = validate_json(path)
    else:
        problem = validate_toml(path)

    if problem is None or problem == NO_PARSER:
        return _common.emit_empty()

    return _common.context(EVENT, f"{path} no longer parses: {problem}")


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
