---
name: agent-briefs
description: "Rules for the brief a subagent receives and the report it returns: what the brief holds, which preconditions the dispatcher verifies, and the shape of the report. Use when writing a brief for a subagent or asking an agent for its report."
---

# agent-briefs

Give an agent a brief it can act on, and ask for a report that stays short.

## When to use

- A subagent is about to be spawned or continued and needs a brief.
- A brief depends on a precondition, such as a file, a branch or a tool.
- An agent is asked for its report.

## Rules

### Briefs

- Give the agent the plan and the rules it needs, not the full conversation transcript.
- A reviewer's brief names the repository, the issue and the pull request, nothing about why
  the change is right.
- The dispatching session verifies every precondition a brief asserts before it sends the brief:
  a file exists where the brief says, a branch is where it says, a tool is installed.
- One account posts agent and owner comments, so an agent cannot tell them apart. A brief that
  relies on an owner decision quotes the owner's answer and its date.
- A brief that depends on work not merged yet says so plainly and gives the path to read it
  from. It never describes that work as present.
- A statement in a brief about how a tool behaves is an assumption until someone runs it. The
  brief labels it as one.
- An agent that finds a stated precondition false stops and reports it. It does not reconstruct
  what is missing. An unattended agent records it on the issue and stops that task.

### Report shape

- What changed, per target: a table or a short list, not a walkthrough.
- Which claims were verified by running something, and what ran.
- Which claims are unverified, and why.
- What it stopped on, if anything.
- Baseline feedback: a rule that blocked or misled, a rule that was missing, or "none".
- No narration of work already done. The report stays in the orchestrator's context and
  is paid for on every later request.

## Guardrails

- No precondition asserted in a brief before the dispatcher has checked it.
- No report longer than the shape above.

## References

- `agents` for when to spawn, scope, models, monitoring and termination.
