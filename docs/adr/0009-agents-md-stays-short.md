# 0009 Keep AGENTS.md short with a nested file, docs and a shared check

Status: accepted
Date: 2026-11-26

## Context

- The root `AGENTS.md` loads in full into every session and every subagent in a repository.
- Measured on 2026-11-26: four repositories carry 247 to 501 lines, thirteen carry 40 to 173.
- The vendor guidance is under 200 lines per file.
- An audit of the four large files found little repetition of the baseline. Most lines matter
  under one directory only.
- No existing tool counts lines of a Markdown file, and `conftest` has no Markdown parser.
- Issue 260 in the skills repository tracks the work.

## Decision drivers

- Every line in the root file is paid for in every request.
- One check definition for CI and local runs.
- A shared interface must not break callers silently.

## Options considered

- Keep one large root file and trust authors. Rejected: the measured files grew to 501 lines.
- A hard limit with no place for the overflow. Rejected: the knowledge has to go somewhere.
- A nested `AGENTS.md` next to a `CLAUDE.md` holding `@AGENTS.md`, plus `docs/` for background.
  Chosen.
- A bespoke check script per repository. Rejected: it drifts, see `conformance-checks`.
- A reusable workflow alone. Rejected as the only form: a local run would use another
  definition than CI.
- A shared Taskfile in the shared workflows repository, included by each repository. Chosen.

## Decision

- The root `AGENTS.md` is limited to 150 lines and a nested one to 100 lines.
- Directory knowledge goes to a nested `AGENTS.md`. Background and history go to `docs/` with a
  one line pointer.
- The check warns first in repositories above the limit. It turns to fail after their own
  issues land.
- The check is the task `lint:agents-md`, defined once in the shared workflows repository
  (issue 95 there).
- The shared task takes its settings from CLI variables and environment, not from `vars` on the
  include.
- The skill `agents-md` states the rules.

## Probe results

Both probes ran on 2026-11-26 in empty directories outside every repository. Versions: Claude
Code 2.1.311, Task 3.54.0.

- Verified in one run: a nested `CLAUDE.md` loads on demand. A fresh headless session reported
  the root marker only. After it read a file below `sub/`, it reported both markers. The answer
  is the model's own report of its context.
- Verified: a remote Taskfile include over HTTPS lists the remote tasks. The URL was
  `https://github.com/ostendorf-cloud/workflows.git//Taskfile.yaml?ref=v0.8.0`.
- Verified: without a terminal and without `--yes` or `--trusted-hosts`, a first run fails with
  exit code 104 and `not trusted by user`. With `--yes` it runs.
- Verified: a wrong `checksum:` stops the run and prints the real checksum.
- Not verified: `--trusted-hosts github.com` on a fresh project. The run reused trust cached in
  the project folder.
- Not verified: whether `vars` on a remote include reach the remote tasks. The remote Taskfile
  used no variable.
- The `git::` and `file://` URL forms are not treated as remote by Task. The SSH form was not
  tested.

## Consequences

- The root file carries only what almost every task needs. Sessions load fewer tokens.
- Content moves into nested files and `docs/`, so a reader must find it by directory or pointer.
- A nested file loads only once a file below its directory is read. The result rests on one run.
- A remote Taskfile is shared code fetched at run time. It stays pinned by tag and checksum.
- CI must pass `--yes` or `--trusted-hosts`. A local run needs one trust answer per project.
- The shared task is a shared interface. A later input change breaks callers.
- Warn mode hides the large files until their own issues land. The check must turn hard after.
- `scripts/validate.py` now scans nested `AGENTS.md` files for forbidden characters.
- Wiring the check into the skills repository waits for the workflows release.
