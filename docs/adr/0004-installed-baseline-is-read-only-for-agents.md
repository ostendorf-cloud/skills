# 0004 The installed baseline is read only for agents

Status: accepted
Date: 2026-10-20

## Context

- An unattended run that edits `~/.claude/settings.json` can widen its own permissions.
- "Never change the installed baseline" was a rule without a gate.

## Decision

- `settings/claude.json` denies `Edit` and `Write` on `~/.claude/settings.json`,
  `~/.claude/CLAUDE.md` and `~/.config/agent-skills/**`.
- The sandbox does not list `~/.claude` as writable, so shell writes fail as well.
- `task install` is run by the user in a terminal, not by an agent.

## Consequences

- Baseline changes go through this repository and a pull request.
- An agent proposes a change with the propose-rule skill and waits for the install.
