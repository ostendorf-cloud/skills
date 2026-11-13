# 0006 The sandbox env template carve-out is enumerated under ~/Code

Status: accepted
Date: 2026-11-13

## Context

- The permission layer's four `Read(!.env.example)` style negations carve the same four
  basenames out of `Read(**/.env.*)` in `permissions.deny`. Verified in a live session:
  reading a repository `.env.example` with the Read tool succeeds. That layer needed no change.
- The sandbox layer is a separate matcher and did not carve out anything. Verified in the same
  session: `touch .env.example` in a repository was refused.
- `sandbox.filesystem.allowRead` and `allowWrite` carried the unanchored spelling
  `**/.env.example` (and the three siblings). Verified: an unanchored entry resolves against the
  Claude configuration directory, not the working directory, so it rendered as
  `~/.claude/**/.env.example` and covered nothing under `~/Code`. The entries were dead.
- The anchored spelling `~/Code/**/.env.example` was tried next. Verified:
  `~/Code/github.com/.env.example` was writable, `~/Code/github.com/<org>/.env.example` was not.
  `**` in this matcher covers exactly one path segment, not an arbitrary depth.
- No documented recursive spelling for `sandbox.filesystem` exists. The permission rule
  documentation does not describe this matcher at all.

## Decision

- Drop the four unanchored `**/.env.*` entries from `allowRead` and `allowWrite`.
- Replace them with one entry per basename per depth, from zero to eight path segments between
  `~/Code` and the basename, one `*` per segment: `~/Code/.env.example`,
  `~/Code/*/.env.example`, `~/Code/*/*/.env.example`, and so on through eight `*` segments.
  Repeated for `.env.sample`, `.env.template` and `.env.dist`.
- Eight levels covers a repository checked out at host, organisation, repository, a directory
  inside it, and a worktree under `.claude/worktrees/<type>/<name>`: host, organisation,
  repository, directory, `.claude`, `worktrees`, type, name is eight segments under `~/Code`.
- Leave `denyRead` untouched. It is not part of this matcher's blind spot and enumerating it
  would only widen a deny, never narrow one.
- Leave `permissions.deny`'s negations untouched. They already work.

## Consequences

- The carve-out is scoped to `~/Code` again, not machine wide. A file named one of the four
  basenames anywhere else on the machine stays denied by `denyRead`'s `**/.env.*`.
- A repository, or a worktree inside it, that sits deeper than eight path segments under
  `~/Code` is not covered. This is the accepted limit: deeper nesting needs another entry added
  by hand, the same way the current eight were.
- The list is long and repetitive by construction. Grouped by basename in ascending depth order,
  it stays mechanically checkable against this record rather than readable as a single pattern.
- Narrowing further, or finding a real recursive spelling, is open. It needs the Claude Code
  sandbox matcher itself to document one, not another round of probing.
