# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Cuts the user's git configuration off for the script tests.

Imported by _load, which every test module imports.
"""

from __future__ import annotations

import os


def git_env(base: dict[str, str] | None = None) -> dict[str, str]:
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


os.environ.update(git_env())
