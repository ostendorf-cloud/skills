#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a command that prints a secret to the transcript, and
a `git commit` whose staged diff holds a credential pattern or a file that never belongs
in git. The commit check runs gitleaks when it is on PATH and falls back to a regex scan
otherwise. Never prints the matched value, only the file and line number.

A command that prints a secret is found behind the flags in front of its subcommand, so
a global option placed before the noun or between the noun and the subcommand does not
hide it. A policed command whose own quoting does not parse is denied rather than passed
through unexamined.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

# bao takes every flag after the subcommand and rejects one in front of it, so its
# subcommand is always the next word. That was verified against bao 2.0.0, which answers
# `Invalid flags before the subcommand`. vault is bao's upstream and shares the CLI, so
# the same is assumed for it, not independently confirmed. The tofu patterns run
# against the part with the global options already stripped, and `tofu state` takes no
# flag in front of its own subcommand either. The tools that do accept a flag there
# have a check of their own below.
SECRET_COMMANDS = (
    re.compile(r"^bao\s+kv\s+get\b"),
    re.compile(r"^bao\s+read\b"),
    re.compile(r"^vault\s+kv\s+get\b"),
    re.compile(r"^vault\s+read\b"),
    re.compile(r"^tofu\s+output\b"),
    re.compile(r"^tofu\s+state\s+(show|pull)\b"),
)

# tofu's only global options, the ones it accepts in front of the subcommand. -chdir
# takes its value in the same token: the space form is rejected.
TOFU_GLOBAL_OPTION = re.compile(r"^-(chdir=.*|help|h|version|v)$")

# bws is a clap CLI. Its global options are accepted in front of `secret` and between
# `secret` and the subcommand, and these are the ones that take a value.
BWS_VALUE_FLAGS = frozenset(
    {
        "-o",
        "--output",
        "-c",
        "--color",
        "-t",
        "--access-token",
        "-f",
        "--config-file",
        "-p",
        "--profile",
        "-u",
        "--server-url",
    }
)
BWS_SECRET_READS = frozenset({"get", "list"})

# bw takes its global options in front of the command. Of those, only --session takes a
# value; --pretty, --raw, --response, --quiet and --nointeraction take none.
BW_VALUE_FLAGS = frozenset({"--session"})

KUBECTL_SECRET_NOUNS = frozenset({"secret", "secrets"})
KUBECTL_OUTPUT_FORMAT = re.compile(r"(-o|--output)[\s=]+([A-Za-z-]+)")
# The output formats that render the secret's data map, and so its encoded value, into
# the transcript. Matched as prefixes, which covers every data printing format
# `kubectl get --help` documents: `yaml`, `kyaml`, `json`, `jsonpath`,
# `jsonpath-as-json`, `jsonpath-file`, `template`, `templatefile`, `go-template`,
# `go-template-file`, `custom-columns` and `custom-columns-file`. `template` is
# kubectl's own alias of `go-template` and `kyaml` its YAML with managed fields, so
# both need an entry of their own rather than sharing a prefix with the format they
# resemble. `name` and `wide` are the only two formats kubectl offers that print no
# data map, and they stay allowed.
KUBECTL_SECRET_FORMATS = (
    "yaml",
    "kyaml",
    "json",
    "template",
    "go-template",
    "custom-columns",
)

FILE_READERS = {"cat", "head", "tail", "less", "grep"}
SECRET_FILENAME = re.compile(
    r"^(\.env(\..+)?|.*\.pem|.*\.key|id_rsa|id_ed25519|kubeconfig|talosconfig|"
    r".*\.tfstate(\..+)?|secrets(\.auto)?\.tfvars(\.json)?|secrets\.ya?ml|\.netrc)$"
)

ECHO_LIKE = re.compile(r"^(echo|printf)\b")
VAR_EXPANSION = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# A variable name component: TOKEN, SECRET, PASSWORD or KEY set off by a non letter or
# digit (an underscore, a space, the ends of the string) on both sides, so GH_TOKEN,
# "env | grep TOKEN" and AWS_SECRET_ACCESS_KEY match but MONKEY does not.
CRED_NAME_PART = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:TOKEN|SECRET|PASSWORD|KEY)(?:[^A-Za-z0-9]|$)", re.IGNORECASE
)

ENV_DUMP_PIPE = re.compile(r"\b(?:printenv|env)\b[^\n;&|]*\|\s*(?:[\w./-]+\s+)*grep\b[^\n;&|]*")
PRINTENV_NAME = re.compile(r"^printenv\s+([A-Za-z_][A-Za-z0-9_]*)\b")

DIFF_FILE = re.compile(r"^\+\+\+ b/(.+)$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abp]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}"),
)

NEVER_PRINT = "Never print a secret value, read it from its manager instead."

GITLEAKS_TIMEOUT = 10
GITLEAKS_LEAK_EXIT_CODE = 2
GITLEAKS_SUBCOMMANDS = (("git", "--staged"), ("protect", "--staged"))


def prints_secret(part: str) -> str:
    """The deny reason for a part that prints a secret value, named by its tool."""
    return f"'{part.split()[0]}' prints a secret value to the transcript. {NEVER_PRINT}"


def resolve_command_name(part: str) -> str:
    """part with the leading path stripped off its command name, so
    `/opt/homebrew/bin/tofu output db_password` becomes `tofu output db_password` and a
    pattern anchored on the tool name matches it. Only the first word is touched, every
    argument stays as written.

    The name is read through `_common.command_name`, so a quoted spelling such as
    `"/opt/homebrew/bin/tofu"` resolves the same as the bare one. A wrapper prefix such
    as `sudo` or `time` is not stripped here, unlike in git_guard and commit_message:
    this hook's other checks match on the raw part, `env` and `printenv` among the
    commands they match, so the parts cannot be normalised once for all of them."""
    tokens = _common.shell_words(part)
    if not tokens:
        return part
    return " ".join([_common.command_name(part), *tokens[1:]])


def strip_tofu_global_options(part: str) -> str:
    """Normalises tofu's global options out of a command part that starts with "tofu".

    `tofu -chdir=/srv/infra output db_password` becomes `tofu output db_password`, so a
    global option in front of the subcommand cannot hide it. -chdir, -help and -version
    are the only options tofu accepts there.

    Expects a part whose command name is already resolved to its basename by
    resolve_command_name.
    """
    tokens = part.split()
    if not tokens or tokens[0] != "tofu":
        return part
    index = 1
    while index < len(tokens) and TOFU_GLOBAL_OPTION.match(tokens[index]):
        index += 1
    return " ".join([tokens[0], *tokens[index:]])


def secret_command_violation(part: str) -> Optional[str]:
    """The deny reason when part is a command that prints a secret value.

    The command name is resolved to its basename before the patterns run, so calling
    bao, vault or tofu by an absolute path does not hide the tool they are anchored on.
    """
    normalised = strip_tofu_global_options(resolve_command_name(part))
    for pattern in SECRET_COMMANDS:
        if pattern.match(normalised):
            return prints_secret(normalised)
    return None


def bws_secret_violation(part: str) -> Optional[str]:
    """The deny reason when part reads a secret with bws, whatever flag order it uses.

    bws accepts its global options in front of `secret` and between `secret` and the
    subcommand, so `bws -o env secret get <id>` and `bws secret -o env list` both read
    the secret and both have to be found behind their flags.
    """
    tokens = _common.shell_tokens(part)
    if not tokens or _common.token_name(tokens[0]) != "bws":
        return None
    noun = _common.subcommand_tokens(tokens[1:], BWS_VALUE_FLAGS)
    if not noun or noun[0] != "secret":
        return None
    if _common.subcommand_after(noun[1:], BWS_VALUE_FLAGS) in BWS_SECRET_READS:
        return prints_secret(resolve_command_name(part))
    return None


def bw_get_violation(part: str) -> Optional[str]:
    """The deny reason when part reads an item with bw, whatever flag order it uses.

    bw's global options go in front of the command, so `bw --raw get password app`
    reads the item just as `bw get password app` does.
    """
    tokens = _common.shell_tokens(part)
    if not tokens or _common.token_name(tokens[0]) != "bw":
        return None
    if _common.subcommand_after(tokens[1:], BW_VALUE_FLAGS) == "get":
        return prints_secret(resolve_command_name(part))
    return None


def gh_auth_token_violation(part: str) -> Optional[str]:
    """The deny reason when part prints the gh token, whatever flag order it uses.

    gh looks up the subcommand the way cobra does, skipping the flags in front of the
    noun and the flags between the noun and the subcommand both, so `gh --hostname
    example.com auth token` and `gh auth --hostname example.com token` both reach the
    token command.
    """
    tokens = _common.shell_tokens(part)
    if not tokens or _common.token_name(tokens[0]) != "gh":
        return None
    dispatch = _common.subcommand_tokens(tokens[1:], space_form_takes_value=True)
    if not dispatch or dispatch[0] != "auth":
        return None
    if _common.subcommand_after(dispatch[1:], space_form_takes_value=True) == "token":
        return f"'gh auth token' prints a secret value to the transcript. {NEVER_PRINT}"
    return None


def kubectl_names_secret(resource: str) -> bool:
    """Whether a kubectl resource argument after `get` names a secret.

    kubectl's resource reference grammar is wider than the bare noun: `secret` and
    `secrets` also take a `/<name>` suffix, a `.<version>.<group>` suffix and a place in
    a comma separated list of types, in any combination, so `secret/app`,
    `secret.v1.core/app` and `secret,configmap` all read the same object. Each of them
    prints the decoded value with a structured output, so each has to match.
    """
    for item in resource.split(","):
        kind = item.split("/", 1)[0].split(".", 1)[0]
        if kind in KUBECTL_SECRET_NOUNS:
            return True
    return False


def kubectl_secret_violation(part: str) -> Optional[str]:
    """The deny reason when part reads a Kubernetes secret with a structured output.

    kubectl is cobra based like gh and dispatches the verb behind its global flags, so
    `kubectl -n default get secret app -o yaml` reads the secret just as `kubectl get
    secret app -o yaml` does and the verb has to be found behind those flags. A flag
    between the verb and the resource moves the resource the same way, so
    `kubectl get -o yaml secret app` needs the same walk one level further down. The
    resource itself is matched through kubectl_names_secret, which covers the
    `TYPE/NAME`, `TYPE.VERSION.GROUP` and comma separated spellings as well.

    The output format is read off the tokenised command rather than the raw part, so
    `-o 'yaml'` and `--output="go-template={{.data}}"` are matched like their unquoted
    spellings instead of slipping past a pattern that expects the format name to follow
    the flag directly.

    kubectl's four boolean-only global flags, `--disable-compression`,
    `--insecure-skip-tls-verify`, `--match-server-version` and
    `--warnings-as-errors`, take no value, so the generic flag walk in
    subcommand_tokens lets one of them swallow the verb behind it. Their absence, not
    their presence, is the secure default: they all default to false and none of them
    appears in ordinary use, so the walk fails open on a command nobody writes by
    accident. This hook is defence in depth and does not close that case.
    """
    tokens = _common.shell_tokens(part)
    if not tokens or _common.token_name(tokens[0]) != "kubectl":
        return None
    dispatch = _common.subcommand_tokens(tokens[1:], space_form_takes_value=True)
    if not dispatch or dispatch[0] != "get":
        return None
    resource_args = _common.subcommand_tokens(dispatch[1:], space_form_takes_value=True)
    if not resource_args or not kubectl_names_secret(resource_args[0]):
        return None
    match = KUBECTL_OUTPUT_FORMAT.search(" ".join(tokens))
    if not match:
        return None
    fmt = match.group(2).lower()
    if fmt.startswith(KUBECTL_SECRET_FORMATS):
        return f"kubectl get secret -o {fmt} prints the decoded secret value. {NEVER_PRINT}"
    return None


def secret_file_read_violation(part: str) -> Optional[str]:
    """The deny reason when part reads a file that holds secrets."""
    tokens = _common.shell_tokens(part)
    if not tokens:
        return None

    name = _common.token_name(tokens[0])
    if name not in FILE_READERS:
        return None

    operands = [token for token in tokens[1:] if not token.startswith("-")]
    if name == "grep" and operands:
        operands = operands[1:]

    for operand in operands:
        basename = operand.rsplit("/", 1)[-1]
        if SECRET_FILENAME.match(basename):
            return f"{name} reads {operand}, a file that holds secrets. {NEVER_PRINT}"
    return None


def echoes_credential_var(part: str) -> Optional[str]:
    """The deny reason when part echoes a variable whose name looks like a credential."""
    if not ECHO_LIKE.match(part):
        return None
    for match in VAR_EXPANSION.finditer(part):
        name = match.group(1)
        if CRED_NAME_PART.search(name):
            return f"This echoes ${{{name}}}, a credential looking variable. {NEVER_PRINT}"
    return None


def env_dump_violation(command: str) -> Optional[str]:
    """The deny reason when the raw command pipes env or printenv into a credential grep."""
    match = ENV_DUMP_PIPE.search(command)
    if match and CRED_NAME_PART.search(match.group(0)):
        return f"This greps the environment for a credential pattern. {NEVER_PRINT}"
    return None


def printenv_violation(part: str) -> Optional[str]:
    """The deny reason when part prints one named, credential looking environment
    variable with printenv."""
    match = PRINTENV_NAME.match(part)
    if not match:
        return None
    name = match.group(1)
    if CRED_NAME_PART.search(name):
        return f"printenv {name} prints a credential looking variable. {NEVER_PRINT}"
    return None


def scan_diff(diff: str) -> Optional[str]:
    """The deny reason for the first added line in diff that looks like a credential."""
    path = ""
    line_no: Optional[int] = None

    for raw_line in diff.splitlines():
        file_match = DIFF_FILE.match(raw_line)
        if file_match:
            path = file_match.group(1)
            line_no = None
            continue

        hunk_match = HUNK_HEADER.match(raw_line)
        if hunk_match:
            line_no = int(hunk_match.group(1))
            continue

        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue

        if raw_line.startswith("+"):
            content = raw_line[1:]
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(content):
                    return (
                        f"{path}:{line_no} looks like a committed credential. Remove it "
                        "and rotate the value before committing."
                    )
            if line_no is not None:
                line_no += 1
        elif not raw_line.startswith("-") and line_no is not None:
            line_no += 1

    return None


def run_gitleaks(
    executable: str, cwd: Optional[str], report_path: str
) -> Optional["subprocess.CompletedProcess[str]"]:
    """Runs gitleaks against the staged diff, trying `git --staged` first and falling
    back to `protect --staged` when the installed version does not know that flag.
    Returns the completed process, or None when gitleaks could not be run at all."""
    result = None
    for subcommand in GITLEAKS_SUBCOMMANDS:
        try:
            result = subprocess.run(
                [
                    executable,
                    *subcommand,
                    "--no-banner",
                    "--redact",
                    "--exit-code",
                    str(GITLEAKS_LEAK_EXIT_CODE),
                    "--report-format",
                    "json",
                    "--report-path",
                    report_path,
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=GITLEAKS_TIMEOUT,
            )
        except Exception:
            return None
        if result.returncode in (0, GITLEAKS_LEAK_EXIT_CODE):
            return result
        if "unknown flag" in result.stderr.lower() or "unknown command" in result.stderr.lower():
            continue
        return result
    return result


def gitleaks_reason(report_path: str) -> str:
    """The deny reason built from a gitleaks JSON report, without the secret value."""
    fallback = (
        "gitleaks found a credential in the staged changes. Remove it and rotate the "
        "value before committing."
    )
    try:
        with open(report_path, encoding="utf-8") as handle:
            findings = json.load(handle)
    except Exception:
        return fallback
    if not findings:
        return fallback
    finding = findings[0]
    path = finding.get("File", "")
    line = finding.get("StartLine", "")
    return (
        f"{path}:{line} looks like a committed credential (gitleaks, {finding.get('RuleID', '')}). "
        "Remove it and rotate the value before committing."
    )


def gitleaks_violation(cwd: Optional[str]) -> tuple[Optional[str], bool]:
    """Scans the staged diff with gitleaks when it is on PATH.

    Returns (reason, handled). handled is True when gitleaks ran to a clean result, so
    the caller should trust it instead of falling back to the regex scan.
    """
    executable = shutil.which("gitleaks")
    if not executable:
        return None, False

    report_dir = tempfile.mkdtemp(prefix="secret-guard-")
    report_path = os.path.join(report_dir, "report.json")
    try:
        result = run_gitleaks(executable, cwd, report_path)
        if result is None:
            return None, False
        if result.returncode == GITLEAKS_LEAK_EXIT_CODE:
            return gitleaks_reason(report_path), True
        if result.returncode == 0:
            return None, True
        return None, False
    finally:
        shutil.rmtree(report_dir, ignore_errors=True)


def commit_violation(cwd: Optional[str]) -> Optional[str]:
    """The deny reason for the currently staged changes, or None when git is unavailable
    or they hold nothing that must not be committed."""
    if _common.repo_root(cwd) is None:
        return None

    names = _common.run_git(["diff", "--cached", "--name-only"], cwd) or ""
    for path in names.splitlines():
        path = path.strip()
        if path and SECRET_FILENAME.match(os.path.basename(path)):
            return f"{path} is staged and matches a file pattern that never belongs in git."

    reason, handled = gitleaks_violation(cwd)
    if handled:
        return reason

    diff = _common.run_git(["diff", "--cached"], cwd) or ""
    return scan_diff(diff)


def part_violation(part: str) -> Optional[str]:
    """The deny reason for a single command part, combining the non-commit checks."""
    return (
        _common.malformed_quoting_violation(part)
        or secret_command_violation(part)
        or bws_secret_violation(part)
        or bw_get_violation(part)
        or gh_auth_token_violation(part)
        or kubectl_secret_violation(part)
        or secret_file_read_violation(part)
        or echoes_credential_var(part)
        or printenv_violation(part)
    )


def main() -> int:
    payload = _common.read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return _common.emit_empty()

    reason = env_dump_violation(command)
    if reason:
        return _common.deny(EVENT, reason)

    parts: list[str] = [_common.strip_env_prefix(part) for part in _common.command_parts(command)]

    for part in parts:
        reason = part_violation(part)
        if reason:
            return _common.deny(EVENT, reason)

    commit_git_path: Optional[str] = None
    is_commit = False
    for part in parts:
        normalized, git_path = _common.strip_global_git_options(part)
        if normalized.startswith("git commit"):
            is_commit = True
            commit_git_path = git_path
            break

    if is_commit:
        cwd = commit_git_path or payload.get("cwd") or os.getcwd()
        reason = commit_violation(cwd)
        if reason:
            return _common.deny(EVENT, reason)

    return _common.emit_empty()


if __name__ == "__main__":
    sys.exit(_common.run_main(main))
