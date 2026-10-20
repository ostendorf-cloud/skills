#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies repository, organisation, label, ruleset or secret
changes made through `gh` or the API, and `gh release` where release-please owns
releases.
"""

import os
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GH_REPO = re.compile(r"^gh\s+repo\s+(edit|delete|create)\b")
GH_LABEL = re.compile(r"^gh\s+label\s+(create|edit|delete|clone)\b")
GH_SECRET = re.compile(r"^gh\s+secret\s+(set|delete|remove)\b")
GH_VARIABLE = re.compile(r"^gh\s+variable\s+(set|delete)\b")
GH_RELEASE = re.compile(r"^gh\s+release\s+(create|delete|edit|upload)\b")
GH_API = re.compile(r"^gh\s+api\b")

API_VALUE_FLAGS = {
    "-X",
    "--method",
    "-f",
    "--field",
    "-F",
    "--raw-field",
    "--input",
    "-H",
    "--header",
    "-q",
    "--jq",
    "-t",
    "--template",
    "--hostname",
    "--cache",
}
WRITE_METHODS = {"PATCH", "PUT", "DELETE", "POST"}

API_WRITE_PATH = re.compile(
    r"^(/)?(repos/[^/]+/[^/]+(/labels|/rulesets|/branches/.*/protection|"
    r"/actions/secrets|/actions/variables|$)|orgs/[^/]+|user/repos)"
)

IAC_REASON = (
    "Repository and organisation settings, labels, rulesets and secrets are "
    "infrastructure as code. Propose the change in the infrastructure repository "
    "instead of changing it with gh."
)
RELEASE_REASON = (
    "release-please owns releases here. The release pull request cuts the release; do "
    "not run gh release directly."
)


def gh_api_method(tokens: list[str]) -> str:
    """The HTTP method `gh api` sends: the one named, else GET."""
    for index, token in enumerate(tokens):
        if token in ("-X", "--method"):
            return (tokens[index + 1] if index + 1 < len(tokens) else "").upper()
        if token.startswith("--method="):
            return token.split("=", 1)[1].upper()
    return "GET"


def gh_api_path(tokens: list[str]) -> str:
    """The endpoint `gh api` is pointed at: its one operand, flag values skipped."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            index += 2 if token in API_VALUE_FLAGS else 1
            continue
        return token
    return ""


def gh_api_violation(part: str) -> Optional[str]:
    """The deny reason for a `gh api` part that writes a repository or org setting."""
    if not GH_API.match(part):
        return None
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None

    rest = tokens[tokens.index("api") + 1 :] if "api" in tokens else tokens[2:]
    method = gh_api_method(rest)
    if method not in WRITE_METHODS:
        return None

    path = gh_api_path(rest)
    if API_WRITE_PATH.match(path):
        return f"gh api {method} {path} changes a repository or org setting. {IAC_REASON}"
    return None


def release_violation(part: str, root: Optional[str]) -> Optional[str]:
    """The deny reason for a `gh release` part when release-please is configured."""
    if not GH_RELEASE.match(part):
        return None
    if root and os.path.isfile(os.path.join(root, "release-please-config.json")):
        return RELEASE_REASON
    return None


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    cwd = payload.get("cwd") or os.getcwd()
    root = _common.repo_root(cwd)

    for raw_part in _common.command_parts(command):
        part = _common.strip_env_prefix(raw_part)
        if not part.startswith("gh "):
            continue

        if (
            GH_REPO.match(part)
            or GH_LABEL.match(part)
            or GH_SECRET.match(part)
            or GH_VARIABLE.match(part)
        ):
            return _common.deny(EVENT, IAC_REASON)

        reason = gh_api_violation(part) or release_violation(part, root)
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(main())
