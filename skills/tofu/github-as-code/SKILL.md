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
- Asked to change a repository, organisation or label setting by hand: refuse, propose OpenTofu.

## Rules

### Authentication

- `provider "github"` authenticates with an `app_auth` block or a `token`, never a literal
  credential in the configuration.
- Prefer `app_auth`: `id`, `installation_id` in the configuration, `pem_file` from secret manager.
- A `token` comes from the secret manager the same way, never typed into a variable default.
- `owner` is required on every provider block when authenticating with `app_auth`.

### Aliases

- One `provider "github"` block per organisation this module manages.
- The default organisation's block carries no `alias` and is declared first.
- Every other organisation's block carries `alias = "<organisation>"` and is declared after it.
- A resource for a non default organisation sets `provider = github.<alias>` explicitly.

### Repositories

- Repositories of one organisation are one map variable, keyed by repository name, fed to
  `github_repository` with `for_each`; each value carries what varies: `visibility`, the label
  groups it opts into. Fixed for every repository: `allow_merge_commit = true`,
  `allow_squash_merge = false`, `allow_rebase_merge = false`, `delete_branch_on_merge = true`.
- Branch protection and required status checks are ruleset input, not `github_repository`
  attributes: they feed `github_repository_ruleset`, keyed the same way.
- `lifecycle { prevent_destroy = true }` on every repository: removing a map key fails first.

### Labels

- The label catalog is a local map of named groups, each group a map of label name to color and
  description: `base`, `ai`, `priority`, `release`, `dependencies`, `community`, `stack`.
- `base` holds config `types`, `needs triage` (config `labels.needsTriage`), `duplicate`,
  `question`, and the context labels `breaking-change`, `deprecated`, `research`, `upstream`.
- `ai` and `dependencies` use the exact names from `skills/README.md`'s label defaults, `priority`
  the `agent-skills.schema.json` `priority` array.
- `release` holds `autorelease: pending` and `autorelease: tagged`, set only by release-please;
  the catalog keeps both so the authoritative resource below does not delete them.
- `community` holds `good first issue` and `help wanted` for public repositories, `stack` exactly
  the keys of config `stacks`.
- `github_issue_labels` is authoritative per repository, built from its chosen groups; an unlisted
  label is deleted on apply, so the catalog is a superset of every label any skill matches on.
- `github_issue_labels` recreates a renamed label and deletes the old one, dropping it from every
  issue: add the new name as its own entry, update every skill that reads the old name, then
  remove the old entry in a later commit.

### Rulesets

- `github_repository_ruleset`, never the legacy `github_branch_protection` resources.
- `enforcement` is required: `active` enforces, `evaluate` logs without blocking and exists
  for organisation owned repositories only, `disabled` keeps the ruleset inert.
- `target = "branch"`, `conditions.ref_name` required with both `include` and `exclude`:
  `~DEFAULT_BRANCH` or an explicit ref in `include`, `exclude = []` as the default.
- `bypass_actors` typed by `actor_type` (`RepositoryRole` for the admin role, `Integration` for
  an app) and timed by `bypass_mode`: `pull_request` for a merge gate, `always` only for admins.
- Split one ruleset into several when a bypass should cover only part of the rules, for example a
  merge gate an app may bypass versus signature and deletion rules nobody bypasses.

### Secrets

- Organisation secrets are `github_actions_organization_secret`; the value attribute is `value`
  or `value_encrypted`, wrapped in `sensitive()` unless already sensitive. Never
  `plaintext_value` or `encrypted_value`, both deprecated.
- `visibility = "selected"` plus `github_actions_organization_secret_repositories` scopes a
  secret to the repositories that need it. `all` only for a secret every repository needs.
  `selected_repository_ids` on the secret resource is deprecated.

### Membership

- Organisation and team membership stay outside this code: the web UI or the organisation's process.
- No `github_membership` or `github_team_membership` resource in this module.

### Import

- A repository, a label set or a ruleset created by hand is imported, never deleted and recreated.
- Write the resource block to match the hand made state first, then add an `import` block naming
  the target with `to` and the hand made resource with `id`.
- `id` formats: `github_repository` and `github_issue_labels` take the repository name,
  `github_repository_ruleset` takes `<repository>:<ruleset_id>`, read from the GitHub UI or API.
- Run `tofu plan` after adding the import block. A plan with changes means the resource still
  differs from the hand made one, fix it and plan again.
- Apply only once the plan shows no change: the import block stays in the configuration and is
  inert once the state already holds the resource.

## Guardrails

- Never change a repository, organisation or label setting with `gh` or the web UI: use OpenTofu.
- Never `github_branch_protection` or `github_branch_protection_v3`: rulesets replace both.
- Never a secret value as a literal, and never printed with `tofu output` or `tofu state show`.
- Never delete and recreate a resource that already exists by hand: import it.
- Never a label removed from the catalog while a skill still matches on its old name.

## Config

- `types` (default `bug`, `feature`, `improvement`, `documentation`, `security`): the `base`
  group's type labels.
- `labels.needsTriage` (default `needs triage`) and `labels.dependencies` (default
  `dependencies`) feed the `base` and `dependencies` groups.
- `labels.ready` through `labels.blocked` (defaults in `skills/README.md`) feed the `ai` group.
- `priority` (default `priority: urgent`, `priority: high`, `priority: medium`, `priority: low`):
  the `priority` group.
- `stacks` (default none): the `stack` group's names.

## References

- `opentofu-conventions` for file layout, state and the general provider rules this skill builds
  on.
- `tofu-plan` for reading the plan before an apply.
