---
name: usage-review
description: "Reviews token use, estimated cost and plan limit distance of Claude Code sessions per session, agent type, model, repository and skill, from the local transcripts and the recorded metrics. Use when a plan limit drains faster than expected or when delegation and model choices need evidence."
---

# usage-review

Answer who used how much, with numbers from the transcripts and the metrics store.

## When to use

- A weekly or five hour limit drained faster than the work explains.
- Delegation rules, model choice or skill size need evidence.
- Not for changing the rules. Findings go to an issue, then `propose-rule`.

## Steps

1. Pick the window. Default seven days. For a drained limit, use the length of that limit window.
2. Run the local report. It reads counters only, never message text.

   ```sh
   python3 ~/.claude/.agent-skills-hooks/usage_report.py --days 7 --top 15
   ```

3. Read the tables in this order:
   - By session: which session and repository used the most output and cache tokens.
   - By kind and model: main session against subagents, per model.
   - By agent type: which role costs most.
   - By day: which day spiked.
   - Cache misses: rebuilds of a large prompt, and how many followed an idle gap over five minutes.
   - Agents by length: subagents with many requests or a large peak context.
   - Main session prompt size: median and maximum prompt, compactions and their size.
4. Add cost at list price. Copy the current list prices per million tokens from the vendor
   pricing page into a scratch JSON file and pass `--prices <file>`.

   ```json
   {"<model name part>": {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}}
   ```

5. Query the metrics store for what transcripts lack. Check the exact metric and label names
   first, the collector may rename dots and add unit suffixes.
   - Plan limit over time: `claude_code.plan_limit.used_percentage` by `window`
     (`five_hour`, `seven_day`) and `session.id`. Take the maximum per day.
   - Context fill: `claude_code.context.used_percentage` by `session.id`.
   - Tokens per `session.id`, `model`, `agent.name`, `vcs.repository.name`, `type`:
     `claude_code.token.usage`. Cost: `claude_code.cost.usage`.
   - Skills used: `claude_code.token.usage` by `skill.name`. The log store has one
     `claude_code.skill_activated` event per activation, count them per skill.
   - Compactions: `claude_code.compaction` events, with `trigger`, `pre_tokens`, `post_tokens`.
   - Output: `claude_code.commit.count`, `claude_code.pull_request.count`,
     `claude_code.lines_of_code.count`, `claude_code.active_time.total`.
6. Relate usage to work. Join the session or repository with the issue from the branch name or
   the pull request. Name the issue next to the number.
7. Report per question: the number, the comparison, the likely cause, one proposed action.

## Rules

- Mark each number as transcript, metric or estimate.
- Cost on a subscription plan is a list price estimate, not a bill.
- Compare shares, not only totals: main session against subagents, cache read against cache
  create, output against input.
- A cache miss after an idle gap is expected. A miss with no gap points at a changed prefix.
- Tool detail logging is on, so `agent.name` and `skill.name` carry real names. The same
  setting exports tool parameters, for example the command of a shell call, to the collector.
  A secret in a command argument leaves the machine too.
  The local report has the agent type from the transcript as well.
- Transcripts are deleted after `cleanupPeriodDays`. Older questions need the metrics store.
- Other people's sessions are out of scope.

## Guardrails

- Never print message text, tool input or a secret. Run the report script, not a raw read of a
  transcript.
- Never run the report against fixtures of another person's machine.
- Never change settings or delegation rules from this skill. Propose them.
- The laptop profile only. The CI profile does not allow `python3`.
- The transcript format is not documented as stable. When the report shows nothing, say so and
  check the format before concluding the usage was zero.

## References

- The collector and the dashboard live in the infrastructure repository.
- Recording: the laptop profile exports metrics and events, the status line script sends the
  plan limit and context fill.
