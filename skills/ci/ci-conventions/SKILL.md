---
name: ci-conventions
description: >-
  Rules for running as an agent inside CI with no human in the loop: no
  questions, bounded steps, read plus review and comment only, secrets
  only through the workflow, never a push or a merge from CI. Use when
  the session runs non interactively in a workflow, Agent laeuft in CI,
  unbeaufsichtigt in der Pipeline.
disallowed-tools: AskUserQuestion
---

# CI conventions

Behaviour when nobody is there to answer a question.

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

## Guardrails

- No interactive prompts used anywhere in the run.
- Scope limited to the triggering pull request, issue or branch.
- No push, merge, release, tag, deploy or infrastructure change.
- Secrets never echoed, logged or persisted.
- Output structured, open questions listed, limits of the run stated.

## References

- `ci-review` for the review output format.
