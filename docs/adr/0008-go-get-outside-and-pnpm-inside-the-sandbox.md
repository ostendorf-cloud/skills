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
- Why `pnpm install` fails inside the sandbox is not verified. The pnpm store lock is known not
  to be writable there (see the fix-ci skill). A TLS failure like the one of `go get` is assumed
  but not shown.
- A review of the first draft of this change found that a plain `pnpm install` outside the
  sandbox is a sandbox escape in two steps:
  - It runs the root `preinstall`, `postinstall` and `prepare` scripts and `.pnpmfile.cjs` with
    the rights of the user. The agent can write those files inside the sandbox first.
  - `pnpm install *` accepts arguments: a package name, which acts like `pnpm add`,
    `--allow-build`, `--env-file` (it loads a file from `denyRead` into scripts),
    `--trust-lockfile`, `--registry`, `--npmrc-auth-file`, `--dir` and `-r`.

## Decision drivers

- An agent finishes a dependency change without a hand over.
- The commands that leave the sandbox stay few, named and exact.
- No excluded entry may run a script or a config file the agent wrote.

## Options considered

- Leave it and hand the commands to the owner. Safe, but it blocks the work each time.
- Add a sandbox rule for the certificate service, a mach lookup of the macOS trust service. It
  would let more tools work inside the sandbox. Not verified here: the service name and its
  effect on the profile were not tested.
- Exclude `pnpm install` with a `*` like the Go module commands. Rejected: see the review
  findings above.
- Exclude `go get` with a `*` and `pnpm install` as two exact strings. Chosen.

## Decision

- `go get` and `go get *` run outside the sandbox, like `go mod tidy` and `go mod download`.
- Exactly two `pnpm install` strings run outside the sandbox, each without a `*`:
  - `pnpm install --frozen-lockfile --ignore-scripts --ignore-pnpmfile`
  - `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile`
- An entry without `*` matches only that string, as `git fetch` differs from `git fetch *`. This
  is the documented meaning of the pair, not measured here.
- Probe with pnpm 12.18.0 in a scratch directory, offline, with a `package.json` whose
  `preinstall`, `postinstall` and `prepare` write marker files and a `.pnpmfile.cjs` that writes
  one too:
  - `--lockfile-only --ignore-scripts --ignore-pnpmfile` wrote no marker.
  - `--frozen-lockfile --ignore-scripts --ignore-pnpmfile` wrote no marker.
  - `--lockfile-only` without the two ignore flags loaded the pnpmfile and wrote its marker.
  - `--dir` is accepted, but it changes the string, so the exact entry no longer matches.
- Not excluded: `pnpm install` in any other form, `pnpm add`, `pnpm exec`, `pnpm dlx`, `npx`,
  `go install`, `go run` and `go generate`.
- No `allow` entry is added. The auto mode classifier decides on a standalone call, as it does
  for `go mod tidy`. That means no human gate on such a call. Which way the classifier decides
  is not verified.
- The CI profile gets nothing. CI runs no package manager outside its own job steps.
- `rules/baseline.md` needs no edit. It forbids a language package manager for a tool. These
  commands raise repository dependencies.
- The `git-guard` hook denies `go get` and the two exact forms when they do not stand alone:
  chained, piped, behind `cd`, with an env prefix, a redirection or an option before the
  subcommand. The deny names the standalone form. Any other `pnpm install` gets context only,
  because it still works inside the sandbox. A deny there would block legitimate use.

## Consequences

- An excluded command sees the real environment and the whole filesystem, including the paths in
  `denyRead`. The same holds for the git network commands in ADR 0005.
- What the two pnpm forms close: root scripts, the pnpmfile, package arguments and every flag
  that is not in the string.
- What they do not close:
  - A lock file entry the agent wrote still installs from the registry. The lock file policy of
    a repository and review of the diff are the control, not the sandbox.
  - `--ignore-scripts` skips build scripts. A build such as the esbuild postinstall must run
    inside the sandbox with `pnpm rebuild`.
- What `go get` can do: fetch modules, edit `go.mod` and `go.sum` and check them against the
  checksum database. It also takes `-tool` and `toolchain@version`. A tool added through
  `go get -tool` or a switch of the Go toolchain is a residual risk. The rule that tools come
  from `mise` is held by the agent, not by this setting.
- Repository policies differ and are no general limit. `ostendorf.tech/web/pnpm-workspace.yaml`
  holds only overrides and relies on pnpm 12 defaults. govue pins pnpm 10 and sets
  `onlyBuiltDependencies: ["esbuild"]` without `minimumReleaseAge`. A release age floor is not
  assumed anywhere.
- Standalone only: ADR 0005 measured that a git command leaves the sandbox only when it stands
  alone. For `go get` and `pnpm install` this is expected, not measured. The hook denies the
  chained shapes so that a call fails early with a clear reason instead of a TLS error.
- The change is live after `task install` and a new session.
