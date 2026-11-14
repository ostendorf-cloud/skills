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
  change is a settings file that still works once the checkout is gone.
- `OWN_HOOK_MARKERS` gains a third fragment, `/.agent-skills-hooks/`, naming the installed
  copy. The two existing fragments, pointing into a checkout, stay so an older installation's
  hook blocks are still recognised as ours and get replaced on upgrade rather than kept
  as a foreign block or orphaned.
- An upgrade from a linked skill to a copy needs no new case: `sync_skill` already replaces
  an `owned_link` entry whenever the requested mode is not `link`, so a plain `task install`
  after this change turns every existing link into a copy in one pass.
- `task doctor` reads the installation's state file and reports when the recorded source
  checkout no longer exists, instead of only failing the hook-compiles check that reads from
  it. The settings and hook checks read the installed copy, so they keep passing once the
  source is gone, which is the point of the change.
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
