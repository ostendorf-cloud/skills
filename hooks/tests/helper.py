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


NO_SCRATCH = "/nonexistent-scratch"


def git_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """base with the user's git configuration cut off.

    Global and system config point at the null device, so a signing setup, aliases,
    hooks or init.defaultBranch of the machine never reach a fixture repository. A
    commit in a test must not wait on a locked signing agent.
    """
    env = dict(base if base is not None else os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


# Every test module imports this helper, so every git subprocess a test starts, and
# every hook it runs, inherits the isolated environment.
os.environ.update(git_env())


def scratch_env(scratch: str, base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """The environment for a hook run whose session scratch directory is scratch."""
    return dict(base if base is not None else os.environ, TMPDIR=scratch)


def run_hook(
    name: str,
    payload: dict[str, Any],
    cwd: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Runs hooks/<name> with payload as its stdin JSON. Returns the parsed response.

    env, when given, replaces the subprocess environment entirely, to test behaviour
    with a tool missing from PATH.

    The hooks treat $TMPDIR as the session scratch scope, and the fixture repositories
    of these tests live under the test process's own temporary directory. Without an
    explicit env the hook therefore runs with $TMPDIR pointed at a directory that holds
    no fixture, so a fixture reads as the real repository it stands for. A test of the
    scratch scope passes scratch_env.
    """
    if env is None:
        env = scratch_env(NO_SCRATCH)
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
