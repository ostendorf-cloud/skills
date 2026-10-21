---
name: github-as-code
description: GitHub repositories, labels, rulesets and organisation secrets written as OpenTofu
  with the github provider, instead of changed by hand with gh or the web UI. Use when writing or
  reviewing OpenTofu that manages a repository, a label, a ruleset, an organisation secret or an
  organisation setting, or when asked to change one of those by hand. Trigger phrases: github
  provider, repository settings, rulesets, labels as code, org settings, Repo-Einstellungen.
---

# github-as-code

Repository, label, ruleset and organisation secret settings for GitHub as OpenTofu.

## When to use

- Writing or changing OpenTofu that manages a repository, a label, a ruleset or an organisation
  secret.
- Bringing a repository, a label set or a ruleset created by hand under management.
- Renaming a label a skill matches on.
- Asked to change a repository, organisation or label setting with `gh` or the web UI: refuse and
  propose the OpenTofu change instead.

## Rules

### Authentication

- `provider "github"` authenticates with an `app_auth` block or a `token`, never a literal
  credential in the configuration.
- Prefer `app_auth`: `id` and `installation_id` may sit in the configuration, `pem_file` comes from
  the secret manager.
- A `token` comes from the secret manager the same way, never typed into a variable default.
- `owner` is required on every provider block when authenticating with `app_auth`.

### Aliases

- One `provider "github"` block per organisation this module manages.
- The default organisation's block carries no `alias` and is declared first.
- Every other organisation's block carries `alias = "<organisation>"` and is declared after it.
- A resource for a non default organisation sets `provider = github.<alias>` explicitly.

### Repositories

- Repositories of one organisation are one map variable, keyed by repository name, fed to
  `github_repository` with `for_each`.
- Each map value carries the settings that vary per repository: visibility, topics, merge
  methods, whether the default branch is protected, required status checks, the label groups the
  repository opts into.
- `lifecycle { prevent_destroy = true }` on every repository.

### Labels

- The label catalog is a local map of named groups, each group a map of label name to color and
  description: `base`, `ai`, `priority`, `release`, `dependencies`, `community`, `stack`.
- `base`, `ai`, `priority` and `dependencies` use the exact names from `skills/README.md`'s label
  defaults and `agent-skills.schema.json`'s `types` and `priority` arrays.
- `community` holds the labels for public repositories only, `stack` one label per technology in
  the `stack: <name>` shape.
- A repository's map entry names the groups it opts into. `github_issue_labels` is authoritative
  per repository, built from the merge of the opted-in groups, never a group a repository did not
  choose.
- `github_issue_labels` recreates a label whose name changed and deletes the old one, dropping it
  from every issue. Renaming is a two-step change: add the new name as its own entry first, update
  every skill that reads the old name, then remove the old entry in a later commit.

### Rulesets

- `github_repository_ruleset`, never the legacy branch protection resource.
- `target = "branch"`, `conditions.ref_name.include` with `~DEFAULT_BRANCH` or an explicit ref,
  never left unset for a branch or tag target.
- `bypass_actors` typed by `actor_type`: `RepositoryRole` for the admin role, `Integration` for an
  app that must pass a gate on its own.
- Split one ruleset into several when a bypass should cover only part of the rules, for example a
  merge gate an app may bypass versus signature and deletion rules nobody bypasses.

### Secrets

- Organisation secrets are `github_actions_organization_secret`. The value is wrapped in
  `sensitive()` wherever it is read from the secret manager and is not already marked sensitive.
- `visibility = "selected"` plus `github_actions_organization_secret_repositories` scopes a secret
  to the repositories that need it. `selected_repository_ids` on the secret resource itself is
  deprecated, use the separate resource.
- `visibility = "all"` only for a secret every repository in the organisation needs.

### Membership

- Organisation and team membership stay outside this code, managed through the web interface or
  the organisation's own process.
- No `github_membership` or `github_team_membership` resource in this module.

### Import

- A repository, a label set or a ruleset created by hand is imported, never deleted and recreated.
- Write the resource block to match the hand made state first, then add an `import` block:
  - `github_repository`: `id` is the repository name.
  - `github_issue_labels`: `id` is the repository name.
  - `github_repository_ruleset`: `id` is `<repository>:<ruleset_id>`, the ruleset id read from the
    GitHub UI or API.
- Run `tofu plan` after adding the import block. A plan with changes means the resource still
  differs from the hand made one, fix it and plan again.
- Apply only once the plan shows no change. The import block stays in the configuration and is
  inert once the state already holds the resource.

## Guardrails

- Never a repository, organisation or label setting changed with `gh` or the web UI: propose the
  OpenTofu change instead.
- Never `github_branch_protection`: rulesets replace it entirely.
- Never a secret value as a literal, and never printed with `tofu output` or `tofu state show`.
- Never delete and recreate a resource that already exists by hand: import it.
- Never a label removed from the catalog while a skill still matches on its old name.

## Config

- `labels.*` (defaults in `skills/README.md`): the names the `ai`, `priority` and `dependencies`
  groups carry in the catalog.
- `priority` and `types` (defaults in `agent-skills.schema.json`): the names the `priority` and
  `base` groups carry in the catalog.

## References

- `opentofu-conventions` for file layout, state and the general provider rules this skill builds
  on.
- `tofu-plan` for reading the plan before an apply.
