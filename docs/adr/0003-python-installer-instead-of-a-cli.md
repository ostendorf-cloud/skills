# 0003 A Python installer instead of a compiled CLI

Status: accepted
Date: 2026-10-20

## Context

- skills.sh installs skill directories only. Rules, hooks and settings need a second path.
- A compiled CLI needs a release pipeline and a package manager entry before the first install.

## Decision

- `scripts/install.py`, standard library only, run through `task install`.
- Hooks are Python as well, so one runtime serves both.

## Consequences

- `python3` and `jq` are the only requirements beside `git` and `mise`.
- No binary to build, sign or distribute. Updates are `git pull` and `task install`.
