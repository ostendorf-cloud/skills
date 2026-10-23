---
name: work-review
description: Reviews the pull request of one issue in review requested as a fresh independent
  agent, posts the verdict as a comment and routes the label to done, changes requested, needs
  human or blocked. Use when asked to review, check or sign off the AI implementation of an
  issue. Trigger phrases: review issue 42, check the PR for issue 42, Issue 42 review, PR
  gegenpruefen.
model: sonnet
context: fork
disallowed-tools:
  - AskUserQuestion
---

# work-review

Judge one pushed pull request as a different agent than the one that built it.

## When to use

- An issue carries `ai: review requested` and its pull request is open.
- Never run this against your own session's implementation work.

## Independence

- This skill forks the calling session, so it is independent of the implementation only when
  `implement` ran the code through its own bounded subagent for this issue, never when the
  supervising session wrote the code directly. The fork would otherwise inherit that work.
- Not independent: `approve` can still be the judgment, but the label never reaches `done`
  through it, see step 10.

## Steps

1. Pick the issue: the one named, or the highest priority issue in `review requested`.
2. Move the label to `reviewing` when that label exists in config.
3. Read the issue body, the `## Plan` section, the pull request diff, and every review thread
   already on the pull request through `gh api graphql` (`reviewThreads`, with `isResolved` and
   each comment's body). A rework round starts from these, not from memory of the first pass.
4. Run the verify command from config `verify` against the pushed branch.
5. Judge in order: does the diff meet the acceptance criteria, is it correct, does it need a
   human. For every open thread from step 3, decide whether its finding is now fixed.
6. Decide the verdict: `approve`, `changes requested`, `needs human` or `blocked`.
7. Resolve every open thread from step 3 whose finding is now fixed, one GraphQL
   `resolveReviewThread` mutation per thread, before posting the new verdict. A finding that
   still stands keeps its thread open and is restated in this round's verdict instead of a
   second thread for the same problem.
8. The pull request's author differs from this review's identity, or config `review.token`
   names an environment variable holding a token of such a reviewer: post the verdict as a
   formal review, `POST /repos/{owner}/{repo}/pulls/{number}/reviews` through `gh api`, with
   `event` from the verdict, `commit_id` the pull request's full 40 character head SHA (a short
   SHA fails with 422), and `comments`: one entry per finding, `{path, line, side: "RIGHT",
   body: "<Blocker|Should|Nit>: <problem and fix>"}`. This formal review is the verdict; post no
   separate comment.
9. The pull request's author is this review's own identity, or the token in step 8 is absent:
   GitHub refuses the review call. Post the verdict with `gh pr comment` instead: first line
   `Verdict: <verdict>`, then findings grouped `Blocker`, `Should`, `Nit`, each naming the file,
   the line and a concrete fix. Name the fallback in the report.
10. A finding's line falls outside every diff hunk in either path: anchor the inline comment at
    the nearest changed line in the same file and name the real location in its body, or, with
    no changed line in that file at all, put the finding in the top level review or comment body.
11. Verdict approve, and this review is independent per Independence: move the label to `done`,
    mark the pull request ready for review with `gh pr ready`.
12. Verdict approve, not independent: treat it like step 14, `needs human`, naming in the report
    that the judgment was approve but independence was missing.
13. Verdict changes requested: move the label to `changes requested`. The pull request stays
    a draft. A pull request that was ready stays ready, nothing is ever put back to draft.
14. Verdict needs human, or the round count reaches config `work.reviewRounds`: move the
    label to `needs human`. The round count is the number of this skill's own verdict comments
    and formal reviews already on the pull request, including the one just posted. Mark the
    pull request ready with `gh pr ready` when the `pr` skill's ready condition holds and only
    a human decision is left. Leave it a draft otherwise.
15. Verdict blocked: move the label to `blocked`.
16. Changes requested or blocked: point the issue comment at the `implement` skill for the
    rework round.
17. Never merge the pull request.
18. Never approve a pull request implemented in this same session, formal review included.

## Guardrails

- Review only: no edits, no commits, no merges.
- Move the label with the snippet in `skills/README.md`: exactly one `ai:` state label
  remains after the move.
- The supervising session picks the model before it spawns this review: `models.reviewBoundary`
  for a change to settings, the sandbox, a hook that denies, a release path or a large diff,
  `models.review` otherwise. A re-review checks the finding list only, same or cheaper model.
- A different agent than the implementer, every time, per Independence.
- `done` is a real acceptance, and only reachable through an independent review. When unsure,
  `needs human`, never a rubber stamp.
- The round cap is a floor for a human decision, never a ceiling that waves through unfinished
  work.
- A formal review or a `gh pr comment`, never both, for the same round's verdict. Resolving a
  thread never substitutes for stating whether its finding passed in the new verdict.
- A finding of the shape "does this write happen" is verified by counting the write at its
  source, a reflog entry, a call count on a fake, a log line, never by comparing state before
  and after: an identical write leaves the result identical.
- `review.token`'s value is read into `GH_TOKEN` for the review call only, never printed or
  logged.

## Config

Reads `.agent-skills.json` through the snippet in `skills/README.md`.

- `work.reviewRounds`: review rounds before escalating to `needs human`. Default `2`.
- `models.review`: default `sonnet`. `models.reviewBoundary`: default `opus`.
- `labels.reviewing`, `labels.done`, `labels.changesRequested`, `labels.needsHuman`,
  `labels.blocked`: defaults in `skills/README.md`.
- `review.token`: environment variable holding a token of the review app, see the Apps section
  of `github-as-code`. Default: unset, the verdict stands as a comment.
- `verify`: command that proves a change is good.

## References

- `gh pr review`, `gh pr comment`, `gh pr ready`, `gh api graphql`:
  <https://cli.github.com/manual/>
- `pr` skill: the ready condition for leaving draft.
- `implement` skill: the rework round a `changes requested` or `blocked` verdict hands off to.
