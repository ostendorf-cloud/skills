#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies repository, organisation, label, ruleset or secret
changes made through `gh` or the API, a pull request write through the API, a GraphQL
mutation through `gh api graphql`, `gh release` where the repository's release tool
(release-me or release-please) owns releases, and `gh repo rename`, `gh repo
set-default`, `gh alias` or `gh extension`, which run arbitrary code or point the CLI
somewhere else entirely.

Every `gh` check finds the subcommand behind the flags in front of it, so a flag
placed between the noun and the subcommand does not hide the command.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

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

# The subcommands of each `gh` noun that change infrastructure as code, and of the two
# nouns that point the CLI at arbitrary code.
GH_IAC_MUTATIONS = {
    "repo": {"create", "delete", "edit", "rename", "set-default"},
    "label": {"clone", "create", "delete", "edit"},
    "secret": {"delete", "remove", "set"},
    "variable": {"delete", "set"},
}
GH_CODE_MUTATIONS = {
    "alias": {"delete", "import", "set"},
    "extension": {"exec", "install", "remove", "upgrade"},
}
GH_RELEASE_MUTATIONS = {"create", "delete", "edit", "upload"}

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
    tokens = _common.shell_tokens(part)
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


def gh_noun_subcommand(part: str, noun: str) -> str:
    """The subcommand a `gh <noun>` part dispatches to, the flags between the noun and
    the subcommand skipped. "" when part is not `gh <noun>`, or names no subcommand.

    gh is built on cobra, which skips flags while it looks up the subcommand and
    treats a flag it does not know at that level as taking the following token as its
    value. `gh label -R owner/repo create bug`, `gh secret --repo=owner/repo set X`
    and `gh auth --hostname example.com token` all reach their subcommand that way, so
    the check cannot be a regex anchored on `gh <noun> <subcommand>`. No gh noun
    carries a persistent flag that takes no value, so there is no exception to that
    rule.
    """
    tokens = _common.shell_tokens(part)
    if len(tokens) < 3 or tokens[0] != "gh" or tokens[1] != noun:
        return ""
    return _common.subcommand_after(tokens[2:], space_form_takes_value=True)


def gh_noun_violation(part: str) -> Optional[str]:
    """The deny reason for a `gh <noun>` part whose real subcommand changes
    infrastructure as code or points the CLI at arbitrary code."""
    for noun, mutations in GH_IAC_MUTATIONS.items():
        if gh_noun_subcommand(part, noun) in mutations:
            return IAC_REASON
    for noun, mutations in GH_CODE_MUTATIONS.items():
        if gh_noun_subcommand(part, noun) in mutations:
            return ALIAS_EXTENSION_REASON
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
    if gh_noun_subcommand(part, "release") not in GH_RELEASE_MUTATIONS:
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

        reason = (
            gh_noun_violation(part)
            or graphql_violation(part)
            or gh_api_violation(part)
            or release_violation(part, root)
        )
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
