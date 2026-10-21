---
name: ci-review
description: >-
  Reviews a pull request from CI as a GitHub review grouped by severity
  with file and line references, approving when nothing blocks and never
  merging or pushing. Use when a workflow triggers an automated pull
  request review, Pull Request aus der CI pruefen, automatisierte
  Review.
disallowed-tools: AskUserQuestion
---

# CI review

A pull request review a human can act on without rereading the diff.

## When to use

- A workflow triggers a review on a pull request.

## Steps

1. Read the pull request body and the linked issue for intent. No intent means the
   first finding is the missing description.
2. Get the diff with `gh pr diff` and read the changed files in context.
3. On an infrastructure pull request, read the sticky plan comment the OpenTofu pipeline
   posted for every touched module: replace and destroy rows first with their reason,
   then anything that looks like drift instead of the change itself, then the plan output
   for a secret value that should have stayed masked.
4. Review in order: correctness, security, operational impact, conventions, tests,
   documentation.
5. Verify what is verifiable in the runner: tests, linters, build. Report the real
   output. Never claim a check that did not run.
6. Classify findings: blocking (defect, security issue, data loss, breaking change
   without migration), should fix (convention violation, missing test, unclear naming,
   missing docs), nit (optional improvement). Drop anything a linter already owns.
7. Post the review with `gh pr review`: `--approve` when nothing blocks,
   `--request-changes` with concrete items when something does, `--comment` otherwise.
   Inline comments reference file and line through the API.
8. End the body with the limits of the review: what was not reviewed, what could not
   be verified.
9. Never merge, never push to the branch, unless the workflow explicitly asked for a
   fix commit.
10. When the work loop is in use, move the label from the config: `reviewing` while the
    review runs, `changesRequested` on request changes, `done` or `needsHuman` per the
    workflow's outcome. A missing label on the tracker is reported, never created.

## Output format

```markdown
## Blocking
- path/file.ext:42 problem, fix

## Should fix
- path/file.ext:88 problem, fix

## Nits
- path/file.ext:12 problem, fix

## Not verified
- checks that did not run, areas not reviewed
```

## Guardrails

- A sticky plan comment read for replace, destroy and secrets before anything else on an
  infrastructure pull request.
- Intent read before judging. Diff read in full, not sampled.
- Findings reference file and line and name a concrete fix.
- Severity separated, linter owned style dropped.
- Checks actually run, output real, nothing claimed that did not execute.
- Approve or request changes posted, never a merge or a push.
- Limits of the review stated in the output.

## Config

- `labels.reviewing`, `labels.changesRequested`, `labels.done`, `labels.needsHuman`:
  label names for the work loop. Defaults in the skills README. A missing label is
  reported, never created.

## References

- `ci-conventions` for the run itself and the OpenTofu pipeline that posts the plan
  comment.
