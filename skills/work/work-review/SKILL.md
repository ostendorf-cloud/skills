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
  through it, see step 13.

## Steps

1. Pick the issue: the one named, or the highest priority issue in `review requested`.
2. Move the label to `reviewing` when that label exists in config.
3. Read the issue body, the `## Plan` section, the pull request diff, and every review thread
   already on the pull request through `gh api graphql` (`reviewThreads`, with `isResolved` and
   each comment's body). A rework round starts from these, not from memory of the first pass.
4. Read the pull request's own CI result for the current head, `gh pr checks`, before trusting
   any `## Verification` section. One that names no commit is unverified, not true.
5. Run the verify command from config `verify` against the pushed branch.
6. Judge in order: does the diff meet the acceptance criteria, is it correct, does it need a
   human. For every open thread from step 3, decide whether its finding is now fixed.
7. Decide the verdict: `approve`, `changes requested`, `needs human` or `blocked`; nits alone
   are `approve`, named in the verdict for the supervising session to fix. Name the commit CI
   was green on, part of the verdict text in steps 9 and 10.
8. Resolve every open thread from step 3 whose finding is now fixed, one GraphQL
   `resolveReviewThread` mutation per thread, before posting the new verdict. A finding that
   still stands keeps its thread open and is restated in this round's verdict instead of a
   second thread for the same problem.
9. Review only, per Guardrails: no edit to the code under review and no commit of its own,
   whichever posting path follows. The pull request's author differs from this review's
   identity, or config `review.token` names an environment variable holding a token of such a
   reviewer: post the verdict as a formal review,
   `POST /repos/{owner}/{repo}/pulls/{number}/reviews` through `gh api`, with `event` from the
   verdict, `commit_id` the pull request's full 40 character head SHA (a short SHA fails with
   422), `body` naming the commit CI was green on, and `comments`: one entry per finding,
   `{path, line, side: "RIGHT", body: "<Blocker|Should|Nit>: <problem and fix>"}`. This formal
   review is the verdict; post no separate comment.
10. The pull request's author is this review's own identity, or the token in step 9 is absent:
    GitHub refuses the review call. Post the verdict with `gh pr comment` instead: first line
    `Verdict: <verdict>`, naming the commit CI was green on, then findings grouped `Blocker`,
    `Should`, `Nit`, each naming the file, the line and a concrete fix. Name the fallback in the
    report.
11. A finding's line falls outside every diff hunk in either path: anchor the inline comment at
    the nearest changed line in the same file and name the real location in its body, or, with
    no changed line in that file at all, put the finding in the top level review or comment body.
12. Verdict approve, independent per Independence: move the label to `done`, mark the pull
    request ready with `gh pr ready`.
13. Verdict approve, not independent: treat it like step 15, `needs human`, naming in the
    report that the judgment was approve but independence was missing.
14. Verdict changes requested: move the label to `changes requested`. The pull request stays
    a draft. A pull request that was ready stays ready, nothing is ever put back to draft.
15. Verdict needs human, or the round count reaches config `work.reviewRounds`: move the
    label to `needs human`. The round count is the number of this skill's own verdict comments
    and formal reviews already on the pull request, including the one just posted.
16. Label now `needs human`: mark the pull request ready with `gh pr ready` when the `pr`
    skill's ready condition holds and only a human decision is left, otherwise leave it a draft.
17. Verdict blocked: move the label to `blocked`.
18. Changes requested or blocked: point the issue comment at the `implement` skill for the
    rework round.
19. Never merge the pull request.
20. Never approve a pull request implemented in this same session, formal review included.

## Guardrails

- Review only: no edit to the code under review, no commit, no merge.
- A reviewer may write a throwaway probe to settle a claim it cannot settle by reading: a
  script in the session's scratch directory, or a temporary test file in the worktree. Both
  forms are deleted in the same task, never left behind.
- The probe is a file of its own, never the code under review. It is never committed, never
  staged, never pushed, and the worktree is left exactly as it was found.
- A claim settled only by reading, and not by running something, is named unverified in the
  verdict, with what it rests on instead, whether or not running it was ever attempted.
- Move the label with the snippet in `skills/README.md`: exactly one `ai:` state label
  remains after the move.
- The supervising session picks the model before it spawns this review: `models.reviewBoundary`
  for a change to settings, the sandbox, a hook that denies, a release path or a large diff,
  `models.review` otherwise. A re-review checks the finding list only, same or cheaper model.
- A different agent than the implementer, every time, per Independence.
- `done` is a real acceptance, and only reachable through an independent review. When unsure,
  `needs human`, never a rubber stamp.
- A `## Verification` section is a claim, not evidence. The pull request's own CI result for
  the current head decides whether it still holds.
- Every verdict names the commit CI was green on, formal review and comment path alike.
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
