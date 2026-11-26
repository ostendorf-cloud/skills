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

`task install` copies the skills into `~/.claude/skills` and the hooks into
`~/.claude/.agent-skills-hooks` together with `rules/main-session.md`, copies `agents/*.md` into
`~/.claude/agents` without touching other files there, writes `rules/baseline.md` as
`~/.claude/CLAUDE.md`, appends the main session rules to the exported `AGENTS.md`, merges
`settings/claude.json` into `~/.claude/settings.json` with the hooks pointing at the installed
copies, and keeps a backup of every file it replaces. The installation keeps working once this
checkout moves, is removed, or sits on another branch; `task install` picks up a change made
here only on the next run. Personal values go into `~/.config/agent-skills/local.json`, see
`settings/local.example.json`. `--link` symlinks the skills into this checkout instead, for a
live view while editing them.

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

## Model defaults

- The laptop profile sets `model` to `opusplan`: Opus in plan mode, Sonnet otherwise.
- `effortLevel` is `medium`.
- `CLAUDE_CODE_SUBAGENT_MODEL` is `sonnet`. A model passed to a single subagent still wins.
- Agent definitions carry their own model: `implementer`, `researcher` and `reviewer` run on Sonnet,
  `reviewer-boundary` on Opus. The path list in `work-review` picks the reviewer.
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW` is `200000`: a session compacts at 200k tokens instead of
  growing into the large window. Every request reads the whole conversation again.
- Raise the model for one session with `/model`, the effort with `/effort`.
- The CI profile sets no model or effort and keeps the workflow's own choice.
- No `language` is set: answers follow the user's language, repository content stays English.

## Use

- Work as usual. The skill reminder names the skill that fits the request.
- `/plan`, `/implement`, `/work-review` and `/work-queue` drive the issue loop.
- `task status` shows drift between the checkout and the installation. `task doctor` checks
  tools, links and hooks.

## Hooks

| Hook | Decision | What it does |
| --- | --- | --- |
| `git-guard` | deny | Push to the default branch, unless the remote has no branch yet, force push without lease or onto the default branch, `git push --all` or `--mirror`, bypassed hooks or signing, deletion of the default branch. On macOS also `git fetch`, `git pull` or `git push` that does not stand alone in its call. |
| `secret-guard` | deny | Commands that print a secret, and a commit whose staged diff holds a credential pattern or a file that never belongs in git. |
| `shell-hygiene` | deny | File content written through the shell: heredoc or redirect into a file, `tee`, `sed -i`. Inline interpreter one liners that span lines or that open a file for writing. |
| `commit-message` | deny | Commit subject that is not a Conventional Commit, or a commit message carrying an attribution trailer, a "Generated with" line or a vendor link outside the documentation hosts. |
| `tracker-body` | deny | A `gh` pull request, issue, review or API body carrying the same attribution patterns, from `--body`, a body file or piped stdin. |
| `public-findings` | deny | A `gh` issue, pull request or API write, or a commit or tag message, in a public repository whose title, label or text describes a finding. Unknown visibility counts as public. A repository without any remote is not public. `publicFindings.allowWords` in `.agent-skills.json` opts out of words. |
| `prefer-opentofu` | deny | `terraform` in a repository that is not marked as Terraform based in `.agent-skills.json`. |
| `iac-first` | deny | Repository, organisation, label, ruleset or secret changes through `gh` or the API, a pull request write through the API or a GraphQL mutation, `gh release` where the release tool (release-me or release-please) is configured, and `gh repo` rename, set-default, alias or extension. |
| `gh-alone` | deny | On macOS, a Bash command that runs `gh` and is not exactly one `gh` call: behind `cd`, in a chain, with a pipe, in a loop, in a command substitution, behind the `env` command or with a redirection other than `2>&1`. A leading `NAME=value` assignment is allowed. The sandbox fails such a call. |
| `scratchpad-path` | deny | A scratchpad path with a dash instead of a slash before the session id, in a Bash command or a file path. The denial shows the corrected path. |
| `label-move` | context | `gh issue edit` or `gh pr edit` that adds an `ai:` label without removing another: reminds that exactly one `ai:` state label must remain. |
| `session-lock` | context | Records the session for the checkout and warns when another live session already works in it. |
| `session-unlock` | context | Removes the session record at session end. |
| `stale-skills` | context | Warns once when the installed skills are behind the checkout they were installed from, or when that checkout is on its default branch and behind origin as last fetched. |
| `main-session-rules` | context | Adds the rules for the session that talks to the user, from the installed `main-session.md`, on every session start, resume, clear and compact. Nothing for a subagent. |
| `ledger-context` | context | Adds the ledger of the current workstream, `.ledger/<stream>.md`, on every session start, resume, clear and compact. The directory comes from `AGENT_SKILLS_LEDGER_DIR` or the nearest `.ledger` above every repository on the way up from the working directory. The stream comes from `AGENT_SKILLS_STREAM` or the first line of `.ledger/current`. A file that links outside the ledger directory is ignored. Adds nothing when there is no ledger. Nothing for a subagent. |
| `context-size` | context | Warns once per 50000 token band when the context reaches 150000 tokens, or the value of `AGENT_SKILLS_CONTEXT_WARN` (`0` disables), and asks for a handoff, then to continue from it. `/clear` is never the only way on. Nothing for a subagent. |
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
task lint:renovate  # Renovate config, extends resolved, no credentials
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
