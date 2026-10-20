#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""PreToolUse hook on Bash. Denies a command that prints a secret to the transcript, and
a `git commit` whose staged diff holds a credential pattern or a file that never belongs
in git. The commit check runs gitleaks when it is on PATH and falls back to a regex scan
otherwise. Never prints the matched value, only the file and line number.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT = "PreToolUse"

SECRET_COMMANDS = (
    re.compile(r"^bao\s+kv\s+get\b"),
    re.compile(r"^bao\s+read\b"),
    re.compile(r"^vault\s+kv\s+get\b"),
    re.compile(r"^vault\s+read\b"),
    re.compile(r"^bws\s+secret\s+(get|list)\b"),
    re.compile(r"^bw\s+get\b"),
    re.compile(r"^gh\s+auth\s+token\b"),
    re.compile(r"^tofu\s+output\b"),
    re.compile(r"^tofu\s+state\s+(show|pull)\b"),
)

KUBECTL_GET_SECRET = re.compile(r"^kubectl\s+get\s+secrets?\b")
KUBECTL_OUTPUT_FORMAT = re.compile(r"(-o|--output)[\s=]+([A-Za-z-]+)")

FILE_READERS = {"cat", "head", "tail", "less", "grep"}
SECRET_FILENAME = re.compile(
    r"^(\.env(\..+)?|.*\.pem|.*\.key|id_rsa|id_ed25519|kubeconfig|talosconfig|"
    r".*\.tfstate(\..+)?|.*\.tfvars|secrets\.ya?ml|\.netrc)$"
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


def secret_command_violation(part: str) -> Optional[str]:
    """The deny reason when part is a command that prints a secret value."""
    for pattern in SECRET_COMMANDS:
        if pattern.match(part):
            return f"'{part.split()[0]}' prints a secret value to the transcript. {NEVER_PRINT}"
    return None


def kubectl_secret_violation(part: str) -> Optional[str]:
    """The deny reason when part reads a Kubernetes secret with a structured output."""
    if not KUBECTL_GET_SECRET.match(part):
        return None
    match = KUBECTL_OUTPUT_FORMAT.search(part)
    if not match:
        return None
    fmt = match.group(2).lower()
    if fmt.startswith("yaml") or fmt.startswith("json"):
        return f"kubectl get secret -o {fmt} prints the decoded secret value. {NEVER_PRINT}"
    return None


def secret_file_read_violation(part: str) -> Optional[str]:
    """The deny reason when part reads a file that holds secrets."""
    try:
        tokens = shlex.split(part)
    except ValueError:
        return None
    if not tokens:
        return None

    name = tokens[0].rsplit("/", 1)[-1]
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
        secret_command_violation(part)
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
