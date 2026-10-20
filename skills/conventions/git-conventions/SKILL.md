---
name: git-conventions
description: Branches, commits, pull requests, rebases, force pushes and worktrees across every
  repository. Use when committing, branching, rebasing, force pushing, opening a pull request,
  reverting history or starting a parallel session. Trigger phrases: branch name, commit message,
  rebase, force push, pull request, revert, worktree, Branch anlegen, Commit schreiben,
  Pull Request erstellen, Force Push, Worktree starten.
---

# Git conventions

How branches, commits, pull requests and history stay consistent and reversible.

## When to use

- Creating a branch, a commit, a tag or a pull request.
- Updating a branch, force pushing, or reverting a published change.
- Starting a parallel session that needs its own checkout.

## Rules

### Branches

- Branch off the default branch. Never commit to it directly.
- Name branches `<type>/<short-subject>` with a Conventional Commits type, for example
  `feat/cache-module`, `fix/backup-retention`, `chore/renovate-preset`.
- One branch solves one thing. A growing scope gets a second branch.
- Delete the branch once its pull request is merged.

### Commits

- Conventional Commits: `type(scope)!: subject`.
- Types: `feat`, `fix`, `chore`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`,
  `revert`. The type drives the release version, so pick it for what it does, not for its size.
- Scope is optional and names the affected area, for example `tofu`, `chart`, `cli`, `ci`.
- Subject in imperative mood, lowercase, no trailing period, at most 72 characters.
- Body explains why. The diff already shows what.
- Breaking changes carry `!` in the header and a `BREAKING CHANGE:` footer with the migration.
- Commits are atomic. Formatting, refactoring and behaviour go into separate commits.
- Reference an issue in the footer with `Refs #123` or `Closes #123`.

### Pull requests

- Title is a single Conventional Commits line. A squash merge takes it as the commit message.
- Body states what changed, why, how it was verified and what the risk is.
- Open as draft while checks run or work continues. Mark ready only once the pipeline is green.
- Squash merge by default. Keep a merge commit only where the individual commits carry value on
  their own.

### History

- Update a branch by rebasing onto the default branch. Never merge the default branch into it.
- A force push is allowed only on a feature branch the current session rebased, and only with
  `--force-with-lease`. Never on the default branch.
- Revert a published mistake with `git revert`. Never reset and force push over published history.
- Fix up an unpushed commit with `git commit --amend` or an interactive rebase, before it is
  pushed, not after.

### Worktrees

- A parallel session on the same repository works from `.worktrees/<branch>`, one branch and one
  checkout per session.
- Remove the worktree and delete the branch once its pull request merges.

## Guardrails

- Never merge the default branch into a feature branch to update it.
- Never force push a branch the current session did not rebase.
- Never leave a merged or abandoned worktree behind.
- Attribution lines for an assistant never go into a commit message or a pull request body.

## Config

- `pr.base`: base branch for a pull request. Default: the repository default branch.
- `pr.draft`: open pull requests as draft. Default: `true`.
- `pr.merge`: merge strategy. Default: `squash`.

## References

- `secrets-handling` for what a commit or a pull request must never carry.
- `commit`, `pr` and `worktree` for the steps that apply these rules.
