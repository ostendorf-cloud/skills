#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a write-up of a finding in a public repository: the
title, label or text of a `gh issue create|edit|comment`, `gh pr create|edit|comment|review`,
a `gh api` write to an issue, pull request or comment (REST, or a GraphQL mutation that
creates or updates one), a `gh label create|edit`, or a `git commit` message, when it
carries the finding vocabulary (the VOCABULARY table below, plus the `security` label).

Design: a sibling of tracker_body.py, not an extension. tracker_body.py is about
attribution only and the two rules change for different reasons, so each hook keeps one
purpose. The command splitting, wrapper stripping and flag value helpers are imported
from tracker_body.py and commit_message.py unchanged, so their behaviour stays as tested.

The vocabulary is a net, so it is conservative: it matches finding shapes such as
`SQL injection` or `a vulnerability in`, not the bare words that normal work uses
(`dependency injection`, `vulnerability database`, `add a CodeQL workflow`).

The repository is public unless the lookup says otherwise. The target comes from
`--repo`/`-R`, the endpoint of a `gh api` call, or the git remote `origin` of the working
directory. The placeholders `{owner}` and `{repo}` of a `gh api` endpoint stand for that
remote. The lookup runs only after a vocabulary match, `gh repo view <slug> --json
isPrivate`, with a short timeout. Answers are cached in a file under $TMPDIR, keyed by
session and repository: a public answer for an hour, a private answer for ten minutes (a
repository may be made public), a failure for one minute. A cache entry that is odd or
corrupt counts as a miss, because the agent can write that file.

A failed lookup is the documented fail closed case, not an internal error: it denies, with
its own reason that names the failure. An internal error in the hook itself prints `{}`.

Tests replace the lookup through the environment variable AGENT_SKILLS_VISIBILITY_CMD, an
executable called with the slug that prints `true` or `false`. No test uses the network.

A repository opts out of words in `.agent-skills.json`, read from the repository root of
the working directory: `{"publicFindings": {"allowWords": ["alert"]}}`. The entries are
names from VOCABULARY or the label name `security`. The list applies only when the target
repository is the one the working directory belongs to.

A message or body file is read only from the session scratch scope ($TMPDIR) or below the
working directory. Any other path, or a file that cannot be read, counts as unreadable and
is allowed. Standard input falls back to scanning the raw command text, as in tracker_body,
and for a commit to the heredoc that feeds it.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402
import commit_message  # noqa: E402
import tracker_body  # noqa: E402

EVENT = "PreToolUse"

VISIBILITY_CMD_ENV = "AGENT_SKILLS_VISIBILITY_CMD"
LOOKUP_TIMEOUT = 5
CACHE_NAME = "agent-skills-public-findings.json"
TTL_PUBLIC = 3600
TTL_PRIVATE = 600
TTL_FAILURE = 60

SECURITY_LABEL = "security"

INJECTION_KINDS = "sql|command|template|header|prompt|code|html|log|ldap|xpath|os|email"

VOCABULARY = {
    "cve": re.compile(r"CVE-\d", re.IGNORECASE),
    "ghsa": re.compile(r"GHSA-", re.IGNORECASE),
    "codeql": re.compile(r"CodeQL\s+(?:alerts?|findings?|results?)\b", re.IGNORECASE),
    "code scanning": re.compile(r"code[\s-]+scanning\s+(?:alerts?|findings?|results?)\b", re.I),
    "alert": re.compile(r"alert\s*#?\d", re.IGNORECASE),
    "vulnerab": re.compile(
        r"\b(?:a|an|the|this|that)\s+(?:\w+\s+){0,2}vulnerabilit(?:y|ies)\s+(?:in|of|that)\b"
        r"|vulnerable\s+to\b|\bis\s+vulnerable\b|vulnerabilities\s+found"
        r"|security\s+vulnerabilit",
        re.IGNORECASE,
    ),
    "exploit": re.compile(r"\bexploit(?:s|able)?\b", re.IGNORECASE),
    "injection": re.compile(rf"\b(?:{INJECTION_KINDS})[\s-]+injection\b", re.IGNORECASE),
    "xss": re.compile(r"\bXSS\b", re.IGNORECASE),
    "ssrf": re.compile(r"\bSSRF\b", re.IGNORECASE),
    "path traversal": re.compile(r"path\s+traversal", re.IGNORECASE),
    "sanitiz": re.compile(
        r"\bun-?sanitiz?s?ed\b"
        r"|\b(?:missing|incomplete|insufficient|bad|improper|no)\s+(?:\w+\s+)?saniti[sz]ation",
        re.IGNORECASE,
    ),
}

PR_SUBCOMMANDS = frozenset({"create", "edit", "comment", "review"})
ISSUE_SUBCOMMANDS = frozenset({"create", "edit", "comment"})
LABEL_SUBCOMMANDS = frozenset({"create", "edit"})
LABEL_VALUE_FLAGS = frozenset(
    {"-c", "--color", "-d", "--description", "-n", "--name", "-R", "--repo"}
)

TITLE_FLAGS = (("--title",), ("-t",))
LABEL_FLAGS = (("--label", "--add-label"), ("-l",))
METHOD_FLAGS = (("--method",), ("-X",))
REPO_FLAGS = (("--repo",), ("-R",))

API_VALUE_FLAGS = frozenset(
    {
        "-X",
        "--method",
        "-f",
        "-F",
        "--field",
        "--raw-field",
        "-H",
        "--header",
        "--input",
        "--jq",
        "-q",
        "--template",
        "-t",
        "--hostname",
        "--cache",
        "-p",
        "--preview",
    }
)
API_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT"})
API_TRACKER_ENDPOINT = re.compile(r"(?:^|/)(?:issues|pulls|comments|reviews)(?:/|$)")
API_TEXT_KEYS = frozenset({"title", "body", "labels", "labels[]"})
API_ENDPOINT_REPO = re.compile(r"^/?repos/([^/\s]+)/([^/\s]+)")
GRAPHQL_MUTATION = re.compile(
    r"\b(?:addComment|createIssue|updateIssue|addPullRequestReview|"
    r"addPullRequestReviewComment|updatePullRequest|createPullRequest)\b"
)
REMOTE_SLUG = re.compile(r"[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$")
VALID_SLUG = re.compile(r"^[\w.][\w.-]*/[\w.][\w.-]*$")

DENY_PUBLIC = (
    "A public repository gets no write-up of a finding before the fix is merged (matched: "
    "{words}). Use a draft security advisory, a plain title and body such as "
    '"resolve static analysis findings" with no finding detail, or publicFindings.allowWords '
    "in .agent-skills.json when the repository's own subject is this vocabulary."
)
DENY_UNKNOWN = (
    "The visibility of {slug} could not be read ({error}), and an unknown repository counts "
    "as public. Retry, or write a plain title and body with no finding detail (matched: "
    "{words})."
)


def allowed_words(directory: Optional[str]) -> frozenset[str]:
    """The words the repository of directory opts out of, lower case. Empty when the
    config is absent, invalid or names no list."""
    config = _common.agent_skills_config(_common.repo_root(directory))
    section = config.get("publicFindings")
    if not isinstance(section, dict):
        return frozenset()
    words = section.get("allowWords")
    if not isinstance(words, list):
        return frozenset()
    return frozenset(word.strip().lower() for word in words if isinstance(word, str))


def finding_words(texts: list[str], labels: list[str], allow: frozenset[str]) -> list[str]:
    """The vocabulary names that texts or labels match and allow does not opt out of."""
    found: list[str] = []
    if SECURITY_LABEL not in allow:
        for label in labels:
            for item in label.split(","):
                if item.strip().lower() == SECURITY_LABEL and SECURITY_LABEL not in found:
                    found.append(SECURITY_LABEL)
    for name, pattern in VOCABULARY.items():
        if name in allow:
            continue
        if any(pattern.search(text) for text in texts):
            found.append(name)
    return found


def readable_path(path: str, cwd: Optional[str]) -> Optional[str]:
    """The resolved path when it lies in the session scratch scope or below cwd, else
    None. The hook never reads a file elsewhere on behalf of a command."""
    full = path if os.path.isabs(path) else os.path.join(cwd or "", path)
    real = os.path.realpath(full)
    roots = list(_common.scratch_roots())
    if cwd:
        roots.append(os.path.realpath(cwd))
    for root in roots:
        try:
            if os.path.commonpath([root, real]) == root:
                return real
        except ValueError:
            continue
    return None


def read_text(path: str, cwd: Optional[str]) -> Optional[str]:
    """The content of path, or None when it is out of scope or cannot be read."""
    real = readable_path(path, cwd)
    if real is None:
        return None
    try:
        with open(real, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def file_texts(paths: list[str], full_command: str, cwd: Optional[str]) -> list[str]:
    """The readable text of every path, with the stdin fallback of tracker_body."""
    texts: list[str] = []
    for path in paths:
        if path in tracker_body.STDIN_MARKERS:
            texts.append(full_command)
            continue
        content = read_text(path, cwd)
        if content:
            texts.append(content)
    return texts


def values_of(tokens: list[str], flags: tuple[tuple[str, ...], tuple[str, ...]]) -> list[str]:
    """Every value of a long and short flag group, see tracker_body.flag_values."""
    return tracker_body.flag_values(tokens, flags[0], flags[1])


def slug_from_remote(directory: Optional[str]) -> str:
    """owner/name from the origin remote of directory, "" when unknown."""
    url = _common.run_git(["remote", "get-url", "origin"], directory)
    if not url:
        return ""
    match = REMOTE_SLUG.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def cache_path() -> str:
    """The cache file, under $TMPDIR."""
    return os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), CACHE_NAME)


def cache_key(session: str, slug: str) -> str:
    """The cache key of a repository within a session."""
    return f"{session}|{slug.lower()}"


def read_cache() -> dict[str, Any]:
    """The cache entries by key, {} when there is no readable cache."""
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def entry_answer(entry: Any, now: float) -> Optional[tuple[Optional[bool], str]]:
    """The (private, error) answer of a cache entry, None when the entry is odd, from
    the future or older than its time to live. The file is writable by the agent, so
    every field is checked."""
    if not isinstance(entry, dict):
        return None
    stamp, private, error = entry.get("at"), entry.get("private"), entry.get("error", "")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    if private is not None and not isinstance(private, bool):
        return None
    if not isinstance(error, str):
        return None
    if private is None:
        ttl = TTL_FAILURE
    else:
        ttl = TTL_PRIVATE if private else TTL_PUBLIC
    age = now - stamp
    if age < 0 or age >= ttl:
        return None
    return private, error


def write_cache(key: str, private: Optional[bool], error: str) -> None:
    """Remembers an answer. Expired or odd entries are dropped. A cache that cannot be
    written is skipped."""
    now = time.time()
    data = {k: v for k, v in read_cache().items() if entry_answer(v, now) is not None}
    data[key] = {"at": now, "private": private, "error": error}
    try:
        with open(cache_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        pass


def lookup_private(slug: str) -> tuple[Optional[bool], str]:
    """(private, error): whether the repository is private, None with the reason when
    the answer cannot be read."""
    override = os.environ.get(VISIBILITY_CMD_ENV)
    if override:
        command = [override, slug]
    else:
        command = ["gh", "repo", "view", slug, "--json", "isPrivate", "--jq", ".isPrivate"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {LOOKUP_TIMEOUT} seconds"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:120]
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        return None, (lines[0] if lines else f"exit status {result.returncode}")[:120]
    answer = result.stdout.strip().lower()
    if answer == "true":
        return True, ""
    if answer == "false":
        return False, ""
    return None, "unexpected answer"


def visibility(slug: str, session: str) -> tuple[Optional[bool], str]:
    """(private, error) for slug, from the cache or the lookup. A slug that is not a plain
    owner/name is never looked up."""
    if not slug:
        return None, "no owner/name found"
    if not VALID_SLUG.match(slug):
        return None, "not a plain owner/name"
    key = cache_key(session, slug)
    cached = entry_answer(read_cache().get(key), time.time())
    if cached is not None:
        return cached
    private, error = lookup_private(slug)
    write_cache(key, private, error)
    return private, error


def gh_write(
    part: str, full_command: str, cwd: Optional[str]
) -> Optional[tuple[list[str], list[str], str]]:
    """(texts, labels, repo slug) a matched `gh` part would write, None when the part is
    not a covered write or does not parse. Expects wrapper prefixes already removed."""
    if _common.command_name(part) != "gh":
        return None
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None
    dispatch = _common.gh_dispatch(["gh"] + tokens[1:])
    if not dispatch:
        return None
    noun = dispatch[0]
    sub = _common.subcommand_after(dispatch[1:], space_form_takes_value=True)
    repo = (values_of(tokens, REPO_FLAGS) or [""])[-1]

    if (noun == "pr" and sub in PR_SUBCOMMANDS) or (noun == "issue" and sub in ISSUE_SUBCOMMANDS):
        texts = values_of(tokens, TITLE_FLAGS)
        texts.extend(tracker_body.flag_values(tokens, ("--body",), ("-b",)))
        paths = tracker_body.flag_values(tokens, ("--body-file",), ("-F",))
        texts.extend(file_texts(paths, full_command, cwd))
        return texts, values_of(tokens, LABEL_FLAGS), repo

    if noun == "label" and sub in LABEL_SUBCOMMANDS:
        operands = _common.subcommand_tokens(dispatch[2:], LABEL_VALUE_FLAGS)
        names = tracker_body.flag_values(tokens, ("--name",), ("-n",))
        labels = ([operands[0]] if operands else []) + names
        texts = tracker_body.flag_values(tokens, ("--description",), ("-d",))
        return texts, labels, repo

    if noun == "api":
        return api_write(tokens, dispatch, full_command, cwd, repo)
    return None


def api_write(
    tokens: list[str], dispatch: list[str], full_command: str, cwd: Optional[str], repo: str
) -> Optional[tuple[list[str], list[str], str]]:
    """The same triple for a `gh api` call that writes to an issue, pull request or
    comment. A call with fields and no method is a POST, as gh itself treats it. A
    GraphQL call counts when its query holds a mutation that creates or updates one."""
    operands = _common.subcommand_tokens(dispatch[1:], API_VALUE_FLAGS)
    endpoint = operands[0] if operands else ""
    if "{" in endpoint:
        origin = slug_from_remote(cwd).split("/")
        if len(origin) == 2:
            endpoint = endpoint.replace("{owner}", origin[0]).replace("{repo}", origin[1])

    fields = tracker_body.flag_values(tokens, ("--field", "--raw-field"), ("-f", "-F"))
    inputs = tracker_body.flag_values(tokens, ("--input",), ())

    if endpoint == "graphql":
        return graphql_write(fields, inputs, full_command, cwd, repo)

    if not API_TRACKER_ENDPOINT.search(endpoint.split("?", 1)[0]):
        return None

    methods = [value.upper() for value in values_of(tokens, METHOD_FLAGS)]
    if methods:
        if methods[-1] not in API_WRITE_METHODS:
            return None
    elif not fields and not inputs:
        return None

    texts: list[str] = []
    labels: list[str] = []
    for value in fields:
        key, separator, rest = value.partition("=")
        if not separator or key not in API_TEXT_KEYS:
            continue
        if rest.startswith("@") and len(rest) > 1:
            texts.extend(file_texts([rest[1:]], full_command, cwd))
        elif key.startswith("labels"):
            labels.append(rest)
        else:
            texts.append(rest)
    texts.extend(file_texts(inputs, full_command, cwd))

    match = API_ENDPOINT_REPO.match(endpoint)
    slug = f"{match.group(1)}/{match.group(2)}" if match else repo
    return texts, labels, slug


def graphql_write(
    fields: list[str], inputs: list[str], full_command: str, cwd: Optional[str], repo: str
) -> Optional[tuple[list[str], list[str], str]]:
    """The triple for a `gh api graphql` call whose query is a covered mutation. The
    query, its variables and any input file are scanned as text."""
    texts: list[str] = []
    for value in fields:
        key, separator, rest = value.partition("=")
        if not separator:
            continue
        if rest.startswith("@") and len(rest) > 1:
            texts.extend(file_texts([rest[1:]], full_command, cwd))
        else:
            texts.append(rest)
    texts.extend(file_texts(inputs, full_command, cwd))
    if not any(GRAPHQL_MUTATION.search(text) for text in texts):
        return None
    return texts, [], repo


def commit_texts(tokens: list[str], command: str, cwd: Optional[str]) -> list[str]:
    """The message texts a `git commit` token list would write: every -m, --message,
    -F and --file value, also inside a short flag cluster such as `-am`. Standard input
    falls back to the heredoc that feeds it. An unreadable file adds nothing."""
    texts: list[str] = []
    files: list[str] = []
    index = tokens.index("commit") + 1
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == "--":
            break
        if token.startswith("--message=") or token.startswith("--file="):
            value = token.split("=", 1)[1]
            (texts if token.startswith("--message") else files).append(value)
        elif token in ("--message", "--file"):
            if index < len(tokens):
                (texts if token == "--message" else files).append(tokens[index])
                index += 1
        elif token.startswith("-") and not token.startswith("--") and len(token) > 1:
            cluster = token[1:]
            for position, letter in enumerate(cluster):
                if letter not in "mF":
                    continue
                value = cluster[position + 1 :]
                if not value and index < len(tokens):
                    value = tokens[index]
                    index += 1
                (texts if letter == "m" else files).append(value)
                break
    for path in files:
        if path == "-":
            heredoc = commit_message.HEREDOC_MESSAGE.search(command)
            if heredoc:
                texts.append(heredoc.group(2))
            continue
        content = read_text(path, cwd)
        if content:
            texts.append(content)
    return texts


def deny_reason(
    texts: list[str], labels: list[str], slug: str, directory: Optional[str], session: str
) -> Optional[str]:
    """The deny reason when the write is a finding write-up in a public or unknown
    repository, else None."""
    if not finding_words(texts, labels, frozenset()):
        return None
    allow: frozenset[str] = frozenset()
    origin = slug_from_remote(directory)
    if origin and slug and origin.lower() == slug.lower():
        allow = allowed_words(directory)
    found = finding_words(texts, labels, allow)
    if not found:
        return None
    private, error = visibility(slug, session)
    words = ", ".join(found)
    if private is True:
        return None
    if private is None:
        return DENY_UNKNOWN.format(slug=slug or "this repository", error=error, words=words)
    return DENY_PUBLIC.format(words=words)


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()
    cwd = payload.get("cwd") or os.getcwd()
    session = payload.get("session_id")
    session = session if isinstance(session, str) else ""

    for raw_part, directory in _common.part_dirs(command, cwd):
        part = _common.strip_wrappers(raw_part)
        where = directory or cwd

        if _common.command_name(part) == "gh":
            write = gh_write(part, command, where)
            if write is None:
                continue
            texts, labels, repo = write
            slug = repo or slug_from_remote(where)
            reason = deny_reason(texts, labels, slug, where, session)
            if reason:
                return _common.deny(EVENT, reason)
            continue

        normalized = _common.normalize_command_part(raw_part)
        stripped, path = _common.strip_global_git_options(normalized)
        try:
            tokens = shlex.split(stripped)
        except ValueError:
            continue
        if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "commit":
            continue
        commit_dir = _common.git_part_dir(raw_part, directory, path)
        if _common.in_scratch(commit_dir):
            continue
        target = commit_dir or where
        texts = commit_texts(tokens, command, target)
        if not texts:
            continue
        reason = deny_reason(texts, [], slug_from_remote(target), target, session)
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
