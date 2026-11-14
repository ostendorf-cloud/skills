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
  copy path and its `.agent-skills-checksum` tree hash marker. `settings/claude.json` denies
  `Edit({{claude_dir}}/skills/**)` the way it already denies the installed hooks copy: while
  skills were symlinks, an edit through the installed path landed in the checkout, which
  `AGENTS.md` sanctions; against a copy that same edit is forbidden, and the next install
  would silently discard it besides.
- Hooks are copied into `claude_dir/.agent-skills-hooks`, one flat directory holding every
  top level `.py` file under `hooks/`, including the shared `_common` module. The settings
  hook commands point into that directory, not the checkout.
- `--link` stays as an opt-in escape hatch for skills, for a checkout under active edit that
  wants a live view without a reinstall per change. It costs nothing in `inspect_target`'s
  classification, which already tells a symlink from a copy regardless of which one a run
  asks for. Hooks have no such flag: they are always copied, since the whole point of this
  change is a settings file that still works once the checkout is gone. `install` keeps
  defaulting to `copy` on every run regardless of what was recorded, since that default is
  exactly what turns an existing link into a copy on a plain `task install`, the upgrade path
  the next bullet relies on. `status`, which only reports and never installs anything, reads
  the mode the last install recorded instead of assuming `copy`, so a `status` right after
  `install --link` does not read every linked skill as drift just because the installer's own
  default changed.
- `OWN_HOOK_MARKERS` gains a third fragment, `/.agent-skills-hooks/`, naming the installed
  copy, and the two existing fragments stay for a state file an older installer wrote. Naming
  alone cannot carry the rest: an install run from `.claude/worktrees/<branch>`, this
  repository's own mandated workflow, names neither "skills" nor "ai-setup", so the fragments
  never matched its commands in the first place. The real signal is the manifest script's own
  basename, gated on where it sits: every command this installer has ever written has the
  shape `python3 "<dir>/<script>"` with `<dir>` named either `hooks` (a checkout) or
  `.agent-skills-hooks` (an installed copy), so matching the basename inside one of exactly
  those two directory names recognises a command from any previous source, a machine that
  installed from several differently named checkouts over time included, not only the one the
  state file's recorded `source` last named. The directory name gate is load bearing, not
  decoration: several of the manifest's own script names, `git_guard.py` or
  `commit_message.py` say, are exactly what an unrelated hook could be called, and a basename
  match with no such gate would strip a foreign hook on sight, on install, and again on
  uninstall with no backup left to recover it the second time, since an installation that
  already exists is never mistaken for the user's original file. That recorded `source`, read
  before this run overwrites it, stays as a second signal, already narrow since it requires
  the one previously recorded directory: a command sitting under it is also ours even when its
  script is no longer in the current manifest, or sits in neither of the two directory names,
  which the basename test alone would miss. Both signals apply to every hook block this
  installer may need to replace or strip: on an upgrade, in `strip_own_hooks` restoring a
  backup, and in `strip_own_hooks` on a plain uninstall.
- `args.claude_dir` is made absolute with `os.path.abspath` before anything else reads it,
  lexical and so never following a symlink the way `build_hook_blocks` deliberately does not
  either. A relative `--claude-dir` used to reach the wired command and the deny rule
  unresolved, correct only for a session whose working directory happened to still be the one
  it was typed in, and a `..` segment produced a command that still worked by accident while
  the deny rule, built by a path comparison, could not match a real path at all. The state
  file already recorded the fully resolved directory regardless, so the two used to disagree.
- `build_hook_blocks` joins `claude_dir` and `OWN_HOOKS_DIRNAME` without resolving the result,
  and every other place that names the installed hooks directory, `doctor`'s broken-command
  check and `install_hooks_dir` included, spells it the same unresolved way. Resolving would
  follow a symlinked hooks directory, or a symlinked `claude_dir`, a common dotfiles layout,
  to wherever it actually points: the settings would then reference a path outside the install
  directory that no marker and no broken-command check recognises as this installer's own.
  A hooks conflict stops `install` before `settings.json` or the state file are written at
  all, for the same reason: a command built against a directory `install_hooks_dir` refused to
  populate points nowhere, and writing it, or a state file claiming a clean install, would
  make the installation inconsistent rather than loudly incomplete.
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
- Known limit, not fixed here: a retired hook, one that was alone in its event and matcher
  block and was written by a generation older than the one the state file currently records,
  survives both an upgrade and an uninstall. Neither signal in `block_is_own` finds it: its
  script is no longer in the manifest, so the basename test has nothing to match, and it sits
  under a source from before the one `source` currently names, so the second signal misses it
  too. `doctor`'s broken-command check stays green regardless, since it only inspects commands
  that already point into the installed hooks directory, this one does not. The exposure is
  one leftover handler, not the fifteen a single recorded source used to leave behind, which
  is the defect this change set out to close.
