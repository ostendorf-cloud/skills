# 0006 The sandbox env deny is narrowed, not the allow

Status: accepted
Date: 2026-11-13

## Context

- `sandbox.filesystem.allowRead`/`allowWrite` enumerated `~/Code/.../.env.example` and three
  sibling basenames at every depth, trying to carve the four template names out of `denyRead`'s
  `**/.env.*`.
- Three spellings were probed in a live session, each tried against a repository, which sits
  three segments under `~/Code`, and against a worktree, which sits deeper:
  - Unanchored `**/.env.example`: resolves against the Claude configuration directory, not the
    working directory. Covers nothing under `~/Code`.
  - `~/Code/**/.env.example`: fails past one wildcard segment.
  - `~/Code/*/*/.env.example` and every longer run of `*` segments: also fails past one wildcard
    segment.
- Verified rule: the sandbox matcher honours at most one wildcard segment. No allow pattern,
  however many segments it writes out, can reach a repository three segments down, let alone a
  worktree deeper than that.
- The permission layer already carves the four basenames out cleanly. Verified: reading a
  repository `.env.example` with the Read tool succeeds, and the `Read(!.env.example)` style
  negations in `permissions.deny` leave `.env` denied. `hooks/secret_guard.py` needs no change
  either.

## Decision

- Stop trying to carve an allow out of the deny. Narrow the deny instead.
- In `sandbox.filesystem.denyRead`, replace the broad `**/.env.*` with explicit entries:
  `**/.env.local`, `**/.env.*.local`, `**/.env.development*`, `**/.env.production*`,
  `**/.env.staging*`, `**/.env.test*`. Keep the existing `**/.env` entry.
- The four template basenames, `.env.example`, `.env.sample`, `.env.template` and `.env.dist`,
  are not in that list. They are simply not denied, so no allow entry is needed for them.
- Remove every enumerated `~/Code/.../.env.*` entry from `allowRead` and `allowWrite`, all four
  basenames, all depths. They are dead weight once the deny no longer matches. Keep the plain
  `~/Code` entry in `allowRead` and every unrelated entry in `allowWrite`.
- Leave `permissions.deny` untouched. It already works and sits in a separate layer.

## Consequences

- A `.env.*` name outside this explicit list, for example `.env.ci`, is no longer denied by the
  sandbox. The permission layer's `Read(**/.env.*)` and `hooks/secret_guard.py` still deny it, so
  the sandbox stops being the third layer for that name.
- A new deployment specific name gets added to `denyRead` by hand when one appears, the same way
  the current entries were chosen.
- Reaching the old breadth again, denying every `.env.*` name everywhere again, needs the sandbox
  matcher to support a recursive pattern. It does not today.
