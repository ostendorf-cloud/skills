#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PostToolUse hook on Write or Edit. Runs `tofu fmt` on a written .tf or .tfvars file
and reports when it rewrote the file. Skips the check when tofu is not on PATH.
"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PostToolUse"
SUFFIXES = (".tf", ".tfvars")


def main() -> int:
    payload = _common.read_payload()
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path or not path.lower().endswith(SUFFIXES) or not os.path.isfile(path):
        return _common.emit_empty()

    tofu = shutil.which("tofu")
    if not tofu:
        return _common.emit_empty()

    try:
        result = subprocess.run(
            [tofu, "fmt", "-list=true", path], capture_output=True, text=True, timeout=20
        )
    except Exception:
        return _common.emit_empty()

    rewritten = [line for line in result.stdout.splitlines() if line.strip()]
    if rewritten:
        return _common.context(EVENT, f"tofu fmt rewrote {path}")

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(main())
