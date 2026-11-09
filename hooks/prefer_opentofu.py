#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a `terraform` invocation unless the repository's
`.agent-skills.json` marks it as Terraform based.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

# The parts are normalised before this runs, so the wrapper prefixes, a leading path
# and a quoted name are already resolved and the name is matched bare.
TERRAFORM = re.compile(r"^terraform\b")


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    parts = [_common.normalize_command_part(part) for part in _common.command_parts(command)]
    if not any(TERRAFORM.match(part) for part in parts):
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    root = _common.repo_root(cwd)
    config = _common.agent_skills_config(root)
    if config.get("iac") == "terraform":
        return _common.emit_empty()

    return _common.deny(
        EVENT,
        "This repository is OpenTofu by default. Use tofu with the same arguments, or "
        'set "iac": "terraform" in .agent-skills.json if this repository is genuinely '
        "Terraform based.",
    )


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
