# 0004 The installed baseline is read only for agents

Status: accepted
Date: 2026-10-20

## Context

- An unattended run that edits `~/.claude/settings.json` can widen its own permissions.
- "Never change the installed baseline" was a rule without a gate.

## Decision

- `settings/claude.json` denies `Edit` on `{{claude_dir}}/settings.json`,
  `{{claude_dir}}/CLAUDE.md` and `~/.config/agent-skills/**`. The installer replaces
  `{{claude_dir}}` with the directory it installs into, so every target protects its own files
  and not another target's. An `Edit(path)` rule covers every file editing tool. A `Write(path)`
  rule is never consulted.
- The sandbox does not list `~/.claude` as writable, so shell writes fail as well.
- `task install` is run by the user in a terminal, not by an agent.

## Consequences

- Baseline changes go through this repository and a pull request.
- An agent proposes a change with the propose-rule skill and waits for the install.
