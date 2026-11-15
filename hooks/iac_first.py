#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies repository, organisation, label, ruleset or secret
changes made through `gh` or the API, a pull request write through the API, a GraphQL
mutation through `gh api graphql`, `gh release` where the repository's release tool
(release-me or release-please) owns releases, and `gh repo rename`, `gh repo
set-default`, `gh alias` or `gh extension`, which run arbitrary code or point the CLI
somewhere else entirely.

Two review calls stay open: a POST to `pulls/<n>/reviews` and a GraphQL mutation whose
only field is `resolveReviewThread`. Every other pull request write and mutation is denied.

Every `gh` check finds the subcommand behind the flags in front of it, so neither a
flag placed in front of the noun nor one placed between the noun and the subcommand
hides the command. Every part is normalised before the checks run, so a wrapper prefix
such as `sudo`, `env` or `mise exec --` in front of gh does not hide it either.
"""

import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

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
# The one pull request write that stays open: posting a review, the verdict path of the
# work-review skill. Exactly this path, no query string, no further segment.
REVIEW_POST_PATH = re.compile(r"^/?repos/[^/]+/[^/]+/pulls/[0-9]+/reviews$")
# The one GraphQL mutation that stays open: resolving a review thread.
ALLOWED_MUTATION = "resolveReviewThread"

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


def gh_command_name(part: str) -> str:
    """The name of the command part runs, resolved the way the checks below resolve it.

    The checks all tokenise with shell_tokens, so the gate in front of them has to see
    the same first token they do: `'gh' label create bug` runs gh, and a gate that
    splits on whitespace alone reads the quotes as part of the name and lets it past.
    Falls back to command_name when the quoting does not parse, so a malformed part
    still reaches malformed_quoting_violation rather than being skipped here.
    """
    tokens = _common.shell_tokens(part)
    if not tokens:
        return _common.command_name(part)
    return _common.token_name(tokens[0])


def gh_api_method(tokens: list[str]) -> str:
    """The HTTP method `gh api` sends: the one named, else GET.

    tokens are every argument after `gh`, not only the ones after `api`, because gh
    applies a flag of `api` whichever side of the word it sits on and the subcommand
    lookup consumes `--method PATCH` in front of it as a flag and its value.
    """
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
    tokens = _common.shell_tokens(part)
    dispatch = _common.gh_dispatch(tokens)
    if not dispatch or dispatch[0] != "api":
        return None
    method = gh_api_method(tokens[1:])
    if method not in WRITE_METHODS:
        return None

    path = gh_api_path(dispatch[1:])
    if method == "POST" and REVIEW_POST_PATH.match(path):
        return None
    if PULLS_WRITE_PATH.match(path):
        return f"gh api {method} {path} changes a pull request. {PULLS_REASON}"
    if API_WRITE_PATH.match(path):
        return f"gh api {method} {path} changes a repository or org setting. {IAC_REASON}"
    return None


def gh_noun_subcommand(part: str, noun: str) -> str:
    """The subcommand a `gh <noun>` part dispatches to, the flags in front of the noun
    itself and the flags between the noun and the subcommand both skipped. "" when part
    does not dispatch to noun, or names no subcommand under it.

    cobra applies the same lookup at both levels, so `gh --repo owner/repo secret set X`,
    `gh label -R owner/repo create bug` and `gh secret --repo=owner/repo set X` all reach
    their subcommand and the check cannot be a regex anchored on `gh <noun>
    <subcommand>`. No gh noun carries a persistent flag that takes no value, so there is
    no exception to that rule.
    """
    dispatch = _common.gh_dispatch(_common.shell_tokens(part))
    if not dispatch or dispatch[0] != noun:
        return ""
    return _common.subcommand_after(dispatch[1:], space_form_takes_value=True)


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
    dispatch = _common.gh_dispatch(_common.shell_tokens(part))
    if not dispatch or dispatch[0] != "api":
        return None
    if gh_api_path(dispatch[1:]) != "graphql":
        return None
    if GRAPHQL_MUTATION.search(part):
        if only_resolves_review_thread(part):
            return None
        return GRAPHQL_REASON
    return None


def mutation_fields(query: str) -> Optional[list[str]]:
    """The top level fields of the one operation in a GraphQL document, or None when
    the document is not a single operation this reads with certainty.

    The document is tokenized first: string literals, block strings and comments are
    skipped, so a brace inside one never counts. Aliases, arguments, selections below
    the first level and directives are skipped. A document with a second definition, a
    fragment spread, an unbalanced bracket, an unterminated string or any character
    this does not know gives None.
    """
    tokens = graphql_tokens(query)
    if tokens is None:
        return None
    fields: list[str] = []
    depth = 0
    nested = 0
    definitions = 0
    for index, token in enumerate(tokens):
        if token in ("(", "["):
            nested += 1
        elif token in (")", "]"):
            nested -= 1
        elif token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                definitions += 1
        elif token == "...":
            return None
        elif depth == 1 and nested == 0 and GRAPHQL_NAME.match(token):
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            preceding = tokens[index - 1] if index else ""
            if following != ":" and preceding not in ("@", "$"):
                fields.append(token)
        if depth < 0 or nested < 0:
            return None
    if depth != 0 or nested != 0 or definitions != 1:
        return None
    return fields


GRAPHQL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GRAPHQL_TOKEN = re.compile(
    r"[ \t\r\n,﻿]+|(?P<comment>#[^\n]*)|(?P<spread>\.\.\.)|(?P<punct>[{}()\[\]:@$!=|&])"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<number>-?[0-9][0-9.eE+-]*)"
)


def graphql_tokens(query: str) -> Optional[list[str]]:
    """The punctuators and names of a GraphQL document, strings, numbers, whitespace,
    commas and comments left out. None when the document does not tokenize cleanly:
    an unterminated string, a line break inside a plain string, or a character outside
    the GraphQL lexical grammar."""
    tokens: list[str] = []
    position = 0
    length = len(query)
    while position < length:
        if query.startswith('"""', position):
            position = _block_string_end(query, position + 3)
        elif query[position] == '"':
            position = _string_end(query, position + 1)
        else:
            match = GRAPHQL_TOKEN.match(query, position)
            if not match:
                return None
            position = match.end()
            if match.lastgroup in ("spread", "punct", "name"):
                tokens.append(match.group(0))
        if position < 0:
            return None
    return tokens


def _string_end(query: str, start: int) -> int:
    """The index after the closing quote of a plain string whose body starts at start,
    or -1 when it is unterminated or holds a line break."""
    position = start
    while position < len(query):
        char = query[position]
        if char == "\\":
            position += 2
            continue
        if char == '"':
            return position + 1
        if char in "\r\n":
            return -1
        position += 1
    return -1


def _block_string_end(query: str, start: int) -> int:
    """The index after the closing triple quote of a block string whose body starts at
    start, or -1 when it is unterminated. A backslash before a triple quote escapes it."""
    position = start
    while position < len(query):
        if query.startswith('\\"""', position):
            position += 4
            continue
        if query.startswith('"""', position):
            return position + 3
        position += 1
    return -1


def only_resolves_review_thread(part: str) -> bool:
    """Whether the only GraphQL mutation in a `gh api graphql` part is resolving a review
    thread: one `query=` value holding one operation whose single top level field is
    resolveReviewThread, and no other word of the part naming a mutation."""
    tokens = _common.shell_tokens(part)
    queries = [token.split("=", 1)[1] for token in tokens if token.startswith("query=")]
    if len(queries) != 1 or not GRAPHQL_MUTATION.search(queries[0]):
        return False
    if any(token == "--input" or token.startswith("--input=") for token in tokens):
        return False
    if len(GRAPHQL_MUTATION.findall(queries[0])) != 1:
        return False
    if any(GRAPHQL_MUTATION.search(token) for token in tokens if not token.startswith("query=")):
        return False
    return mutation_fields(queries[0]) == [ALLOWED_MUTATION]


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
        part = _common.normalize_command_part(raw_part)
        if gh_command_name(part) != "gh":
            continue

        reason = (
            _common.malformed_quoting_violation(part)
            or gh_noun_violation(part)
            or graphql_violation(part)
            or gh_api_violation(part)
            or release_violation(part, root)
        )
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
