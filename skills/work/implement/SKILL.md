---
name: implement
description: Claims one ready or changes-requested GitHub issue, implements it on a worktree branch through a subagent, verifies, commits, pushes and opens a draft pull request, then hands it to review. Use when asked to implement, work on, pick up or build an issue, or to address review feedback. Trigger phrases: implement issue 42, work this issue, address the review feedback, Issue umsetzen, Ticket abarbeiten.
---

# implement

Take one issue from label to a pushed, reviewable pull request.

## When to use

- An issue carries `ai: ready` or `ai: changes requested` and needs implementing.
- Not the review of your own output: that is `work-review`.
- Draining many issues unattended: use `work-queue` instead.

## Steps

1. Pick the issue: the one named, or the highest priority eligible issue (`ready` or
   `changes requested`, no `needs triage`).
2. Claim it: move the label to `working`, assign yourself when the tracker allows it. Claim
   before any work.
3. Read the issue body, the `## Plan` section or latest plan comment, and the latest review
   feedback when re-working.
4. Create the branch and worktree via the `worktree` skill: `work.branch` strategy, default
   `worktree`, under `.worktrees/<branch>`, branch named `<type>/<issue-number>-<slug>`.
5. Implement through a subagent: Agent tool, model from the plan's per-step override or config
   `models.implement` (default `sonnet`), scoped to the files the plan named, carrying the house
   style rules.
6. Keep the change scoped to this one issue.
7. Run the verify command from config `verify`.
8. Verify fails and is not fixable, or the issue is ambiguous: move the label to `blocked`,
   comment the reason, stop.
9. Commit via the `commit` skill, referencing the issue.
10. Push the branch.
11. Open a draft pull request via the `pr` skill, body includes `Closes #<number>`.
12. Move the label to `review requested`.
13. Comment a short summary on the issue via the `tldr` skill template.
14. Interactive session: ask when something is genuinely unclear before step 5.
15. Unattended session (`CI=true`): never ask, record the question as an issue comment and move
    to `blocked` instead.

## Guardrails

- Claim (`working`) before any implementation work starts.
- Never review this skill's own output, never set `done`.
- On failure or ambiguity: `blocked` with the reason as a comment, never a silent stop.
- The subagent gets a bounded file scope and the house style, not the full transcript.
- `CI=true` means unattended: no questions to the user, only to the issue.

## Config

Reads `.agent-skills.json` through the snippet in `skills/README.md`.

- `work.branch`: `worktree` or `branch:<name>`. Default `worktree`.
- `models.implement`: default `sonnet`.
- `verify`: command that proves a change is good.
- `labels.working`, `labels.reviewRequested`, `labels.blocked`, `labels.changesRequested`:
  defaults in `skills/README.md`.
- `pr.draft`: must be `true` for this skill's pull requests.

## References

- Branching and worktrees: `worktree` skill.
- Commit conventions: `commit` skill.
- Pull request body and labels: `pr` skill.
