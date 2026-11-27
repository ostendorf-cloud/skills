#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""Token use report over the local Claude Code transcripts.

Not a hook. It lives next to the hook scripts so the installer copies it to
`~/.claude/.agent-skills-hooks/`. It reads counters only: the usage record of every
request, its model, timestamp, working directory, session and agent identity, and the
size fields of a compaction. It never prints message text, tool input or tool output.

Transcript layout, as observed and not documented as stable:
`<root>/<project>/<session>.jsonl` for the main session and
`<root>/<project>/<session>/subagents/agent-<id>.jsonl` for each subagent.
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

TOKEN_FIELDS = ("input", "output", "cache_read", "cache_create")
# The prompt cache lives five minutes by default. A longer gap explains a rebuild.
CACHE_TTL_SECONDS = 300


@dataclass
class Request:
    session: str
    agent_id: str
    agent_type: str
    model: str
    timestamp: str
    repository: str
    input: int
    output: int
    cache_read: int
    cache_create: int

    @property
    def kind(self) -> str:
        return "subagent" if self.agent_id else "main"

    @property
    def context(self) -> int:
        return self.input + self.cache_read + self.cache_create


@dataclass
class Compaction:
    session: str
    trigger: str
    pre_tokens: int
    post_tokens: int


def as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def repository_name(cwd: str) -> str:
    """The repository directory name for a working directory, worktrees folded in."""
    if not cwd:
        return "unknown"
    marker = "/.claude/worktrees/"
    if marker in cwd:
        cwd = cwd.split(marker, 1)[0]
    return Path(cwd).name or "unknown"


def agent_type_from_meta(path: Path) -> str:
    meta = path.with_name(path.name[: -len(".jsonl")] + ".meta.json")
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = data.get("agentType") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def read_transcript(
    path: Path, session: str, subagent: bool
) -> tuple[list[Request], list[Compaction]]:
    requests: list[Request] = []
    compactions: list[Compaction] = []
    seen: set[tuple[str, str]] = set()
    meta_type = agent_type_from_meta(path) if subagent else ""
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return requests, compactions
    with handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            session_id = record.get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                session_id = session
            if record.get("subtype") == "compact_boundary":
                meta = record.get("compactMetadata")
                if isinstance(meta, dict):
                    compactions.append(
                        Compaction(
                            session_id,
                            str(meta.get("trigger", "")),
                            as_int(meta.get("preTokens")),
                            as_int(meta.get("postTokens")),
                        )
                    )
                continue
            if record.get("type") != "assistant":
                continue
            message = record.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            # A streamed answer is written more than once. Count each request once.
            key = (str(message.get("id", "")), str(record.get("requestId", "")))
            if key != ("", ""):
                if key in seen:
                    continue
                seen.add(key)
            agent_id = ""
            agent_type = ""
            if subagent or record.get("agentId"):
                agent_id = str(record.get("agentId") or path.stem)
                attribution = record.get("attributionAgent")
                agent_type = (
                    attribution if isinstance(attribution, str) and attribution else meta_type
                ) or "unknown"
            requests.append(
                Request(
                    session=session_id,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    model=str(message.get("model") or "unknown"),
                    timestamp=str(record.get("timestamp") or ""),
                    repository=repository_name(str(record.get("cwd") or "")),
                    input=as_int(usage.get("input_tokens")),
                    output=as_int(usage.get("output_tokens")),
                    cache_read=as_int(usage.get("cache_read_input_tokens")),
                    cache_create=as_int(usage.get("cache_creation_input_tokens")),
                )
            )
    return requests, compactions


def collect(root: Path) -> tuple[list[Request], list[Compaction]]:
    requests: list[Request] = []
    compactions: list[Compaction] = []
    if not root.is_dir():
        return requests, compactions
    for project in sorted(p for p in root.iterdir() if p.is_dir()):
        for main in sorted(project.glob("*.jsonl")):
            found = read_transcript(main, main.stem, subagent=False)
            requests += found[0]
            compactions += found[1]
        for sub in sorted(project.glob("*/subagents/*.jsonl")):
            found = read_transcript(sub, sub.parent.parent.name, subagent=True)
            requests += found[0]
            compactions += found[1]
    return requests, compactions


def parse_time(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_prices(path: Optional[Path]) -> dict[str, dict[str, float]]:
    """Per million token rates by model name substring. Empty without a file."""
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: {field: float(rates.get(field, 0)) for field in TOKEN_FIELDS}
        for name, rates in data.items()
    }


def cost(request: Request, prices: dict[str, dict[str, float]]) -> Optional[float]:
    for name, rates in prices.items():
        if name in request.model:
            return sum(getattr(request, field) * rates[field] for field in TOKEN_FIELDS) / 1e6
    return None


def fmt_tokens(value: float) -> str:
    return f"{int(round(value)):,}"


def table(title: str, header: list[str], rows: Iterable[list[str]]) -> str:
    rows = list(rows)
    lines = [f"## {title}", ""]
    if not rows:
        return "\n".join(lines + ["No data.", ""])
    widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]

    def render(cells: list[str]) -> str:
        padded = []
        for i, cell in enumerate(cells):
            padded.append(cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i]))
        return "| " + " | ".join(padded) + " |"

    lines.append(render(header))
    lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    lines += [render(row) for row in rows]
    return "\n".join(lines + [""])


class Totals:
    def __init__(self) -> None:
        self.count = 0
        self.input = self.output = self.cache_read = self.cache_create = 0
        self.cost = 0.0
        self.priced = False

    def add(self, request: Request, prices: dict[str, dict[str, float]]) -> None:
        self.count += 1
        self.input += request.input
        self.output += request.output
        self.cache_read += request.cache_read
        self.cache_create += request.cache_create
        value = cost(request, prices)
        if value is not None:
            self.cost += value
            self.priced = True

    def cells(self, with_cost: bool) -> list[str]:
        cells = [
            str(self.count),
            fmt_tokens(self.input),
            fmt_tokens(self.output),
            fmt_tokens(self.cache_read),
            fmt_tokens(self.cache_create),
        ]
        if with_cost:
            cells.append(f"{self.cost:,.2f}" if self.priced else "n/a")
        return cells


def grouped(
    requests: list[Request], key: Any, prices: dict[str, dict[str, float]]
) -> dict[Any, Totals]:
    groups: dict[Any, Totals] = defaultdict(Totals)
    for request in requests:
        groups[key(request)].add(request, prices)
    return groups


def usage_table(
    title: str,
    label: list[str],
    groups: dict[Any, Totals],
    prices: dict[str, dict[str, float]],
    limit: int = 0,
) -> str:
    with_cost = bool(prices)
    header = label + ["requests", "input", "output", "cache read", "cache create"]
    if with_cost:
        header.append("cost")
    ordered = sorted(groups.items(), key=lambda item: (-item[1].output, str(item[0])))
    if limit:
        ordered = ordered[:limit]
    rows = []
    for key, totals in ordered:
        names = list(key) if isinstance(key, tuple) else [key]
        rows.append([str(n) for n in names] + totals.cells(with_cost))
    return table(title, header, rows)


def cache_misses(requests: list[Request], threshold: int, limit: int) -> str:
    """Main session requests that rebuilt a large prompt instead of reading the cache."""
    by_session: dict[str, list[Request]] = defaultdict(list)
    for request in requests:
        if request.kind == "main":
            by_session[request.session].append(request)
    rows = []
    for session, items in by_session.items():
        items.sort(key=lambda r: r.timestamp)
        misses = rebuilt = after_ttl = 0
        previous: Optional[datetime] = None
        for request in items:
            now = parse_time(request.timestamp)
            if request.cache_create >= threshold and request.cache_create > request.cache_read:
                misses += 1
                rebuilt += request.cache_create
                if previous and now and (now - previous).total_seconds() > CACHE_TTL_SECONDS:
                    after_ttl += 1
            previous = now or previous
        if misses:
            rows.append([session[:8], str(misses), str(after_ttl), fmt_tokens(rebuilt)])
    rows.sort(key=lambda row: -int(row[3].replace(",", "")))
    return table(
        f"Cache misses (main session, rebuild of at least {threshold:,} tokens)",
        ["session", "misses", "after idle gap", "tokens rebuilt"],
        rows[:limit] if limit else rows,
    )


def agents_by_length(requests: list[Request], limit: int) -> str:
    agents: dict[str, list[Request]] = defaultdict(list)
    for request in requests:
        if request.kind == "subagent":
            agents[request.agent_id].append(request)
    rows = []
    for agent_id, items in agents.items():
        rows.append(
            (
                len(items),
                [
                    agent_id[-8:],
                    items[0].agent_type,
                    items[0].session[:8],
                    str(len(items)),
                    fmt_tokens(sum(r.output for r in items)),
                    fmt_tokens(sum(r.cache_read for r in items)),
                    fmt_tokens(max(r.context for r in items)),
                ],
            )
        )
    rows.sort(key=lambda item: -item[0])
    return table(
        "Agents by length",
        ["agent", "type", "session", "requests", "output", "cache read", "peak context"],
        [row for _, row in rows[:limit]] if limit else [row for _, row in rows],
    )


def prompt_sizes(requests: list[Request], compactions: list[Compaction], limit: int) -> str:
    sizes: dict[str, list[int]] = defaultdict(list)
    for request in sorted(requests, key=lambda r: r.timestamp):
        if request.kind == "main":
            sizes[request.session].append(request.context)
    compacted: dict[str, list[Compaction]] = defaultdict(list)
    for item in compactions:
        compacted[item.session].append(item)
    rows = []
    for session, values in sizes.items():
        events = compacted.get(session, [])
        mean_pre = statistics.mean(c.pre_tokens for c in events) if events else 0
        rows.append(
            (
                max(values),
                [
                    session[:8],
                    str(len(values)),
                    fmt_tokens(statistics.median(values)),
                    fmt_tokens(max(values)),
                    str(len(events)),
                    fmt_tokens(mean_pre) if events else "-",
                ],
            )
        )
    rows.sort(key=lambda item: -item[0])
    return table(
        "Main session prompt size (input plus cache tokens per request)",
        ["session", "requests", "median", "max", "compactions", "mean size at compaction"],
        [row for _, row in rows[:limit]] if limit else [row for _, row in rows],
    )


def report(
    requests: list[Request],
    compactions: list[Compaction],
    prices: dict[str, dict[str, float]],
    top: int,
    miss_threshold: int,
) -> str:
    sections = [
        usage_table(
            "By session",
            ["session", "repository"],
            grouped(requests, lambda r: (r.session[:8], r.repository), prices),
            prices,
            top,
        ),
        usage_table(
            "By kind and model",
            ["kind", "model"],
            grouped(requests, lambda r: (r.kind, r.model), prices),
            prices,
        ),
        usage_table(
            "By agent type",
            ["agent type", "model"],
            grouped(
                [r for r in requests if r.kind == "subagent"],
                lambda r: (r.agent_type, r.model),
                prices,
            ),
            prices,
        ),
        usage_table(
            "By day (UTC)",
            ["day"],
            grouped(requests, lambda r: r.timestamp[:10] or "unknown", prices),
            prices,
        ),
        usage_table(
            "By repository",
            ["repository"],
            grouped(requests, lambda r: r.repository, prices),
            prices,
        ),
        cache_misses(requests, miss_threshold, top),
        agents_by_length(requests, top),
        prompt_sizes(requests, compactions, top),
    ]
    if not prices:
        sections.append(
            "Cost is not shown. Pass --prices FILE with per million token list prices.\n"
        )
    return "\n".join(sections)


def filter_requests(
    requests: list[Request], days: int, now: datetime, session: str, repository: str
) -> list[Request]:
    cutoff = now - timedelta(days=days) if days else None
    kept = []
    for request in requests:
        if session and not request.session.startswith(session):
            continue
        if repository and request.repository != repository:
            continue
        if cutoff is not None:
            stamp = parse_time(request.timestamp)
            if stamp is None or stamp < cutoff:
                continue
        kept.append(request)
    return kept


def default_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "projects"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Token use report over local transcripts.")
    parser.add_argument("--root", type=Path, default=None, help="projects directory")
    parser.add_argument("--days", type=int, default=7, help="look back this many days, 0 for all")
    parser.add_argument("--session", default="", help="session id prefix")
    parser.add_argument("--repository", default="", help="repository directory name")
    parser.add_argument("--prices", type=Path, default=None, help="JSON of per million rates")
    parser.add_argument("--top", type=int, default=15, help="rows per long table, 0 for all")
    parser.add_argument("--miss-threshold", type=int, default=50000)
    args = parser.parse_args(argv)

    requests, compactions = collect(args.root or default_root())
    now = datetime.now(timezone.utc)
    requests = filter_requests(requests, args.days, now, args.session, args.repository)
    if args.session:
        compactions = [c for c in compactions if c.session.startswith(args.session)]
    try:
        prices = load_prices(args.prices)
    except (OSError, ValueError, AttributeError) as exc:
        print(f"usage_report: cannot read prices: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(report(requests, compactions, prices, args.top, args.miss_threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
