---
name: agents
description: Rules for delegating work to subagents, when to spawn, how to scope and bound their files, model routing by role, and the requirement to verify results and terminate every finished or stale agent. Use when spawning, coordinating or cleaning up subagents or teammates. Trigger phrases: spawn an agent, run this in parallel, clean up the agents, Subagenten einsetzen, Agenten aufraeumen.
---

# agents

Delegate only where it pays, scope it tightly, and never leave an agent running.

## When to use

- Work splits into independent parts that can run in parallel.
- An independent reviewer is needed for a diff or a decision.
- A long search or audit would flood the main session with output.

## Rules

- Direct work stays narrow: a read, a lookup, a one line nit. Every change that alters behaviour
  goes through a subagent, however small it looks.
- One bounded scope per agent: the goal, the files it may touch, the house style, what it must
  not do.
- Model routing by role: plan `opus`, implement `sonnet`, review `opus`. A plan may override one
  task's model and states why in one line, tokens and time against capability.
- Parallel spawning only for independent work. One agent waiting on another is sequential work
  pretending to be parallel.
- Every spawned agent reports status back to the session that spawned it. The report ends with
  baseline feedback: a rule that blocked or misled, a rule that was missing, or "none".
- The session collects that feedback and raises what is worth a change through `propose-rule`,
  one issue per rule, never silently.
- Agent output is a claim, not a fact: verify files, run tests, read the diff before relying on
  it.
- Terminate every agent whose work is done, or that is stale or stuck. Idle is not done: an agent
  that finished a step and waits for the next instruction stays alive on purpose, judged by its
  reported state, never by idleness alone.
- A conflict between two agents' changes, such as a merge conflict on overlapping files from
  parallel work or a review finding that traces to one agent's change, is resolved by the agent
  that caused it. Not by a third agent, and not absorbed silently by the supervising session.
  Exception: the causing agent is already terminated, stale or stuck. Then the supervising
  session resolves the conflict directly, or reassigns a fresh agent, and says so in its report.
- Check the running agent list before spawning more, and again before ending the session. The
  list must be empty at the end.
- Never ask an agent to do something that was denied in this session. Never route work through an
  agent to get around a permission decision.
- Give the agent the plan and the rules it needs, not the full conversation transcript.

### Monitoring

- State an expected duration when spawning an agent.
- Not reported by then: check its status and last output instead of waiting longer.
- Stuck, idle or looping: terminate it, then reassign its scope or finish it directly.
- Agent team mode: a teammate idle without reporting is asked once, then terminated if still
  silent.
- Never leave an agent or teammate running at the end of the session.

## Steps

1. Decide whether the work is a read, a lookup or a one line nit. Anything else goes to a
   subagent.
2. Split the work so results do not overlap, name the output of each agent.
3. Spawn with scope, files, style and a reporting instruction.
4. Collect results, verify them, resolve conflicts between agents per the rule above.
5. Terminate every agent, confirm the list is empty.
6. Report outcome per agent, including what was rejected.

## Guardrails

- Scope, allowed files and style given to every agent, no exceptions.
- Results verified before being relied on.
- Agent list empty before the session ends.
