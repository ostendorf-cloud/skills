---
name: work-review
description: Reviews the pull request of one issue in review requested as a fresh independent agent, writes a GitHub review and routes the label to done, changes requested or needs human. Use when asked to review, check or sign off the AI implementation of an issue. Trigger phrases: review issue 42, check the PR for issue 42, Issue 42 review, PR gegenpruefen.
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
6. Write a GitHub review with `gh pr review`: approve, or request changes with inline comments
   through the review API.
7. Verdict approve: move the label to `done`, mark the pull request ready for review with
   `gh pr ready`.
8. Verdict fixable problems: move the label to `changes requested`, the review comment carries
   the concrete feedback.
9. Verdict needs a human call, or the round count reaches config `work.reviewRounds`: move the
   label to `needs human`, comment why.
10. Never merge the pull request.
11. Never approve a pull request implemented in this same session.

## Guardrails

- Review only: no edits, no commits, no merges.
- A different agent than the implementer, every time.
- `done` is a real acceptance. When unsure, `needs human`, never a rubber stamp.
- The round cap is a floor for a human decision, never a ceiling that waves through unfinished
  work.

## Config

Reads `.agent-skills.json` through the snippet in `skills/README.md`.

- `work.reviewRounds`: review rounds before escalating to `needs human`. Default `2`.
- `labels.reviewing`, `labels.done`, `labels.changesRequested`, `labels.needsHuman`: defaults in
  `skills/README.md`.
- `verify`: command that proves a change is good.

## References

- `gh pr review`, `gh pr ready`: <https://cli.github.com/manual/>
