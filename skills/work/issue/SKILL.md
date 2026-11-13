---
name: issue
description: Creates or updates a GitHub issue with gh issue create or gh issue edit, after a duplicate search, with Goal, Context, Acceptance criteria and Out of scope sections, one type label and a priority label when known. Use when filing, opening or updating an issue or ticket, or when asked to create a bug, feature or research issue. Trigger phrases: open an issue, create a ticket, file a bug, Issue erstellen, Ticket anlegen.
---

# issue

File or update one GitHub issue with a clear outcome and testable criteria.

## When to use

- Opening a new issue in any repository.
- Updating an existing issue's body, labels or milestone.
- Issue exists but is too thin to implement: use `refine-issue` instead.
- A security vulnerability in a public repository with no fix merged yet: skip this skill, open
  a draft security advisory, or go straight to a branch and pull request instead. See the
  baseline's Plans and issues rule.

## Steps

1. Duplicate search: `gh issue list --search "<keywords>" --state all`.
2. Match found: comment there, do not open a second issue.
3. Pick the type: bug, feature, improvement, documentation or security, from config `types`.
4. Title: one line, imperative for feature or improvement, symptom for bug.
5. Write the body to a file with sections Goal, Context, Acceptance criteria, Out of scope, as
   bullets.
6. Acceptance criteria as checkboxes, verifiable without reading the diff.
7. Confirm labels and milestone exist: `gh label list`,
   `gh api repos/{owner}/{repo}/milestones --jq '.[].title'`.
8. Create: `gh issue create --title "<title>" --body-file <file>`, or update:
   `gh issue edit <number> --body-file <file>`.
9. Add exactly one type label. Add the priority label from config `priority` when the user named
   one.
10. Add `needs triage` on new issues, unless the user explicitly asks for `ai: ready`.
11. Never set `ai: ready` unless the user says so explicitly in this request.
12. Reference related issues with `#<number>`. Link blocking or blocked issues with
    `gh issue edit --add-blocked-by`.
13. A missing type, priority or state label on the tracker is reported, never created.
14. Never write a version, changelog entry or release note.
15. Report the issue URL.

## Template

```markdown
## Goal
<One line. What is true once done.>
## Context
- Trigger: <issue, PR, incident or discussion link>
- Affected: <repository, service or module>
## Acceptance criteria
- [ ] <Verifiable statement>
- [ ] <Tests covering the new behavior>
## Out of scope
- <What this deliberately does not change>
```

## Guardrails

- Duplicate search happens before every create.
- Setting `ai: ready` uses the snippet in `skills/README.md`: exactly one `ai:` state
  label remains afterwards, on a reopened issue too.
- Exactly one type label per issue.
- `ai: ready` and `needs triage` are set only on explicit instruction from the user, never
  guessed.
- A label absent on the tracker is named in the report, never created by this skill.
- An unfixed security vulnerability in a public repository gets no issue: see the baseline's
  Plans and issues rule.

## Config

Reads `.agent-skills.json` through the snippet in `skills/README.md`.

- `types`: issue type labels. Default `bug`, `feature`, `improvement`, `documentation`,
  `security`.
- `priority`: priority labels, highest to lowest. Default `priority: urgent`, `priority: high`,
  `priority: medium`, `priority: low`.
- `labels.needsTriage`: default `needs triage`.
- `labels.ready`: default `ai: ready`.

## References

- `gh issue create`, `gh issue edit`: <https://cli.github.com/manual/>
