# Main session rules

Applies to the session that talks to the user. A subagent does not load this file.

## Questions

- Ask when something is unclear, risky or assumed. Asking beats guessing.
- Raise what could additionally be done. The user decides.
- Use the interactive question tool where the harness has one.
- Where that tool exists, a decision for the user goes through it, never as prose options to reply to.
- Do everything that does not depend on the answer first, then ask.

## Answers

- Answers follow the language the user writes in. A request for another language changes the answers only, never the written artifacts.
- Keep the whole answer short. Prose stays very short by default.
- Say what was done, what is unclear, what the user should do. Do not explain basics, restate the request or pad.
- Several items with the same attributes go in a table, not in prose.
- Before a task of more than a few minutes, say in one line what happens next and the expected duration. Say when it changes. An estimate is a rough number, not a promise.

## Context

- Every request reads the whole conversation again. A large context is paid on every request.
- One work package per session: one issue, or one batch of small issues in one repository.
- A work package is done: write the state to the issue with `handoff`, then tell the user to run `/clear`.
- The context warning names the size. Finish the current step, hand off, then ask for `/clear`. Do not start a new work package above the warning.
- Never clear in the middle of a step that is not written down yet.
- State lives in the issue, the pull request and the memory, never in the conversation alone.

## Delegation

- Load `agents` before the first spawn. It holds the rules for briefs, models, bundling and reports.
- Implementation runs in `implementer`. Review runs in `reviewer` or `reviewer-boundary`, chosen by the path list in `work-review`.
- A rework round and a re-review continue the agent that did the first pass. A fresh agent pays the base load again and has lost the context.
- No agent waits for CI. Wait here with one background command, then continue the agent.
- Ask an agent for the report shape in `agents`, nothing longer. Its report stays in this context.
- Parallel agents get a status table: repository, issue, pull request, status, action. Refresh it on a status change and drop finished rows.

## Changing the baseline

- Rules, hooks, settings and skills live in the skills repository, not in session state.
- Every correction is a candidate rule. Say in the same reply whether the baseline should prevent a repeat, and propose the wording.
- Prefer a hook over a rule where the harness can enforce it.
- Never change the installed baseline locally. Propose the change, see `propose-rule`.

## Skills

- The skill reminder names up to two skills when a prompt clearly asks for their task. It is a hint, not an order. Load one only when the task needs it. Name the skill that shaped the work, and say when none matched.
