# 0007 An installation is self contained

Status: accepted
Date: 2026-11-14

## Context

- Skills installed as symlinks into the source checkout. Hooks were never installed at all:
  `settings.json` carried each hook script's absolute path inside the checkout.
- Removing or moving the checkout left dangling skill links and hook paths pointing at
  nothing. Hooks then failed on every tool call.
- `rules/baseline.md` was already copied, not linked, and never had this problem.

## Decision

- Skills are copied into `claude_dir/skills` by default, reusing `install_skill`'s existing
  copy path and its `.agent-skills-checksum` tree hash marker.
- Hooks are copied into `claude_dir/.agent-skills-hooks`, one flat directory holding every
  top level `.py` file under `hooks/`, including the shared `_common` module. The settings
  hook commands point into that directory, not the checkout.
- `--link` stays as an opt-in escape hatch for skills, for a checkout under active edit that
  wants a live view without a reinstall per change. It costs nothing in `inspect_target`'s
  classification, which already tells a symlink from a copy regardless of which one a run
  asks for. Hooks have no such flag: they are always copied, since the whole point of this
  change is a settings file that still works once the checkout is gone. A plain `status` or
  `install` that passes no mode flag reads the mode the last install recorded instead of
  assuming `copy`, so a `status` right after `install --link` does not read 49 links as
  drift just because the installer's own default changed.
- `OWN_HOOK_MARKERS` gains a third fragment, `/.agent-skills-hooks/`, naming the installed
  copy, and the two existing fragments stay for a state file an older installer wrote. Naming
  alone cannot carry the rest: an install run from `.claude/worktrees/<branch>`, this
  repository's own mandated workflow, names neither "skills" nor "ai-setup", so the fragments
  never matched its commands in the first place. The state file's recorded `source`, read
  before this run overwrites it, is the real signal: a command is also ours when it names one
  of the current manifest's scripts and sits under that previous source, whatever it was
  named. The two signals combine on every hook block this installer may need to replace or
  strip: on an upgrade, in `strip_own_hooks` restoring a backup, and in `strip_own_hooks` on a
  plain uninstall.
- An upgrade from a linked skill to a copy needs no new case: `sync_skill` already replaces
  an `owned_link` entry whenever the requested mode is not `link`, so a plain `task install`
  after this change turns every existing link into a copy in one pass.
- `install_hooks_dir` never deletes a target it did not write. `inspect_hooks_dir` classifies
  `claude_dir/.agent-skills-hooks` the way `inspect_target` already classifies a skill entry:
  a symlink, a plain file, or a directory with no checksum marker is a conflict, reported and
  left alone, never handed to `shutil.rmtree`.
- `task doctor` reads the installation's state file and reports when the recorded source
  checkout no longer exists, instead of only failing the hook-compiles check that reads from
  it. It also compiles every hook script from the installed copy, not only from the source,
  and checks that every hook command already wired into `settings.json` still resolves to a
  real file on disk. Both keep that meaning when the source is gone and its manifest is
  empty: compiling the installed copy falls back to whatever the copy itself holds, and the
  wired-command check reads `settings.json`, never the manifest, so neither check goes
  trivially green just because there is nothing left to compare against.
- `hooks/stale_skills.py` needs no change. It already compares the commit recorded at
  install time against the checkout's current `HEAD`, and already says nothing when the
  checkout is not there. That comparison was already about the parts that were already
  copies, the rules file above all; it now covers skills and hooks the same way.

## Consequences

- A skill or hook edit in the checkout takes effect on the next `task install`, not
  immediately. `AGENTS.md` already documents reinstall as the flow, and `stale_skills.py`
  exists precisely to warn when that reinstall is overdue.
- Uninstall removes `claude_dir/.agent-skills-hooks` when it carries the checksum marker, the
  same ownership test an installed skill copy already uses, and leaves anything it did not
  write alone.
