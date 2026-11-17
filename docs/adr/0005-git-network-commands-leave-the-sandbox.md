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
- The hook sets `"onFailure": "block"` in `hooks/hooks.json`. It fails closed: a hook that cannot
  start, exits with an unexpected code, times out or prints invalid JSON blocks the call instead
  of letting it through.

## Consequences

- An excluded command sees the real environment and the whole filesystem, including the paths in
  `denyRead` and the credential files the sandbox hides. The hook, not the sandbox, limits it.
- The exclusion applies only when the command stands alone in the call. Measured, these shapes
  stay sandboxed and fail over SSH: a pipe, a chain with `&&` or `;`, `> file`, `< file`,
  `2>/dev/null`, an env assignment or `env` before git, a global option such as `-c`,
  `--no-pager` or `-C` before the subcommand, and a push behind `cd`. A trailing `2>&1` or
  `>&2` and a `time` prefix still leave the sandbox. Run the command alone from the worktree
  directory instead.
- On macOS the `git-guard` hook denies the sandboxed shapes. It does nothing on Linux and in
  CI, where nothing is lost by them.
- Linux is unaffected either way; the exclusion only matters where the proxy cannot carry SSH.
- While the install is broken, for example with no `python3`, `onFailure: block` blocks every Bash
  call, not only git. The setting needs Claude Code 2.1.295 or later.
- The way out is to fix the install, then run `task install`.
- The hook is an early stop against mistakes, not the last line. Branch protection on the
  remote is the backstop, because the hook reads shell text only and does not follow other
  interpreters, sourced files, git aliases or included config files, or commands the shell
  builds at run time.
