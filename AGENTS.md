# skills

This repository is the baseline: the rules, skills, hooks and settings every session loads. The
baseline already applies here and is not repeated.

## Layout

- `rules/baseline.md`: always-on rules. Installed as `~/.claude/CLAUDE.md` and exported as
  `AGENTS.md` for other agents.
- `rules/main-session.md`: rules for the session that talks to the user. Emitted by the
  `main-session-rules` hook and appended to the exported `AGENTS.md`.
- `agents/<name>.md`: one subagent definition. Installed into `~/.claude/agents`.
- `skills/<category>/<name>/SKILL.md`: one skill. `skills.sh.json` groups them for the skills.sh
  catalogue.
- `hooks/*.py`: one hook per file, standard library only. `hooks/hooks.json` is the manifest the
  installer reads. Tests in `hooks/tests/`.
- `settings/claude.json`: the laptop profile. `settings/claude-ci.json`: the CI profile.
  `settings/local.example.json`: template for the personal overlay at
  `~/.config/agent-skills/local.json`.
- `scripts/install.py`: install, uninstall, status, doctor. `scripts/validate.py`: repository
  checks.
- `agent-skills.schema.json`: schema of the per repository `.agent-skills.json`.
- `docs/adr/`: decisions worth keeping.

## Commands

```sh
task setup           # mise install
task check           # every check, one after another: lint:*, test:*, validate
task --list          # one target per check: lint:*, test:*, validate
task install         # install this checkout for Claude Code
task doctor
```

- One task target per check and one CI job per target. `check` aggregates the small targets and
  holds no command of its own. CI calls the small targets, never `check`.
- Workflows: `checks.yaml` runs every check as its own job, `install.yaml` smoke tests the
  installer, `release.yaml` runs release-me with the release app token, and `renovate.yaml` runs
  self-hosted Renovate for this repository.

## Deviations

- CI calls the small Task targets, with one exception: the `license` job in `checks.yaml` calls
  `ostendorf-cloud/workflows`' `reusable-license.yaml` instead of `task lint:license`. The shared
  workflow pins addlicense itself, so the check cannot drift with this repository's `mise.toml`.
  `task lint:license` stays and runs the same tool, flags and files locally.
- The `renovate-config` job in `checks.yaml` calls `ostendorf-cloud/workflows`'
  `reusable-renovate-config.yaml`, which pins Renovate itself. `task lint:renovate` runs the same
  two commands locally. The `mise.toml` pin and the shared pin move by hand, on the same major
  version.
- `lint:agents-md` is included in `Taskfile.yaml` from `ostendorf-cloud/workflows` by tag and
  checksum, and `task check` runs it. Every `task` call in CI passes `--trusted-hosts github.com`.
  The tag and checksum move by hand together.

## Changing the baseline

- Edit here. Never edit the installed files under `~/.claude`. `task install` overwrites them,
  and the installed settings deny an agent those writes for the directory they are installed in.
  The user runs `task install`.
- Skill and hook edits are live after `task install`, settings need a new session.
- A new skill needs an entry in `skills.sh.json` and a new hook an entry in `hooks/hooks.json`
  plus a test.

## Writing a skill

- Frontmatter: `name`, `description`. Optional: `model`, `context`, `agent`, `allowed-tools`,
  `disallowed-tools`, `argument-hint`.
- `name` equals the directory name. `description` is one double quoted line of at most 300
  characters: what the skill does, then when to use it. A plain scalar with a colon and a space
  inside is not valid YAML, and the harness then lists the skill by its title only.
- No trigger phrases in a description, they cost listing tokens. A new skill needs a trigger in
  `TRIGGERS` of the skill reminder hook and phrases in `PHRASES` in its test.
- Body at most 120 lines. Sections in this order: title, one line purpose, `## When to use`,
  `## Steps` or `## Rules`, `## Guardrails`, `## Config` when the skill reads
  `.agent-skills.json`, `## References` when needed.
- Short full sentences. One instruction per line. No prose paragraphs, no examples longer than a
  few lines.
- Generic within the conventions: no person, account, organisation, host or repository name. Say
  "the skills repository", "the infrastructure repository", "the shared scripts repository". The
  git remote and the config supply names at run time.
- No product name where more than one tool fits. Describe the shape: "the secret manager", "the
  object store", "the tracker". A tool specific rule belongs in a tool skill named after the tool.
- A skill reads `.agent-skills.json` with `jq` through the snippet in the README of the skills
  directory. `skills/README.md` is its repository path, `task install` copies it to
  `~/.claude/skills/README.md`, and a skill cites the installed path. Absent config means
  defaults. A key may be `false` and that is not absent.
- Skills that run unattended set `disallowed-tools: AskUserQuestion` and record questions on the
  issue instead.
- Every label the skill touches comes from the config with the documented default. A missing
  label on the tracker is reported, never created.
- Every command a skill or a README documents is checked against the allow list in
  `settings/claude-ci.json` first. A command built from variables prints the line to run.
- No ASCII art, no emoji, no typographic quotes, no long dashes.
- A rule that narrows or reverses an existing one edits that rule in the same commit. Two
  sections never state opposite instructions.

## Writing a rule

- `rules/baseline.md` loads into every session and every subagent. A rule goes there only when
  a subagent needs it too.
- A rule about talking to the user, delegating or the size of the conversation goes into
  `rules/main-session.md`. It stays under 9000 characters, the harness cuts hook output above
  that.
- A rule only one role needs goes into that role's agent definition.
- A rule a hook can enforce becomes a hook. Every line here is paid for in every request.

## Writing an agent definition

- Frontmatter: `name` equal to the file name, `description` as one double quoted line, `model`,
  `maxTurns`. Optional: `skills`, `tools`, `disallowedTools`, `effort`.
- A reviewer has no `Edit` and no `NotebookEdit`. No agent has `AskUserQuestion` or `Agent`.
- The body holds what this role needs on top of the baseline: scope, rules, report shape. It
  repeats no baseline rule.
- `skills` preloads the whole skill body into every spawn. List only what the role always needs.

## Writing a hook

- Standard library only. Python 3.9 compatible. Exit 0 always, decisions go through the JSON
  protocol on stdout.
- A hook denies, adds context or, on `Stop`, blocks the end of a turn. It asks only when the
  manifest says so.
- A deny names the rule and what to do instead in one or two sentences.
- Unparseable input or an internal error prints `{}` and exits 0. A hook never blocks by
  accident.
- Match on the command text after splitting on `&&`, `||`, `;` and `|`. A deny applies when any
  part matches.
- Tests feed a payload on stdin and assert the decision. Test names state the behaviour:
  `test_denies_push_to_default_branch`. Fixture commands look real. No network, no git
  repository unless the hook needs one, then a temporary one.
- License header at the top of every `.py` and `.sh` file, after the shebang:

```text
# Copyright 2026 Simon Ostendorf
# SPDX-License-Identifier: Apache-2.0
```

## Writing settings

- Strict JSON, no comments. A non obvious entry is explained in the commit and in an ADR when it
  is a decision.
- Paths use `~/`. The file works on every machine.
- `{{claude_dir}}` in a path stands for the directory the installer writes into. It is replaced
  at install time, home relative as `~/...` where it sits under the home directory. A rule that
  protects an installation's own files uses it instead of a literal `~/.claude`.
- A file rule is written as `Edit(path)` or `Read(path)`. `Edit` covers every file editing
  tool. A path rule on `Write`, `NotebookEdit`, `MultiEdit` or `Glob` is never matched and
  `validate` rejects it, in the overlay example too.
- `ask` outranks `allow` and forces a prompt even in auto mode. Keep `ask` to merge, release,
  apply, delete class commands.
- Personal values such as organisation names and extra domains live in the local overlay, never
  here.
