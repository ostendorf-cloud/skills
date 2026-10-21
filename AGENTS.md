# skills

This repository is the baseline: the rules, skills, hooks and settings every session loads. The
baseline already applies here and is not repeated.

## Layout

- `rules/baseline.md`: always-on rules. Installed as `~/.claude/CLAUDE.md` and exported as
  `AGENTS.md` for other agents.
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
task --list          # one target per check: lint:*, test:*, validate
task install         # install this checkout for Claude Code
task doctor
```

- One task target per check and one CI job per target. No umbrella target.
- Workflows: `checks.yaml` runs every check as its own job, `install.yaml` smoke tests the installer.

## Changing the baseline

- Edit here. Never edit the installed files under `~/.claude`. `task install` overwrites them,
  and the installed settings deny an agent those writes. The user runs `task install`.
- Skill and hook edits are live after `task install`, settings need a new session.
- A new skill needs an entry in `skills.sh.json` and a new hook an entry in `hooks/hooks.json`
  plus a test.

## Writing a skill

- Frontmatter: `name`, `description`. Optional: `model`, `context`, `allowed-tools`,
  `disallowed-tools`, `argument-hint`.
- `name` equals the directory name. `description` says what the skill does and ends with when to
  use it, with trigger phrases.
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
- A skill reads `.agent-skills.json` with `jq` through the snippet in `skills/README.md`. Absent
  config means defaults. A key may be `false` and that is not absent.
- Skills that run unattended set `disallowed-tools: AskUserQuestion` and record questions on the
  issue instead.
- Every label the skill touches comes from the config with the documented default. A missing
  label on the tracker is reported, never created.
- No ASCII art, no emoji, no typographic quotes, no long dashes.

## Writing a hook

- Standard library only. Python 3.9 compatible. Exit 0 always, decisions go through the JSON
  protocol on stdout.
- A hook denies or adds context. It asks only when the manifest says so.
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
- `ask` outranks `allow` and forces a prompt even in auto mode. Keep `ask` to merge, release,
  apply, delete class commands.
- Personal values such as organisation names and extra domains live in the local overlay, never
  here.
