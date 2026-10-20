# 0001 Hooks deny or inform, they do not ask

Status: accepted
Date: 2026-10-20

## Context

- Sessions should run unattended for hours. A hook that asks stops the run until a human answers.
- Auto mode already reviews every action a rule does not settle.

## Decision

- A hook returns `deny` with the rule and the alternative, or adds context. It never returns `ask`.
- Prompts come only from `permissions.ask`: merge, release, apply, delete class commands.

## Consequences

- A denied command is a decision the agent follows. It fixes the command or reports the blocker.
- A rule that needs judgement is not a hook. It is a rule in `baseline.md` or a skill.
