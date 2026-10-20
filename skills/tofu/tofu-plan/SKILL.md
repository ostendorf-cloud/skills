---
name: tofu-plan
description: Runs the OpenTofu plan workflow, reads the plan completely, groups changes by blast
  radius and applies only a saved plan file after explicit confirmation. Use when an infrastructure
  change should be planned, reviewed or applied, or when state and reality may have drifted.
  Trigger phrases: tofu plan, tofu apply, review a plan, infrastructure change, drift,
  Plan erstellen, Tofu anwenden, Drift pruefen.
---

# Plan and apply

Understand what a change does to real infrastructure before it happens.

## When to use

- Before applying any infrastructure change.
- When a plan output needs interpreting.
- When state and reality may have drifted apart.

## Steps

1. Confirm where this runs: directory, workspace or environment, and which backend and
   credentials are in use. Never plan against an environment that was not asked for.
2. `tofu fmt -check`, `tofu init` if needed, then `tofu validate` and `tflint`. All three run
   without asking.
3. `tofu plan -out=tfplan`. Keep the plan file, the apply must use exactly what was reviewed.
4. Read the plan completely and group the changes by blast radius:
   - create
   - update in place
   - replace, with the reason from the plan for every single one
   - destroy, with the reason from the plan for every single one
5. Present a short table of the grouped changes. Call out anything that causes downtime, data
   loss, a new public exposure or a credential rotation.
6. Check for drift: a diff that was not expected from the change itself is drift or a provider
   upgrade side effect, not something to apply blindly.
7. Stop and raise anything surprising instead of applying it. A replace of a stateful resource or
   an unrequested destroy is a stop condition, not a thing to explain away.
8. Ask for confirmation with the table. `tofu apply tfplan` only after it is given, and only that
   saved plan file. Never `-auto-approve`. Never `tofu destroy`.
9. After the apply: report what changed, and run a second plan to confirm no drift remains.
10. On failure, read the provider error, state what partially applied, and do not retry blindly.
11. State operations (`import`, `state mv`, `state rm`) are the user's to run. Prepare the command
    and the reasoning, do not execute it unasked.

## Guardrails

- Never apply without a plan that was read in full and confirmed.
- Never use `-auto-approve`.
- Never run `tofu destroy`.
- Never run `tofu output` or `tofu state show`, both print secrets in plain text.
- Never run a state mutating command without the user's explicit confirmation.

## References

- `opentofu-conventions` for the conventions a plan is checked against.
