---
name: grill-me
description: "Questions the owner about a plan or an issue in rounds until no open assumption is left, then records the decisions with the date as one issue comment. Use before work starts on a plan with unchecked assumptions, risks or undefined terms."
---

# grill-me

Close every open assumption of a plan or an issue with the owner before any work starts.

## When to use

- The owner asks to be grilled, challenged or questioned on a plan, an idea or an issue.
- A plan or an issue rests on assumptions nobody has confirmed.
- Not for a thin issue that needs acceptance criteria: use `refine-issue`.
- Not for a plan of steps and files: use `plan`.
- `refine-issue` restates the issue and writes its criteria. `plan` writes the approach. This skill
  probes the owner's own assumptions, and neither of the others does.

## Steps

1. Unattended session (`CI=true`): skip the rounds. Record the open points as one comment with
   `gh issue comment <number> --body-file <file>` and stop.
2. Read the plan or the issue and every comment: `gh issue view <number> --comments`.
3. List three things: the assumptions, the risks and the undefined terms. Check each against the
   code or the docs first. Ask only what a read cannot answer.
4. Ask the open points through the interactive question tool, in rounds of at most four
   questions.
5. Each question offers concrete options. The recommended option comes first and says why in
   one line.
6. Fold the answers in. An answer may raise a new open point: add it to the list.
7. Stop when a round raises no new open point.
8. Write the decisions as one comment on the issue with `gh issue comment <number> --body-file
   <file>`. Each decision carries the date.
9. Stop. No other write, no branch, no label change.

## Template

```markdown
## Decisions <YYYY-MM-DD>
- <Question>: <decision>. <Reason in one line.>
## Still open
- <Point nobody could answer> (<who answers>)
```

## Guardrails

- Every question goes through the question tool, never as plain text.
- At most four questions per round.
- Never guess an answer the owner did not give.
- The one issue comment is the only write. No file, no issue body edit, no label.
- Unattended runs never ask.
- Never change `refine-issue` or `plan` behaviour from here. Hand over to them when the issue
  needs criteria or a plan.

## References

- `gh issue view`, `gh issue comment`: <https://cli.github.com/manual/>
