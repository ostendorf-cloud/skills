---
name: worktree
description: Creates a git worktree under .worktrees/<branch> for a parallel session, and removes
  it once its branch is merged. Use when starting a session that must not disturb an already
  checked out branch, or cleaning up after one. Trigger phrases: create a worktree, parallel
  session, remove the worktree, Worktree anlegen, Worktree entfernen.
---

# Worktree

One checkout, one session, without disturbing a branch another session already has open.

## When to use

- Starting a session that needs its own checkout alongside an existing one.
- A branch merged and its worktree is no longer needed.
- The worktree list has grown and needs pruning.

## Steps

1. Check `.gitignore` for a `.worktrees/` entry. Add it when missing.
2. Branch off the base from config `pr.base`, else the repository default branch:
   `git worktree add .worktrees/<branch> -b <branch> <base>`.
3. Install dependencies inside the new worktree when a lock file exists there.
4. Run every command for that session from inside `.worktrees/<branch>`, never from the
   original checkout.
5. Once the branch's pull request merges: `git worktree remove .worktrees/<branch>`, then
   `git branch -d <branch>`.
6. List existing worktrees with `git worktree list` and prune one left behind by a merged or
   abandoned branch.

## Guardrails

- One branch, one worktree, one session. Never point two sessions at the same worktree.
- Never remove a worktree whose branch still has unmerged work without checking first.
- `.worktrees/` stays in `.gitignore`. Never commit a worktree's contents from the parent
  checkout.

## Config

- `pr.base`: base branch for the new worktree. Default: the repository default branch.

## References

- `git-conventions` for the branch naming and history rules a worktree's branch still follows.
