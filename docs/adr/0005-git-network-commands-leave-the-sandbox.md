# 0005 Git network commands leave the sandbox

Status: accepted
Date: 2026-10-21

## Context

- On macOS the sandbox proxy cannot tunnel git over SSH. `git fetch`, `git pull` and `git push`
  against an SSH remote fail inside it.
- Every repository here uses an SSH remote. Switching to HTTPS would trade the SSH agent for a
  token on disk and change every checkout on every machine.
- The Claude Code docs name `sandbox.excludedCommands` for exactly these three commands as the
  fix for a kept SSH remote.

## Decision

- `git fetch`, `git pull` and `git push`, bare and with arguments, run outside the sandbox.
- Nothing else of git leaves the sandbox. `git clone` is covered by `gh repo clone`, which is
  already excluded with `gh *`.
- The `git-guard` hook stays the gate on pushes: it runs before the command and independently of
  the sandbox, and keeps denying a push to the default branch and a force push without lease.

## Consequences

- An excluded command sees the real environment and the whole filesystem, including the paths in
  `denyRead` and the credential files the sandbox hides. The hook, not the sandbox, limits it.
- The exclusion applies only when the command stands alone in the call. A pipe, a redirection
  such as `2>&1` or `> file`, a chain with `&&`, `||` or `;`, `git -C <path> push` and a push
  behind `cd` stay sandboxed and still fail over SSH. Run them alone from the worktree
  directory instead. The `git-guard` hook denies these shapes.
- Linux is unaffected either way; the exclusion only matters where the proxy cannot carry SSH.
