---
name: release-conventions
description: >-
  Versioning and release rules: semantic versioning driven by Conventional
  Commits, release-please configuration, moving major tags, the Renovate
  conventions and the release labels release-please owns. Use when
  setting up release automation or deciding what a change means for the
  version, Release-Konventionen, Versionierung festlegen.
---

# Release conventions

How versions, changelogs and dependency updates get produced.

## When to use

- Setting up release automation or dependency updates in a repository.
- Deciding what a change means for the next version.
- Reviewing a release pull request or a Renovate configuration.

## Rules

### Versioning

- Semantic versioning, driven by Conventional Commits: `feat` is a minor, `fix` and
  `perf` are a patch, a `!` marker or a `BREAKING CHANGE` footer is a major. `chore`,
  `docs`, `ci`, `test`, `build`, `style` and `refactor` do not release on their own.
- Before `1.0.0` a breaking change bumps the minor. Reaching `1.0.0` is a deliberate
  decision, not a side effect.
- A version is never set by hand and never edited in a file release-please owns.

### release-please

- Configuration lives in `release-please-config.json`, state in
  `.release-please-manifest.json`. Both are committed.
- One repository version by default. Split into components only when parts are
  genuinely consumed and released separately.
- `bump-minor-pre-major` stays `true` until the deliberate `1.0.0` decision.
- The flow: commits land on the default branch, release-please maintains a release
  pull request, merging it creates the tag, the release and the changelog entry.
- A feature pull request merges as a merge commit, never squashed: every `feat` and `fix`
  commit stays visible to release-please on its own, instead of collapsing into one line
  release-please reads from the pull request title alone. release-please recommends squash
  merges. The merge commit is a deliberate deviation, the atomic commits matter more.
- Never push a tag by hand. A manual tag desynchronizes the manifest.
- `CHANGELOG.md` is generated. Hand edits are lost on the next release.

### Actions and workflow tags

- Every action is pinned to a commit digest: `uses: owner/action@<commit sha> # v<tag>`. The
  digest is what runs, the tag comment is for readers, and Renovate keeps both updated.

### Renovate

- Every repository extends the shared preset where the organisation provides one.
  Repository rules add to the preset, not copy it.
- Group updates that always release together: one pull request per logical upgrade.
- `:pinDigests` for container images and GitHub Actions, with Renovate updating both
  the tag and the digest.
- Automerge only for patch updates of trusted dependencies and digest only updates.
  Major updates always get their own reviewed pull request.
- Updates carry the `dependencies` label so the triage skill can find them.

### Release labels

- `autorelease: pending` and `autorelease: tagged` are owned by release-please. A
  missing label is reported, never created by hand.

## Guardrails

- Commit types match the intended version bump.
- release-please config and manifest committed, no hand written versions.
- Breaking changes documented with a migration path in the commit body.
- Actions and images pinned by digest, with Renovate keeping them current.
- Automerge limited to low risk updates, major updates always reviewed.

## References

- `ci-conventions` for workflow files and the action pinning rule.
- `git-conventions` for the merge strategy that keeps commits visible to release-please.
- <https://github.com/googleapis/release-please>
- <https://www.conventionalcommits.org/en/v1.0.0/>
- <https://docs.renovatebot.com/configuration-options/>
