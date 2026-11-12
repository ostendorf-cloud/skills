# skills

Rules, skills, hooks and settings for coding agents. Claude Code first, every agent that reads
`AGENTS.md` and skills.sh second.

## What it does

- One always-on rule set, short enough to load on every request.
- Skills for commits, pull requests, reviews, issues, releases, OpenTofu, Kubernetes and more.
  Loaded when needed.
- Hooks that deny what must never happen and remind of what is easy to forget. They do not ask.
  Among them: a commit, pull request or issue carrying an attribution line, a generated-by
  marker or a link to Claude or Anthropic gets denied before it is written.
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

A second, independent installation, for example a work profile at `~/.claude-work`, runs
`python3 scripts/install.py install --claude-dir ~/.claude-work --target work` directly. The
directory is the identity of an installation and the `--target` name namespaces the shared
`state.json`, `local.json` and `AGENTS.md` export. Both flags belong together: a `--target`
without its own `--claude-dir` is not a second installation, and the installer refuses a
directory that already belongs to another target. Each target records its directory, so
`uninstall`, `status` and `doctor` refuse a `--claude-dir` that does not match what was recorded.
Moving a target to another directory means uninstalling it first.

Run `task install` in your own terminal, not from an agent session. The installed settings deny
an agent every write to the installed `settings.json` and `CLAUDE.md` of the directory it runs
from, and to `~/.config/agent-skills`, so an unattended run cannot widen its own permissions.

Skills alone, for any agent that supports skills.sh:

```sh
npx skills add ostendorf-cloud/skills -g
```

## Use

- Work as usual. The skill reminder names the skill that fits the request.
- `/plan`, `/implement`, `/work-review` and `/work-queue` drive the issue loop.
- `task status` shows drift between the checkout and the installation. `task doctor` checks
  tools, links and hooks.

## Hooks

| Hook | Decision | What it does |
| --- | --- | --- |
| `git-guard` | deny | Push to the default branch, force push without lease or onto the default branch, `git push --all` or `--mirror`, bypassed hooks or signing, deletion of the default branch. |
| `secret-guard` | deny | Commands that print a secret, and a commit whose staged diff holds a credential pattern or a file that never belongs in git. |
| `shell-hygiene` | deny | File content written through the shell: heredoc or redirect into a file, `tee`, `sed -i`. Inline interpreter one liners that span lines or that open a file for writing. |
| `commit-message` | deny | Commit subject that is not a Conventional Commit, or a commit message carrying an attribution trailer, a "Generated with" line or a vendor link outside the documentation hosts. |
| `tracker-body` | deny | A `gh` pull request, issue, review or API body carrying the same attribution patterns, from `--body`, a body file or piped stdin. |
| `prefer-opentofu` | deny | `terraform` in a repository that is not marked as Terraform based in `.agent-skills.json`. |
| `iac-first` | deny | Repository, organisation, label, ruleset or secret changes through `gh` or the API, a pull request write through the API or a GraphQL mutation, `gh release` where the release tool (release-me or release-please) is configured, and `gh repo` rename, set-default, alias or extension. |
| `label-move` | context | `gh issue edit` or `gh pr edit` that adds an `ai:` label without removing another: reminds that exactly one `ai:` state label must remain. |
| `session-lock` | context | Records the session for the checkout and warns when another live session already works in it. |
| `session-unlock` | context | Removes the session record at session end. |
| `skill-reminder` | context | Names the skills that cover the request. |
| `file-parses` | context | A YAML, JSON or TOML file that no longer parses after a write. |
| `tofu-fmt` | context | Reports when a written `.tf` or `.tfvars` file is not formatted. |

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

`CONTRIBUTING.md` has the commit, sign-off and license-header rules a change here follows.

Releases come from release-me. Every merge to `main` updates the release pull request,
merging that creates the tag, the release and the changelog. The workflow runs with the token
of the release app: the variable `GH_APP_RELEASE_APP_ID` and the secret
`GH_APP_RELEASE_PRIVATE_KEY`, set on the repository or the organisation as infrastructure code.

## License

Apache-2.0. See `LICENSE`.
