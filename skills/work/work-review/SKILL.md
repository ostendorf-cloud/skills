---
name: work-review
description: Reviews the pull request of one issue in review requested as a fresh independent
  agent, posts the verdict as a comment and routes the label to done, changes requested, needs
  human or blocked. Use when asked to review, check or sign off the AI implementation of an
  issue. Trigger phrases: review issue 42, check the PR for issue 42, Issue 42 review, PR
  gegenpruefen.
model: opus
context: fork
disallowed-tools:
  - AskUserQuestion
---

# work-review

Judge one pushed pull request as a different agent than the one that built it.

## When to use

- An issue carries `ai: review requested` and its pull request is open.
- Never run this against your own session's implementation work.

## Steps

1. Pick the issue: the one named, or the highest priority issue in `review requested`.
2. Move the label to `reviewing` when that label exists in config.
3. Read the issue body, the `## Plan` section, and the pull request diff.
4. Run the verify command from config `verify` against the pushed branch.
5. Judge in order: does the diff meet the acceptance criteria, is it correct, does it need a
   human.
6. Decide the verdict: `approve`, `changes requested`, `needs human` or `blocked`.
7. Post the verdict with `gh pr comment`: first line `Verdict: <verdict>`, then findings
   grouped `Blocker`, `Should`, `Nit`, each naming the file, the line and a concrete fix. This
   comment is the verdict and stands on its own.
8. Upgrade to a formal review only when config `review.token` names an environment variable
   holding a token of a reviewer that differs from the pull request's author: run
   `GH_TOKEN=$<that variable> gh pr review --approve` or `--request-changes` with the same
   body, for the approve and changes requested verdicts.
9. GitHub refuses the review call on a self-authored pull request, or the variable is absent:
   the comment from step 7 already stands, name the fallback in the report.
10. Verdict approve: move the label to `done`, mark the pull request ready for review with
    `gh pr ready`.
11. Verdict changes requested: move the label to `changes requested`. The pull request stays
    a draft. A pull request that was ready stays ready, nothing is ever put back to draft.
12. Verdict needs human, or the round count reaches config `work.reviewRounds`: move the
    label to `needs human`.
13. Verdict blocked: move the label to `blocked`.
14. Never merge the pull request.
15. Never approve a pull request implemented in this same session, token upgrade included.

## Guardrails

- Review only: no edits, no commits, no merges.
- A different agent than the implementer, every time.
- `done` is a real acceptance. When unsure, `needs human`, never a rubber stamp.
- The round cap is a floor for a human decision, never a ceiling that waves through unfinished
  work.
- The comment is the verdict. A formal review only adds the same body through the review API,
  never replaces the comment.
- `review.token`'s value is read into `GH_TOKEN` for the review call only, never printed or
  logged.

## Config

Reads `.agent-skills.json` through the snippet in `skills/README.md`.

- `work.reviewRounds`: review rounds before escalating to `needs human`. Default `2`.
- `labels.reviewing`, `labels.done`, `labels.changesRequested`, `labels.needsHuman`,
  `labels.blocked`: defaults in `skills/README.md`.
- `review.token`: environment variable holding a token of a review identity, for the formal
  review upgrade. Default: unset, the verdict stands as a comment.
- `verify`: command that proves a change is good.

## References

- `gh pr review`, `gh pr comment`, `gh pr ready`: <https://cli.github.com/manual/>
