# 0002 The ask list stays short

Status: accepted
Date: 2026-10-20

## Context

- An `ask` rule forces a prompt even in auto mode and shadows every `allow` rule under it.
- `Bash(gh:*)` in `ask` produced a prompt for every comment, label and review.

## Decision

- `ask` holds only what a human must confirm: `gh pr merge`, `gh release`, `tofu apply`, `tofu state`, `kubectl delete`, `helm uninstall`, Talos upgrades, `brew`.
- Everything irreversible or secret revealing is `deny`. Everything else goes to the auto mode classifier.
- Hooks inspect the full command text where a prefix rule cannot, for example `gh api` with a mutating method.

## Consequences

- Push to a feature branch, pull requests, comments and reviews run without a prompt.
- A new confirmation need is a settings change in this repository, not a session habit.
