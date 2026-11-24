# 0008 Run go get outside the sandbox and make pnpm work inside

Status: accepted
Date: 2026-11-24

## Context

- Inside the sandbox `go get` fails the TLS check with `x509: OSStatus`. The sandbox blocks the
  macOS certificate service, although `sandbox.network.allowedDomains` already allows every host.
- A session cannot raise a Go dependency. It hands each change to the owner as a command to run.
  This blocks the work at every govue release and every Renovate follow up.
- `go mod download` and `go mod tidy` already run outside the sandbox through
  `sandbox.excludedCommands`. `go get` was missing.
- `pnpm install` was first planned as an excluded command too. Review of that plan showed it is
  not safe, see the options below.
- The cause of the pnpm failure is not TLS. Measured with pnpm 12.18.0 in the sandbox, the
  registry, the lock file and a git hosted dependency all work. The first failure is a write
  to the store and state paths under `~/Library/pnpm`, which the sandbox cannot write. In a
  project outside the sandbox write scope, the store falls back to a path next to the project,
  which is not writable either.

## Decision drivers

- An agent finishes a dependency change without a hand over.
- A command that leaves the sandbox must not be steerable by files the agent wrote.
- A store shared with the owner's own projects must not take content from the sandbox.

## Options considered

- Leave it and hand the commands to the owner. Safe, but it blocks the work each time.
- A sandbox rule for the certificate service, a mach lookup of the macOS trust service. It
  would let more tools work inside the sandbox. Not verified here: the service name and its
  effect on the profile were not tested.
- Exclude `pnpm install` with or without `*`. Rejected. A review ran three probes against even
  the narrowest form, `pnpm install --frozen-lockfile --ignore-scripts --ignore-pnpmfile`, and
  no flag set closes them:
  - A `pnpm-workspace.yaml` with `modulesDir: ../outside/target` writes `node_modules` to a path
    outside the sandbox.
  - A `file:../secret` dependency hardlinks files into the repository.
  - A `packageManager: pnpm@9.15.9` field makes pnpm 12 download and run pnpm 9, which sent
    `Bearer ${ENV}` to a registry the agent chose.
- Exclude `go get` and let pnpm write its store and state under `~/.cache`, which the sandbox
  already allows. Chosen.
- Allow writes to `~/Library/pnpm` instead. Rejected: see the store consideration below.

## Decision

- `go get` and `go get *` run outside the sandbox, like `go mod tidy` and `go mod download`.
- pnpm stays inside the sandbox. The `env` block of `settings/claude.json` sets
  `pnpm_config_store_dir` to `~/.cache/pnpm/store`. pnpm expands the `~` itself, measured with
  `pnpm store path`. Whether Claude Code expands `~` in `env` values is not verified, so the
  value relies on pnpm doing it.
- Measured with that variable alone, in a scratch directory, in the sandbox:
  - `pnpm install` of a project with `is-odd` succeeds.
  - `pnpm install --frozen-lockfile` from the resulting lock file succeeds.
  - A project with `ostendorf-cloud/govue#v0.9.0&path:/web`, a GitHub codeload download,
    installs 51 packages.
  - The pnpm cache under `~/Library/Caches/pnpm` is read only, and the install still works. A
    value for `pnpm_config_cache_dir` with `~` was not expanded by pnpm 12.18.0 and created a
    directory named `~` in the project, so it is not set.
  - A `packageManager` field that differs from the running pnpm makes pnpm start a download of
    the other version. That path failed here with `ENOTFOUND` for `registry.npmjs.org`. It was
    not investigated. It is not the normal case when the pinned pnpm version matches.
- No `allow` entry is added. The auto mode classifier decides on a standalone call, as it does
  for `go mod tidy`. That means no human gate on such a call. Which way the classifier decides
  is not verified.
- Whether an entry without `*` matches only that string is not verified. No exact pnpm entry
  is used in the end.
- The CI profile gets nothing. CI runs no package manager outside its own job steps.
- `rules/baseline.md` needs no edit. It forbids a language package manager for a tool. These
  commands raise repository dependencies.
- The `git-guard` hook denies `go get` when it does not stand alone: chained, piped, behind `cd`,
  with an env prefix or an option before the subcommand. The deny names the standalone form.
  This is an early stop for a clear message, not a security control. The hook says nothing about
  pnpm.

## Consequences

- An excluded command sees the real environment and the whole filesystem, including the paths in
  `denyRead`. The same holds for the git network commands in ADR 0005.
- What `go get` can do: fetch modules, edit `go.mod` and `go.sum`, and check them against the
  checksum database. It builds nothing and runs no module code.
- Residual risks of `go get`:
  - `go get -tool` adds a tool dependency, and `go get toolchain@version` switches the Go
    toolchain. The rule that tools come from `mise` is held by the agent, not by this setting.
  - A direct fetch from a version control host runs git on a URL the agent chose, for example
    through `GOFLAGS`, `GOPROXY=direct` or a `replace` directive in a `go.mod` the agent wrote.
- Store consideration for pnpm: a separate store under `~/.cache/pnpm/store` keeps the sandbox
  away from the stores of the owner's own projects. A store shared through `~/Library/pnpm`
  would let an agent poison content that later projects outside the sandbox link to.
- The cost of a separate store: a first install downloads again, and pnpm links the files with
  hardlinks, so a project must sit on the same volume as `~/.cache`.
- The standalone only behaviour was measured for git in ADR 0005. For `go get` it is expected,
  not measured.
- The change is live after `task install` and a new session.
