#!/usr/bin/env python3
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
"""SessionStart hook. Adds the ledger of the current workstream as context.

The ledger is one Markdown file per workstream, outside every repository:
<org folder>/.ledger/<stream>.md. See the Ledger section of rules/main-session.md.

The ledger directory comes from AGENT_SKILLS_LEDGER_DIR when set. Otherwise the hook
walks up from the session's cwd and takes the nearest `.ledger` directory above the
outermost directory that holds a `.git` file or directory. A `.ledger` inside a repository
is repository content and is ignored. Files that resolve outside the ledger directory,
for example through a symlink, are ignored too. It never guesses a path that does not exist.

The stream comes from AGENT_SKILLS_STREAM when set. Otherwise it is the first line of
the file `<ledger dir>/current`. A stream name holds letters, digits, dot, dash and
underscore only and does not start with a dot, so it can never leave the ledger directory.

The content is emitted for every SessionStart source: startup, resume, clear and compact.
It is cut at MAX_CHARS, the harness cuts additional context at 10000 characters.

Warnings come first, so the cut never hides them. The hook only reads the file, it never
runs gh. It warns when:
- the `## Inventory` section has no line `Inventory read: YYYY-MM-DD`, with an optional
  ` HH:MM` after the date. Date and time are UTC.
- that date is older than 24 hours. A date without a time is fresh on the same UTC day only.
- the ledger is larger than MAX_CHARS.

With no ledger, no stream or an empty file the hook prints `{}` and exits 0. So does a
payload with a non empty agent_id, which marks a subagent, and any unexpected error.
"""

import datetime
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common  # noqa: E402

EVENT_START = "SessionStart"
ENV_DIR = "AGENT_SKILLS_LEDGER_DIR"
ENV_STREAM = "AGENT_SKILLS_STREAM"
LEDGER_DIRNAME = ".ledger"
CURRENT_NAME = "current"
STREAM_NAME = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
MAX_CHARS = 8000
HEADER = "Ledger of the current workstream, file {path}. The issue and gh state win over it.\n\n"
CUT_NOTE = "\n\n[ledger cut, read the file for the rest]"
MAX_AGE = datetime.timedelta(hours=24)
INVENTORY_HEADING = re.compile(r"^## Inventory\b.*$", re.MULTILINE)
NEXT_HEADING = re.compile(r"^## ", re.MULTILINE)
INVENTORY_READ = re.compile(
    r"^Inventory read: (\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?[ \t]*$", re.MULTILINE
)
WARN_MISSING = (
    "the ledger has no `Inventory read: YYYY-MM-DD` line in its `## Inventory` section. "
    "Read all open issues and pull requests of the organisation before the next status table."
)
WARN_STALE = (
    "the inventory was read on {stamp} UTC, more than 24 hours ago. "
    "Read all open issues and pull requests of the organisation again."
)
WARN_SIZE = (
    "the ledger has {size} characters, over the limit of {limit}. The end is cut. "
    "Prune it: one current row per item, drop merged and closed items."
)


def ledger_dir(cwd: str) -> Optional[str]:
    """The ledger directory: the environment variable, else the nearest `.ledger` that sits
    above every repository on the way up from cwd.

    The ledger lives outside every repository, so a `.ledger` inside one is repository
    content and is never read. A worktree can sit inside its main checkout, so the search
    only starts above the outermost directory that holds a `.git` file or directory.
    """
    configured = os.environ.get(ENV_DIR, "").strip()
    if configured:
        return configured if os.path.isdir(configured) else None
    chain = []
    current = os.path.realpath(cwd)
    while True:
        chain.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    outermost = -1
    for index, directory in enumerate(chain):
        if os.path.lexists(os.path.join(directory, ".git")):
            outermost = index
    for directory in chain[outermost + 1 :]:
        candidate = os.path.join(directory, LEDGER_DIRNAME)
        if os.path.isdir(candidate):
            return candidate
    return None


def inside(directory: str, path: str) -> bool:
    """True when path resolves to a file inside directory, links followed."""
    base = os.path.realpath(directory)
    return os.path.commonpath([base, os.path.realpath(path)]) == base


def read_inside(directory: str, path: str) -> Optional[str]:
    """The stripped text of a file that resolves inside directory, else None."""
    try:
        if not inside(directory, path):
            return None
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return text.strip() or None


def stream_name(directory: str) -> Optional[str]:
    """The current stream: the environment variable, else the first line of `current`."""
    name = os.environ.get(ENV_STREAM, "").strip()
    if not name:
        text = read_inside(directory, os.path.join(directory, CURRENT_NAME))
        name = text.splitlines()[0].strip() if text else ""
    return name if STREAM_NAME.fullmatch(name) else None


def inventory_section(text: str) -> Optional[str]:
    """The body of the `## Inventory` section, up to the next `## ` heading, else None."""
    match = INVENTORY_HEADING.search(text)
    if not match:
        return None
    rest = text[match.end() :]
    following = NEXT_HEADING.search(rest)
    return rest[: following.start()] if following else rest


def inventory_warning(text: str, now: datetime.datetime) -> Optional[str]:
    """A warning when the inventory date is missing or older than 24 hours, else None.

    A date without a time is fresh only on the same UTC day, so it is never older than 24 hours.
    A date in the future counts as stale.
    """
    section = inventory_section(text)
    match = INVENTORY_READ.search(section) if section is not None else None
    if not match:
        return WARN_MISSING
    try:
        day = datetime.date.fromisoformat(match.group(1))
        clock = datetime.time.fromisoformat(match.group(2)) if match.group(2) else None
    except ValueError:
        return WARN_MISSING
    if clock is None:
        fresh = day == now.date()
    else:
        read = datetime.datetime.combine(day, clock, datetime.timezone.utc)
        fresh = datetime.timedelta(0) <= now - read <= MAX_AGE
    stamp = match.group(1) + (" " + match.group(2) if match.group(2) else "")
    return None if fresh else WARN_STALE.format(stamp=stamp)


def warnings(text: str, now: datetime.datetime) -> str:
    """The warning block for a ledger text, empty when there is nothing to warn about."""
    found = []
    inventory = inventory_warning(text, now)
    if inventory:
        found.append(inventory)
    if len(text) > MAX_CHARS:
        found.append(WARN_SIZE.format(size=len(text), limit=MAX_CHARS))
    return "".join(f"WARNING: {line}\n" for line in found) + ("\n" if found else "")


def build(cwd: str, now: Optional[datetime.datetime] = None) -> Optional[str]:
    directory = ledger_dir(cwd)
    if not directory:
        return None
    stream = stream_name(directory)
    if not stream:
        return None
    path = os.path.join(directory, f"{stream}.md")
    text = read_inside(directory, path)
    if not text:
        return None
    notice = warnings(text, now or datetime.datetime.now(datetime.timezone.utc))
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + CUT_NOTE
    return HEADER.format(path=path) + notice + text


def main() -> int:
    payload = _common.read_payload()
    if payload.get("hook_event_name") != EVENT_START or payload.get("agent_id"):
        return _common.emit_empty()
    message = build(payload.get("cwd") or os.getcwd())
    if not message:
        return _common.emit_empty()
    return _common.context(EVENT_START, message)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(_common.emit_empty())
