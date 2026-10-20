# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Every hook must survive malformed input: exit 0 and print valid JSON, never a
traceback, since a hook that crashes would otherwise block the tool call by accident.
"""

import json
import subprocess
import sys
import unittest

from helper import HOOKS_DIR

with open(f"{HOOKS_DIR}/hooks.json", encoding="utf-8") as _handle:
    HOOK_SCRIPTS = sorted({entry["script"] for entry in json.load(_handle)["hooks"]})


def run_with_garbage_stdin(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, f"{HOOKS_DIR}/{script}"],
        input="not json at all {{{",
        capture_output=True,
        text=True,
        timeout=30,
    )


class HookRobustnessTest(unittest.TestCase):
    def test_every_hook_survives_garbage_stdin(self):
        for script in HOOK_SCRIPTS:
            with self.subTest(script=script):
                result = run_with_garbage_stdin(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout or "{}")
                self.assertIsInstance(parsed, dict)


if __name__ == "__main__":
    unittest.main()
