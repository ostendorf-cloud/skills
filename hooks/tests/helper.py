# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Test helper: runs a hook script as a subprocess with a payload and parses its JSON
response. Shared by every test module in this directory.
"""

import json
import os
import subprocess
import sys
from typing import Any, Optional

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(
    name: str,
    payload: dict[str, Any],
    cwd: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Runs hooks/<name> with payload as its stdin JSON. Returns the parsed response.

    env, when given, replaces the subprocess environment entirely, to test behaviour
    with a tool missing from PATH.
    """
    result = subprocess.run(
        [sys.executable, os.path.join(HOOKS_DIR, name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout or "{}")


def bash_payload(command: str, cwd: Optional[str] = None) -> dict[str, Any]:
    """A PreToolUse Bash payload for command."""
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


def file_tool_payload(tool_name: str, path: str) -> dict[str, Any]:
    """A PreToolUse payload for tool_name targeting path.

    Read, Edit, Write and MultiEdit carry their target under file_path; NotebookEdit
    carries it under notebook_path.
    """
    key = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {key: path},
    }


def write_payload(file_path: str, content: str = "", tool_name: str = "Write") -> dict[str, Any]:
    """A PostToolUse Write or Edit payload for file_path."""
    tool_input: dict[str, Any] = {"file_path": file_path}
    if tool_name == "Write":
        tool_input["content"] = content
    else:
        tool_input["new_string"] = content
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def decision(output: dict[str, Any]) -> Optional[str]:
    """The permissionDecision of a hook response, or None when it set none."""
    return (output.get("hookSpecificOutput") or {}).get("permissionDecision")


def reason(output: dict[str, Any]) -> str:
    """The permissionDecisionReason of a hook response, or "" when it set none."""
    return (output.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""


def context(output: dict[str, Any]) -> str:
    """The additionalContext of a hook response, or "" when it set none."""
    return (output.get("hookSpecificOutput") or {}).get("additionalContext") or ""
