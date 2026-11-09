#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies repository, organisation, label, ruleset or secret
changes made through `gh` or the API, a pull request write through the API, a GraphQL
mutation through `gh api graphql`, `gh release` where the repository's release tool
(release-me or release-please) owns releases, and `gh repo rename`, `gh repo
set-default`, `gh alias` or `gh extension`, which run arbitrary code or point the CLI
somewhere else entirely.
"""

import os
import re
import shlex
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

GH_REPO = re.compile(r"^gh\s+repo\s+(edit|delete|create|rename|set-default)\b")
GH_LABEL_PREFIX = re.compile(r"^gh\s+label\b")
GH_SECRET = re.compile(r"^gh\s+secret\s+(set|delete|remove)\b")
GH_VARIABLE = re.compile(r"^gh\s+variable\s+(set|delete)\b")
GH_RELEASE = re.compile(r"^gh\s+release\s+(create|delete|edit|upload)\b")
GH_ALIAS = re.compile(r"^gh\s+alias\s+(set|delete|import)\b")
GH_EXTENSION = re.compile(r"^gh\s+extension\s+(install|exec|upgrade|remove)\b")
GH_API = re.compile(r"^gh\s+api\b")
GH_API_GRAPHQL = re.compile(r"^gh\s+api\s+graphql\b")
GRAPHQL_MUTATION = re.compile(r"\bmutation\b", re.IGNORECASE)

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

GH_LABEL_MUTATIONS = {"create", "edit", "delete", "clone"}
GH_LABEL_VALUE_FLAGS = {"-R", "--repo"}

API_WRITE_PATH = re.compile(
    r"^(/)?(repos/[^/]+/[^/]+(/labels|/rulesets|/branches/.*/protection|"
    r"/actions/secrets|/actions/variables|$)|orgs/[^/]+|user/repos)"
)
PULLS_WRITE_PATH = re.compile(r"^(/)?repos/[^/]+/[^/]+/pulls(/.*)?$")

IAC_REASON = (
    "Repository and organisation settings, labels, rulesets and secrets are "
    "infrastructure as code. Propose the change in the infrastructure repository "
    "instead of changing it with gh."
)
RELEASE_REASON = (
    "The repository's release tool (release-me or release-please) owns releases "
    "here. The release pull request cuts the release; do not run gh release directly."
)
PULLS_REASON = (
    "This changes a pull request directly through the API, routing around gh pr "
    "merge and its merge prompts. Use gh pr merge, gh pr edit or gh pr review instead."
)
GRAPHQL_REASON = (
    "This runs a GraphQL mutation through gh api, which can merge a pull request or "
    "change other state while routing around the normal merge prompts. Use the "
    "dedicated gh command instead."
)
ALIAS_EXTENSION_REASON = (
    "gh alias and gh extension can point the CLI at arbitrary, unsandboxed code. "
    "Run the underlying command directly instead."
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
    if PULLS_WRITE_PATH.match(path):
        return f"gh api {method} {path} changes a pull request. {PULLS_REASON}"
    if API_WRITE_PATH.match(path):
        return f"gh api {method} {path} changes a repository or org setting. {IAC_REASON}"
    return None


def gh_label_subcommand(tokens: list[str]) -> str:
    """The subcommand `gh label` is given: its first operand, flag values skipped."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            index += 2 if token in GH_LABEL_VALUE_FLAGS else 1
            continue
        return token
    return ""


def gh_label_violation(part: str) -> Optional[str]:
    """The deny reason for a `gh label` part whose real subcommand mutates a label,
    regardless of flags placed between `gh label` and the subcommand."""
    if not GH_LABEL_PREFIX.match(part):
        return None
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None

    rest = tokens[tokens.index("label") + 1 :] if "label" in tokens else tokens[2:]
    if gh_label_subcommand(rest) in GH_LABEL_MUTATIONS:
        return IAC_REASON
    return None


def graphql_violation(part: str) -> Optional[str]:
    """The deny reason for a `gh api graphql` part whose body runs a mutation."""
    if not GH_API_GRAPHQL.match(part):
        return None
    if GRAPHQL_MUTATION.search(part):
        return GRAPHQL_REASON
    return None


def release_violation(part: str, root: Optional[str]) -> Optional[str]:
    """The deny reason for a `gh release` part when the repository's release tool,
    release-me or release-please, is configured."""
    if not GH_RELEASE.match(part):
        return None
    if root and (
        os.path.isfile(os.path.join(root, "release-me.yaml"))
        or os.path.isfile(os.path.join(root, "release-please-config.json"))
    ):
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

        if GH_REPO.match(part) or GH_SECRET.match(part) or GH_VARIABLE.match(part):
            return _common.deny(EVENT, IAC_REASON)

        if GH_ALIAS.match(part) or GH_EXTENSION.match(part):
            return _common.deny(EVENT, ALIAS_EXTENSION_REASON)

        reason = (
            gh_label_violation(part)
            or graphql_violation(part)
            or gh_api_violation(part)
            or release_violation(part, root)
        )
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
