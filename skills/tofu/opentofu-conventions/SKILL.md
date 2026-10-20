---
name: opentofu-conventions
description: OpenTofu conventions for file layout, typed variables, providers, state, naming,
  sensitive secrets and the Kubernetes provider boundary. Use when writing, reviewing or
  refactoring OpenTofu or Terraform code, or running a tofu command. Trigger phrases: write tofu,
  opentofu module, variables.tf, provider block, state backend, tofu plan, tofu apply,
  Tofu Code schreiben, Variablen Datei, Terraform Code, Statedatei.
---

# OpenTofu conventions

Infrastructure as code is written with OpenTofu. Terraform only where configured.

## When to use

- Writing or changing `.tf` files.
- Reviewing infrastructure code.
- Setting up a new root module or a module.
- Running `tofu init`, `plan`, `apply`, `validate` or `tflint`.

## Rules

### Tooling

- `tofu` is the binary. `terraform` only in a repository whose config sets `iac: terraform`.
- `tofu fmt` and `tofu validate` before every commit. `tflint` runs too.
- `tofu plan`, `tofu validate` and `tflint` run freely, no confirmation needed.
- `tofu apply` asks for confirmation first. `tofu destroy` is never run by an agent.
- `tofu output` and `tofu state show` are never run, both print secrets in clear. Read a secret
  through a `sensitive` aware path in code, or ask the user to read it themselves.
- `required_version` is set, provider versions constrained with `~>`. Lock file committed.

### Files

- `main.tf` for resources, `variables.tf` for inputs, `outputs.tf` for outputs, `versions.tf` for
  `required_version` and `required_providers`, `providers.tf` for provider configuration,
  `locals.tf` for locals.
- Every variable is declared in `variables.tf`, never in another file.
- Split `main.tf` by topic once it grows, for example `network.tf` or `storage.tf`.

### Naming

- Resource and variable names are stable, descriptive, snake_case. No index encoded into a name.
- One name per concept, consistent between a root module and the modules it calls.

### Variables and outputs

- Every variable has a `type` and a `description`. A default only where it is genuinely safe.
- Secret variables and outputs carry `sensitive = true`. Never a secret as a literal default.
- A secret read from a provider that does not mark it sensitive is wrapped in `sensitive()` at
  every use.
- No secret goes into an output in clear, marked sensitive or not: state keeps an output's value in
  plain text regardless of the flag. Pass a value between modules through a remote state data
  source instead.
- `validation` blocks where a wrong value would fail late or silently.

### Providers

- Official provider from the registry, pinned with `~>`. Never a fork or an abandoned provider.
- Provider configuration lives in the root module only. A module declares `required_providers` and
  configures nothing.
- The Kubernetes provider is used directly for a typed resource when a chart would add nothing:
  Namespace, ConfigMap, Secret, ServiceAccount, RBAC, StorageClass. See `kubernetes-conventions`
  for the full boundary against `helm_release`.

### Resources

- `for_each` over `count`. Adding or removing one element must not recreate the others.
- No environment specific value hardcoded. Use a variable instead.
- `prevent_destroy = true` on a server and on a stateful resource: a database, a volume, a bucket.

### State

- Remote backend with locking. Never local state in a repository, never a state file committed.
- One root module per blast radius. A module reads the state of the module before it, never the
  reverse.
- No wrappers, no generated HCL. Resources are written out by hand, even when that repeats a
  little.
- Bring an existing resource under management with an `import` block, never by deleting and
  recreating it.

## Guardrails

- Never run `tofu destroy`. Report the need and let the user run it.
- Never run `tofu output` or `tofu state show`. Both print secrets in plain text.
- Never apply without a plan that was reviewed and confirmed first.
- Never run a `terraform` command unless `.agent-skills.json` sets `iac: terraform`.
- Never give a chart or an inline manifest a job a typed provider resource already does cleanly.

## Config

- `iac`: infrastructure tool. Default: `opentofu`. `terraform` only when set explicitly.

## References

- `tofu-plan` for the plan and apply workflow.
- `tofu-module` for module layout.
- `kubernetes-conventions` for the Kubernetes provider and Helm boundary.
