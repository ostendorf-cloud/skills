# Skills

One directory per skill under its category. The category is navigation, the skill name is global.

`task install` copies this file to `~/.claude/skills/README.md`. Skills cite it by that path,
and `validate` rejects a skill that cites a path the installer does not provide.

## Reading the config

Every skill that reads `.agent-skills.json` uses this snippet. `jq` is required and listed as an
install requirement.

```sh
root=$(git rev-parse --show-toplevel 2>/dev/null) || root=.
config="$root/.agent-skills.json"
[ -f "$config" ] && cfg=$(cat "$config") || cfg='{}'
value=$(printf '%s' "$cfg" | jq -r '.work.branch // empty'); [ -n "$value" ] || value=worktree
```

- A key may be `false`. Test for it with `jq -r '.work | select(. != null) | tostring'` before
  reading subkeys.
- Defaults are the ones in `agent-skills.schema.json`. A skill states the default it uses.
- `CI=true` means unattended. Skills then never ask and record questions on the issue.

## Label defaults

| Key              | Default                 |
| ---------------- | ----------------------- |
| ready            | `ai: ready`             |
| working          | `ai: working`           |
| reviewRequested  | `ai: review requested`  |
| reviewing        | `ai: reviewing`         |
| changesRequested | `ai: changes requested` |
| needsHuman       | `ai: needs human`       |
| done             | `ai: done`              |
| blocked          | `ai: blocked`           |
| needsTriage      | `needs triage`          |
| dependencies     | `dependencies`          |
| story            | `story`                 |

A label missing on the tracker is reported. Skills never create labels, infrastructure code does.

## Moving the state label

Moving the state means exactly one `ai:` state label remains afterwards. This snippet reads the
eight state labels named in `defaults` below, with the config's override, and prints one
complete `gh issue edit` command: one `--add-label` for the new state and one `--remove-label`
per other state label, quoted with jq's `@sh`. A disabled or unknown target state aborts instead
of printing a command that would remove every state label. The snippet never runs `gh` itself.
Run the printed command as it is, then list the labels with `gh issue view <number> --json
labels --jq '.labels[].name'` to confirm the result. That way the literal `gh issue edit
--add-label ...` text is what the CI profile's prefix rule in `settings/claude-ci.json` sees,
not a shell expansion. On a pull request, swap `gh issue edit` for `gh pr edit`, and
`gh issue view` for `gh pr view`.

```sh
defaults='{"ready":"ai: ready","working":"ai: working","reviewRequested":"ai: review requested","reviewing":"ai: reviewing","changesRequested":"ai: changes requested","needsHuman":"ai: needs human","done":"ai: done","blocked":"ai: blocked"}'
new=working        # the target state's config key
number="<number>"  # the issue or pull request number
result=$(jq -n --argjson d "$defaults" --argjson c "$cfg" --arg new "$new" --arg number "$number" '
  ($d * (($c.labels // {}) | with_entries(select(.key | in($d))))) as $l
  | ($l[$new] // false) as $target
  | if $target == false then {target: false, line: ""} else
      {target: $target, line: (
        "gh issue edit --add-label \($target|@sh)"
        + ([$l | to_entries[] | select(.key != $new and .value != false) | " --remove-label \(.value|@sh)"] | join(""))
        + " \($number|@sh)"
      )}
    end
')
target=$(printf '%s' "$result" | jq -r '.target')
if [ "$target" = "false" ]; then
  echo "no label configured for state \"$new\", move aborted" >&2
else
  printf '%s' "$result" | jq -r '.line'
fi
```

- `cfg` comes from the config snippet above. `defaults` names the eight state keys explicitly,
  so `needsTriage` and `dependencies` never enter the merge and are never removed by this
  snippet.
- A state disabled with `false`, or a `new` key that is not one of the eight, makes `target`
  `false` and aborts instead of printing a command that removes every state label.
- Pure POSIX: `sh`, `bash` and `zsh` all run it unchanged.
