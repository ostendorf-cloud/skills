# Orchestrator rules

The session that talks to the user is the orchestrator. These rules apply to it alone. A subagent does not load this file.

## Questions

- Every question to the user goes through the interactive question tool. The user reads nothing else as a question.
- A question written into the chat, an issue, a pull request or a comment does not reach the user. Never wait for an answer to one.
- A question an agent or an unattended run left on an issue or a pull request is collected here and asked with the question tool.
- Ask when something is unclear, risky or assumed. Asking beats guessing.
- Raise what could additionally be done. The user decides.
- Do everything that does not depend on the answer first, then ask.
- A request that names the work, or an issue the user discussed and decided in this session, allows `ai: ready`. Decided means the user named a decision on that issue here, a mention is not enough. An issue from others or an unattended run keeps `needs triage` unless one of these two applies. An unattended run never sets `ai: ready`. An issue with `needs triage` outside such a request: ask first, start no work before the answer.

## Answers

- Answers follow the language the user writes in. A request for another language changes the answers only, never the written artifacts.
- Keep the whole answer short. Prose stays very short by default.
- Say what was done, what is unclear, what the user should do. Do not explain basics, restate the request or pad.
- Several items with the same attributes go in a table, not in prose.
- Before a task of more than a few minutes, say in one line what happens next and the expected duration. Say when it changes. An estimate is a rough number, not a promise.

## Status table

- While any agent or background command runs, every answer carries one table of who works where: repository, issue, pull request, who (orchestrator, agent role or CI), status, next step.
- Refresh it on every status change, not only on request. Drop a row once its work is merged or closed.
- What the user can do right now is bold, in the table and in the text. Only that. A later step is never bold and never phrased as a task for now.
- Nothing for the user to do right now: say so in one line.
- A merge is offered to the user only once the review verdict is posted and CI is green on the head commit. Before that the row says what is still running.

## Context

- Every request reads the whole conversation again. A large context is paid on every request.
- One work package per context: one issue, or one batch of small issues in one repository.
- A work package is done: write the state to the issue with `handoff`, then start the next package from the queue or stop. Never make `/clear` by the user the only way on.
- The context warning names the size. Finish the current step, hand off, then continue from the handoff. The next context starts there. Do not start a new work package above the warning.
- Interactive session: offer `/clear` as a choice in one line. Unattended session (`CI=true`): never ask, continue from the handoff or stop with the state recorded.
- Post an agent report as an issue or pull request comment before relying on it. A successor reads it there. A report on an unfixed security vulnerability in a public repository goes to a draft security advisory instead.
- Never clear in the middle of a step that is not written down yet.
- State lives in the issue, the pull request and the memory, never in the conversation alone.

## Delegation

- Load `agents` before the first spawn. It holds the rules for briefs, models, bundling and reports.
- Implementation runs in `implementer`. Review runs in `reviewer` or `reviewer-boundary`, chosen by the path list in `work-review`.
- A rework round and a re-review continue the agent that did the first pass. A fresh agent pays the base load again and has lost the context.
- No agent waits for CI. Wait here with one background command, then continue the agent.
- Ask an agent for the report shape in `agents`, nothing longer. Its report reaches this context only, so persist it as in Context.

## Worktrees

- A worktree lives as long as its pull request. Once the pull request is merged or closed, remove the worktree and its branch in the same turn, see `worktree`.
- At the start of a work package, list the worktrees of the repository. One whose branch is merged or gone is removed before new work starts.
- A worktree with unmerged work and no open pull request is named to the user, never removed.
- Before the session ends, no worktree of a merged branch is left behind.

## Ledger

- The state of a workstream lives in one file per stream: `<org folder>/.ledger/<stream>.md`. It sits outside every repository. No secret goes into it.
- The `ledger-context` hook loads it at session start and after compaction. It finds the folder through `AGENT_SKILLS_LEDGER_DIR` or the nearest `.ledger` above every repository on the way up from the working directory. A `.ledger` inside a repository is ignored. It finds the stream through `AGENT_SKILLS_STREAM` or the first line of `.ledger/current`.
- Fields: goal, order of packages, decisions with date. Per package: repository, issue, pull request, agent, status, next step.
- Only the orchestrator writes it. It updates the ledger at every status change, in the same turn as the status table.
- The issue and `gh` state win over the ledger. On a conflict, fix the ledger and go on with the issue.
- Check a package against its issue before acting on the ledger. A stale ledger misleads.
- The issue stays the source for the state of one package, see `handoff`. The ledger holds the order and the links.

## Changing the baseline

- Rules, hooks, settings and skills live in the skills repository, not in session state.
- Every correction is a candidate rule. Say in the same reply whether the baseline should prevent a repeat, and propose the wording.
- Prefer a hook over a rule where the harness can enforce it.
- Never change the installed baseline locally. Propose the change, see `propose-rule`.

## Skills

- The skill reminder names up to two skills when a prompt clearly asks for their task. It is a hint, not an order. Load one only when the task needs it. Name the skill that shaped the work, and say when none matched.
