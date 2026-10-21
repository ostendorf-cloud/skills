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

- Title is a single Conventional Commits line that frames the pull request for a reviewer.
- Body states what changed, why, how it was verified and what the risk is.
- Open as draft while checks run or work continues. Mark ready only once the pipeline is green.
- Rebase the branch onto the default branch right before the merge, so the merge commit carries
  no drift and the diff a reviewer last saw is the diff that lands.
- Merge commit by default. No squash: every atomic commit survives, `git revert <sha>` reverts
  one step alone, `git revert -m 1 <merge>` reverts the whole pull request, `git log
  --first-parent` reads as the pull request history. Rebase merge only where a repository opts
  in through config `pr.merge` and its repository settings allow it.

### History

- Update a branch by rebasing onto the default branch. Never merge the default branch into it.
- A force push is allowed only on a feature branch the current session rebased, and only with
  `--force-with-lease`. Never on the default branch.
- Revert a mistake on the default branch with `git revert`. Never reset and force push over the
  default branch or a merged branch.
- Fix up a commit on the own branch with `git commit --amend` or an interactive rebase before the
  merge, under the rules in Review fixes.

### Review fixes

- A review fix on an already pushed commit lands in the commit it corrects when that commit is
  unambiguous: `git commit --fixup <sha>`, then `git rebase --autosquash <base>` to fold it in,
  then push with `--force-with-lease`.
- Only on the own branch, and only before the merge. Never once the pull request has merged.
- The target commit is not clear, or the fix changes something of its own: a new commit instead.
- Never fold a fix into the last commit or an arbitrary one. The target is the commit it
  corrects, found deliberately.

### Worktrees

- A parallel session on the same repository works from `.worktrees/<branch>`, one branch and one
  checkout per session.
- Remove the worktree and delete the branch once its pull request merges.

## Guardrails

- Never merge the default branch into a feature branch to update it.
- Never force push a branch the current session did not rebase.
- Never leave a merged or abandoned worktree behind.
- Attribution lines for an assistant never go into a commit message or a pull request body.
- Never fold a review fix into the last commit or an arbitrary one, and never once the pull
  request has merged.

## Config

- `pr.base`: base branch for a pull request. Default: the repository default branch.
- `pr.draft`: open pull requests as draft. Default: `true`.
- `pr.merge`: merge strategy. Default: `merge`.

## References

- `secrets-handling` for what a commit or a pull request must never carry.
- `commit`, `pr` and `worktree` for the steps that apply these rules.
