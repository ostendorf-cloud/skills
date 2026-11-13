# 0006 The sandbox env template carve-out is machine wide

Status: accepted
Date: 2026-11-13

## Context

- The sandbox carve-out for the four env template basenames carried the anchored spelling
  `~/Code/**/.env.example` (and the three siblings) in `sandbox.filesystem.allowRead` and
  `allowWrite`.
- Probed in a session with the current settings installed and active:

  ```text
  touch ~/Code/github.com/.env.example                   ok
  touch ~/Code/github.com/<org>/.env.example              Operation not permitted
  touch ~/Code/github.com/<org>/<repo>/.env.example       Operation not permitted
  ```

- The sandbox matcher reads `~/Code/**/.env.example` as exactly one path segment between
  `~/Code` and the basename. Every repository sits three or four segments under `~/Code`, so
  the anchored entry never reached one.
- The unanchored spelling `**/.env.example` already sits in the same lists and in the
  `permissions.deny` negations. It matches at any depth and is the one that actually works.

## Decision

- Drop the four anchored `~/Code/**/.env.*` entries from `allowRead` and `allowWrite`. They are
  dead past one path segment and keeping them next to the unanchored spelling is a duplicate,
  not a narrower rule.
- Keep one spelling per basename: the unanchored `**/.env.example`, `**/.env.sample`,
  `**/.env.template` and `**/.env.dist`, in both lists.
- Leave `denyRead` untouched.

## Consequences

- The four basenames become readable and writable anywhere on the machine the sandbox can
  reach, not only under `~/Code`. This is the accepted trade: a carve-out that is scoped to
  `~/Code` but dead, against one that works but is wider than `~/Code`.
- `denyRead`'s `**/.env.*` still denies every other `.env.*` spelling everywhere, so the
  widening is exactly these four basenames, nothing else named `.env.*`.
- Narrowing the carve-out back to `~/Code` is open. It needs a session to test what the
  sandbox matcher's dialect actually accepts for an anchored, multi-segment pattern, with the
  changed profile installed, before a narrower spelling is proposed again.
