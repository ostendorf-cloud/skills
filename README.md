# skills

Rules, skills, hooks and settings for coding agents. Claude Code first, every agent that reads
`AGENTS.md` and skills.sh second.

## What it does

- One always-on rule set, short enough to load on every request.
- Skills for commits, pull requests, reviews, issues, releases, OpenTofu, Kubernetes and more.
  Loaded when needed.
- Hooks that deny what must never happen and remind of what is easy to forget. They do not ask.
- A settings profile that lets an agent work unattended: auto mode, sandbox, masked credentials,
  a short ask list.
- A label driven work loop: an issue marked `ai: ready` gets implemented, pushed, reviewed and
  handed back, without a human in between.

## Install

Requirements: `git`, `python3`, `jq`, `mise`.

```sh
git clone https://github.com/ostendorf-cloud/skills.git
cd skills
task setup
task install
```

`task install` links the skills into `~/.claude/skills`, writes `rules/baseline.md` as
`~/.claude/CLAUDE.md`, merges `settings/claude.json` and the hooks into `~/.claude/settings.json`,
and keeps a backup of every file it replaces. Personal values go into
`~/.config/agent-skills/local.json`, see `settings/local.example.json`.

Run `task install` in your own terminal, not from an agent session. The installed settings deny
an agent every write to `~/.claude/settings.json`, `~/.claude/CLAUDE.md` and
`~/.config/agent-skills`, so an unattended run cannot widen its own permissions.

Skills alone, for any agent that supports skills.sh:

```sh
npx skills add ostendorf-cloud/skills -g
```

## Use

- Work as usual. The skill reminder names the skill that fits the request.
- `/plan`, `/implement`, `/work-review` and `/work-queue` drive the issue loop.
- `task status` shows drift between the checkout and the installation. `task doctor` checks
  tools, links and hooks.

## Per repository

An optional `.agent-skills.json` at the repository root sets verify command, labels, models and
branch strategy. Schema: `agent-skills.schema.json`. Absent means defaults.

## Workflow

1. Plan in the issue, with the expensive model.
2. Implement with the cheaper model in a worktree, push, open a draft pull request, move the label
   to `ai: review requested`.
3. Review with a fresh agent as a GitHub review. Approve moves the label to `ai: done`, request
   changes sends it back to `ai: working`.
4. A human merges.

## Development

```sh
task --list
task check          # every check, one after another
task lint:ruff      # one target per check
task test:hooks
task validate
```

One target per check, one CI job per target. `check` only calls the small targets.

## License

Apache-2.0. See `LICENSE`.
