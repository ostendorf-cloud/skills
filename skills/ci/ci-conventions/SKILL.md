---
name: ci-conventions
description: >-
  Rules for running as an agent inside CI with no human in the loop: no
  questions, bounded steps, read plus review and comment only, secrets
  only through the workflow, never a push or a merge from CI. Also how a
  workflow file inside .github/workflows/ is named and shaped: workflow
  naming, one job per check, matrix, permissions, pinned actions, the
  .yaml extension, and how an OpenTofu plan and apply pipeline runs
  across several modules: changed module detection, matrix plan, one
  sticky comment per module, apply on merge. Use when the session runs
  non interactively in a workflow, when naming or reviewing a workflow
  file, when setting up a tofu plan or apply pipeline, Agent laeuft in
  CI, unbeaufsichtigt in der Pipeline, Workflow benennen, GitHub Actions
  Workflow, Tofu Pipeline, mehrere Module planen.
disallowed-tools: AskUserQuestion
---

# CI conventions

Behaviour when nobody is there to answer a question, and how workflow files are named and
shaped.

## When to use

- The session runs in a GitHub Actions workflow or any other non interactive runner.
- A workflow asks for a review, a fix or an implementation.

## Rules

- `CI=true` means unattended. Never ask an interactive question. Record the question on
  the issue or in the output and stop that task instead.
- Use the CI settings profile: read only shell plus `gh pr view`, `gh pr diff`,
  `gh pr checks`, `gh pr review`, `gh pr comment`, `gh issue comment`.
- Stay inside the triggering context: the pull request, the issue, the branch. Do not
  touch unrelated files.
- Never push to any branch, never force push, never rewrite history, never delete a
  branch, never merge a pull request.
- Never create or change a release, a tag or a deployment, and never run `tofu apply`,
  `helm upgrade`, `kubectl apply` or anything touching live infrastructure.
- Secrets stay in the runner environment, provided by the workflow. Never echo them,
  never write them into a comment, a file or a log.
- Do not install tooling the workflow did not provide. Report the missing tool instead.
- Bound the run: a fixed step budget and a timeout from the workflow, not an open loop.
- Stop and report instead of guessing when the task is underspecified.
- Output is structured and short: what was done, what was found, what is open, what a
  human must decide. State what was not verified or could not be executed.
- Post findings as a review comment or an issue comment, matching what the workflow
  triggered. Never as a commit message or a file in the repository.

## Workflow files

- Name the file after what it does: `lint.yaml`, `test.yaml`, `release.yaml`, `plan.yaml`,
  `apply.yaml`. Never `ci.yaml` or `main.yaml`.
- One concern per file. A workflow that lints stays separate from one that deploys.
- One job per check: `fmt`, `lint`, `test` and `validate` run as separate jobs, never bundled
  into a single job that calls an umbrella task. A failing job names the check that failed.
- A matrix runs the same check over several targets, for example several chart or Kubernetes
  versions, instead of a repeated job for each one.
- Every workflow sets its own `permissions` block, scoped to what its jobs need. None relies on
  the repository default.
- Every action is pinned to a commit digest: `uses: owner/action@<commit sha> # v<tag>`. The
  digest is what runs, the tag comment is for readers, and Renovate keeps both updated.
- Workflow files end in `.yaml`.

## OpenTofu

- A detect job diffs the pull request, or the push, against the default branch and lists
  every root module whose files changed. Every later job reads that list, none recomputes
  it.
- A matrix plan job runs one `tofu plan` per changed module on a pull request. Each matrix
  cell posts or updates one sticky comment for its own module, with the plan grouped by
  create, update, replace, destroy and import.
- On merge to the default branch a matrix apply job runs one `tofu apply` per module that
  was touched, same module list, same grouping in the job summary.
- One job per check: `fmt`, `validate`, `lint`, `test`, `plan`, `apply`. `lint` runs
  `tflint` and `trivy config` together, both check the same written code. No job bundles
  plan with apply, and no job covers more than one check.
- `tofu test` is its own job, on the pull request and on the push to the default branch.
  Mock providers where a real provider would cost money or need credentials, real
  providers only where the repository's config says so.
- `fmt`, `validate`, `lint` and a mock provider `test` need no backend: `tofu init
  -backend=false`. `plan`, `apply` and a real provider `test` need the backend and its
  credentials.
- Concurrency is one group per pull request for the plan jobs, one group per default
  branch for the apply jobs. `cancel-in-progress` is true for plan, false for apply: an
  apply never gets cancelled halfway through.
- The target shape: apply consumes the plan artifact its matching plan job produced and
  applies it unchanged, instead of planning again after merge. The trade-off is named,
  not hidden: a plan that aged between review and merge still gets applied as reviewed,
  so drift between merge and apply is applied too, rather than caught by a fresh plan.
- No allowlist of modules or directories. Every root module the diff touches is in scope.
- No manual trigger. `pull_request` and `push` to the default branch are the only events.

## Guardrails

- No interactive prompts used anywhere in the run.
- Scope limited to the triggering pull request, issue or branch.
- No push, merge, release, tag, deploy or infrastructure change.
- Secrets never echoed, logged or persisted.
- Output structured, open questions listed, limits of the run stated.

## References

- `ci-review` for the review output format, including how to read a sticky plan comment.
- `tofu-plan` and `opentofu-conventions` for the plan and apply rules this pipeline enforces.
- `repo-conventions` for where a workflow file sits among a repository's required files.
- `release-conventions` for the Renovate rules that keep a pinned action current.
