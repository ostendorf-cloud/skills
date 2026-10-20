---
name: review
description: Reviews a diff, a branch or a pull request and posts the result as a GitHub review
  with findings grouped by severity. Use when asked to review code, before merging a pull request,
  or before approving your own earlier work from a different session. Trigger phrases: review this,
  review the pull request, request changes, Code Review, PR reviewen.
---

# Review

Review a change the way a peer does who has to maintain it afterwards.

## When to use

- Before merging a pull request.
- Asked to look over a diff, a branch or a file.

## Steps

1. Establish the scope: `git diff <base>...HEAD`, or `gh pr diff <number>`. Read the issue or
   the pull request body for the intent before judging the code.
2. Read the changed code in its context, not only the diff hunks. A hunk that looks fine can
   still break a caller.
3. Check, in this order, and stop guessing where something cannot be verified:
   - correctness: edge cases, error paths, empty values, concurrency, idempotency
   - security: input validation, secrets, injection, permissions
   - operational impact: migrations, rollout, rollback, blast radius
   - conventions: the matching convention skill, naming, layout, Conventional Commits
   - tests: do the new paths have coverage, do the tests assert behaviour
   - documentation: README, docs, ADR or concept doc where the decision deserves one
4. Verify claims instead of asserting them. Run the verify command, run the linter, check the
   symbol that is supposedly unused.
5. Compare the change's author to the current session's own work. Never approve your own work.
6. Post the review with `gh pr review --approve`, `--request-changes` or `--comment`, with inline
   comments through `gh api` on the pull request's reviews endpoint where a finding has a line.
7. Group findings as blocker, should fix, nit, each naming the file, the line, the problem and a
   concrete fix. Leave anything a formatter or linter owns to that tool.
8. State plainly what was not reviewed and what could not be verified.
9. Approve only when no blocker and no should fix finding remains.

## Guardrails

- Never approve a change authored by the current session.
- Never approve while a blocker or a should fix finding stands.
- A claim about test results or a symbol's use is verified by running something, not recalled.
- Posting a review needs no confirmation. It is a comment, reversible like any other.

## Config

- `verify`: command used to check a claim about tests or lint. Default: `task lint && task test`.

## References

- `git-conventions` for the conventions a review checks against.
- `ci-review` for a review that runs non interactively in CI.
