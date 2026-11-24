# 0008 Run package managers outside the sandbox

Status: accepted
Date: 2026-11-24

## Context

- Inside the sandbox `go get` fails the TLS check with `x509: OSStatus`. The sandbox blocks the
  macOS certificate service, although `sandbox.network.allowedDomains` already allows every host.
- A session cannot raise a dependency or regenerate a lock file. It hands each change to the
  owner as a command to run. This blocks the work at every govue release and every Renovate
  follow up.
- `go mod download` and `go mod tidy` already run outside the sandbox through
  `sandbox.excludedCommands`. `go get` and `pnpm install` were missing.
- pnpm can run lifecycle scripts of a dependency. Run outside the sandbox, they run with the
  rights of the user.

## Decision drivers

- An agent finishes a dependency change without a hand over.
- The commands that leave the sandbox stay few and named.
- No command that leaves the sandbox can install a tool or run a script of the agent's choice.

## Options considered

- Leave it and hand the commands to the owner. Safe, but it blocks the work each time.
- Add a sandbox rule for the certificate service, a mach lookup of the macOS trust service. It
  would let more tools work inside the sandbox. Not verified here: the service name and its
  effect on the profile were not tested.
- Exclude `go get` and `pnpm install` like the existing Go module commands. Chosen.

## Decision

- `go get` and `pnpm install` run outside the sandbox, bare and with arguments.
- The entries sit in `sandbox.excludedCommands` in `settings/claude.json`, in the shape of the
  existing pairs.
- No `allow` entry is added. The auto mode classifier already handles `go mod tidy` and
  `go mod download` the same way.
- Not excluded: `pnpm add`, `pnpm exec`, `pnpm dlx`, `npx`, `go install`, `go run` and
  `go generate`. They install a tool or run code of the agent's choice.
- The CI profile gets nothing. CI runs no package manager outside its own job steps.
- `rules/baseline.md` needs no edit. It forbids a language package manager for a tool. These
  commands raise repository dependencies.

## Consequences

- An excluded command sees the real environment and the whole filesystem, including the paths in
  `denyRead`. The same holds for the git network commands in ADR 0005.
- Lifecycle scripts of a pnpm dependency run with the rights of the user.
- Limits on that risk:
  - The repositories carry a lock file policy.
  - The repositories carry a release age floor for new package versions.
  - Tools come from `mise`. None of the excluded commands installs one.
  - Hooks still run before the command and still deny the shapes they deny.
- The risk is reduced, not removed. The owner accepted it on 24 November 2026 for
  `pnpm install`.
- The exclusion applies only when the command stands alone in the call, as in ADR 0005.
- The change is live after `task install` and a new session.
