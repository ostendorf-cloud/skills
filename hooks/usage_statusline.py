#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Status line that also records the plan limit and the context fill as metrics.

Not a hook. It lives next to the hook scripts so the installer copies it to
`~/.claude/.agent-skills-hooks/`. Claude Code runs it as the `statusLine` command and
feeds the status line JSON on stdin. It always prints one status line and exits 0.

The plan limit is not part of the built in OpenTelemetry export, so this script sends
three gauges over OTLP/HTTP JSON to the configured endpoint:

- claude_code.plan_limit.used_percentage with attribute `window` (five_hour, seven_day)
- claude_code.context.used_percentage

Every sample carries session.id, model and vcs.repository.name. The endpoint, the
headers and the resource attributes come from the standard OTEL_EXPORTER_OTLP_* and
OTEL_RESOURCE_ATTRIBUTES variables, which the local overlay sets. Nothing is sent
without an endpoint. Claude Code cancels a status line run that takes too long, so the
send runs in a detached child and at most once per interval per session.
"""

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

SEND_INTERVAL_SECONDS = 60
SEND_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 2
FOREGROUND_ENV = "USAGE_STATUSLINE_FOREGROUND"
STATE_DIR_ENV = "USAGE_STATUSLINE_STATE_DIR"
WINDOWS = (("five_hour", "5h"), ("seven_day", "7d"))


def number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def dig(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def status_line(data: dict[str, Any]) -> str:
    parts = []
    model = dig(data, "model", "display_name")
    parts.append(model if isinstance(model, str) and model else "claude")
    context = number(dig(data, "context_window", "used_percentage"))
    if context is not None:
        parts.append(f"ctx {context:.0f}%")
    for window, label in WINDOWS:
        used = number(dig(data, "rate_limits", window, "used_percentage"))
        if used is not None:
            parts.append(f"{label} {used:.0f}%")
    return " | ".join(parts)


def parse_pairs(text: str) -> dict[str, str]:
    """A comma separated k=v list, as OTEL_EXPORTER_OTLP_HEADERS and
    OTEL_RESOURCE_ATTRIBUTES spell it."""
    pairs: dict[str, str] = {}
    for item in text.split(","):
        key, sep, value = item.partition("=")
        if sep and key.strip():
            pairs[key.strip()] = value.strip()
    return pairs


def attributes(values: dict[str, str]) -> list[dict[str, Any]]:
    return [{"key": k, "value": {"stringValue": v}} for k, v in sorted(values.items())]


def metrics_endpoint(env: dict[str, str]) -> str:
    explicit = env.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
    if explicit:
        return explicit
    base = env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    return f"{base}/v1/metrics" if base else ""


def repository_name(cwd: str) -> str:
    """The repository name from the origin remote of cwd, empty when there is none."""
    if not cwd:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    url = result.stdout.strip().rstrip("/")
    name = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def build_payload(
    data: dict[str, Any], env: dict[str, str], repository: str, now_ns: int
) -> Optional[dict[str, Any]]:
    """The OTLP JSON metrics body for one status line input, None without a sample."""
    labels = {"session.id": str(data.get("session_id") or "unknown")}
    model = dig(data, "model", "id")
    labels["model"] = model if isinstance(model, str) and model else "unknown"
    if repository:
        labels["vcs.repository.name"] = repository

    samples: list[tuple[str, float, dict[str, str]]] = []
    context = number(dig(data, "context_window", "used_percentage"))
    if context is not None:
        samples.append(("claude_code.context.used_percentage", context, {}))
    for window, _ in WINDOWS:
        used = number(dig(data, "rate_limits", window, "used_percentage"))
        if used is not None:
            samples.append(("claude_code.plan_limit.used_percentage", used, {"window": window}))
    if not samples:
        return None

    metrics: dict[str, dict[str, Any]] = {}
    for name, value, extra in samples:
        entry = metrics.setdefault(
            name,
            {
                "name": name,
                "unit": "%",
                "gauge": {"dataPoints": []},
            },
        )
        entry["gauge"]["dataPoints"].append(
            {
                "attributes": attributes({**labels, **extra}),
                "timeUnixNano": str(now_ns),
                "asDouble": value,
            }
        )
    resource = {"service.name": "claude-code-statusline"}
    resource.update(parse_pairs(env.get("OTEL_RESOURCE_ATTRIBUTES", "")))
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": attributes(resource)},
                "scopeMetrics": [
                    {
                        "scope": {"name": "agent-skills.usage-statusline"},
                        "metrics": list(metrics.values()),
                    }
                ],
            }
        ]
    }


def post(payload: dict[str, Any], endpoint: str, env: dict[str, str]) -> bool:
    headers = {"Content-Type": "application/json"}
    for name, value in parse_pairs(env.get("OTEL_EXPORTER_OTLP_HEADERS", "")).items():
        headers[name] = urllib.parse.unquote(value)
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (OSError, ValueError, urllib.error.URLError):
        return False


def send(data: dict[str, Any], env: dict[str, str]) -> bool:
    endpoint = metrics_endpoint(env)
    if not endpoint:
        return False
    cwd = dig(data, "workspace", "project_dir") or data.get("cwd") or ""
    payload = build_payload(
        data, env, repository_name(cwd if isinstance(cwd, str) else ""), time.time_ns()
    )
    return payload is not None and post(payload, endpoint, env)


def state_file(env: dict[str, str], session: str) -> Path:
    base = env.get(STATE_DIR_ENV) or str(
        Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        / "agent-skills"
        / "usage-statusline"
    )
    safe = "".join(c for c in session if c.isalnum() or c in "-_") or "unknown"
    return Path(base) / safe


def due(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime >= SEND_INTERVAL_SECONDS
    except FileNotFoundError:
        return True
    except OSError:
        return False


def record(raw: str, data: dict[str, Any], env: dict[str, str]) -> None:
    """Send the gauges when an endpoint is set and the interval has passed."""
    if not metrics_endpoint(env):
        return
    path = state_file(env, str(data.get("session_id") or ""))
    now = time.time()
    if not due(path, now):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except OSError:
        return
    if env.get(FOREGROUND_ENV):
        send(data, env)
        return
    try:
        child = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--send"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if child.stdin is not None:
            child.stdin.write(raw.encode("utf-8"))
            child.stdin.close()
    except OSError:
        return


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        print("claude")
        return 0
    env = dict(os.environ)
    if "--send" in sys.argv[1:]:
        send(data, env)
        return 0
    try:
        print(status_line(data))
    except Exception:  # noqa: BLE001 - a status line must print whatever the input holds
        print("claude")
    # Recording never breaks the status line, whatever goes wrong in it.
    with contextlib.suppress(Exception):
        record(raw, data, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
