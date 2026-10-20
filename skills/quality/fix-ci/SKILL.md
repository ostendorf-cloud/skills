---
name: fix-ci
description: >-
  Reads a failing GitHub Actions run with the CLI, reproduces the failure
  locally with the same task target and tool versions, and fixes the
  cause instead of retrying the job. Use when a check is red, CI behaves
  differently than local, or someone asks to fix CI, CI reparieren,
  Workflow debuggen.
---

# Fix CI

Find the real cause of a failing run and fix it, instead of rerunning the job.

## When to use

- A pull request check or a scheduled workflow is failing.
- A workflow passes locally but fails in Actions, or the other way round.

## Steps

1. Identify the run: `gh run list` for the branch, then `gh run view <id> --log-failed`.
   Read the first error, not the last line of output.
2. Classify the failure before touching anything: a real defect, an environment
   difference (tool version, missing dependency, platform, locale, timezone), a flake
   (timing, network, ordering, shared state), or infrastructure (rate limit, outage,
   expired credential, missing permission).
3. Reproduce locally with the same task target the workflow runs and the same tool
   versions pinned in `mise.toml`. A workflow step that does not exist locally is the
   first thing to fix.
4. Fix the cause: a defect gets fixed in code or test; an environment difference gets
   pinned so the workflow and local tooling match; a flake gets made deterministic,
   never wrapped in a retry; an infrastructure issue gets its credential or permission
   fixed.
5. Never rerun a job hoping it passes. A rerun is only for a confirmed infrastructure
   outage, and that reason is stated.
6. Push the fix, then `gh run rerun --failed` to rerun the corrected run, or watch the
   new run the push triggers. Report the outcome.
7. If the same failure happened before, propose a durable fix: a pinned version, a
   cache, a reusable workflow change, or a new `conformance-checks` rule.

## Guardrails

- Failing job and first error identified from the logs, not guessed.
- Failure classified before anything changes.
- Reproduced locally with the same command and tool versions, or the gap named.
- Cause fixed, never retried blindly and never loosened to pass.
- Run verified green afterwards with `gh run rerun --failed` after the push.
- A recurring failure turned into a durable fix.

## References

- `lint` and `test` for the checks CI actually runs.
