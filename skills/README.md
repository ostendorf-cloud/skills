# Skills

One directory per skill under its category. The category is navigation, the skill name is global.

## Reading the config

Every skill that reads `.agent-skills.json` uses this snippet. `jq` is required and listed as an install requirement.

```sh
root=$(git rev-parse --show-toplevel 2>/dev/null) || root=.
config="$root/.agent-skills.json"
[ -f "$config" ] && cfg=$(cat "$config") || cfg='{}'
value=$(printf '%s' "$cfg" | jq -r '.work.branch // empty'); [ -n "$value" ] || value=worktree
```

- A key may be `false`. Test for it with `jq -r '.work | select(. != null) | tostring'` before reading subkeys.
- Defaults are the ones in `agent-skills.schema.json`. A skill states the default it uses.
- `CI=true` means unattended. Skills then never ask and record questions on the issue.

## Label defaults

| Key | Default |
|---|---|
| ready | `ai: ready` |
| working | `ai: working` |
| reviewRequested | `ai: review requested` |
| reviewing | `ai: reviewing` |
| changesRequested | `ai: changes requested` |
| needsHuman | `ai: needs human` |
| done | `ai: done` |
| blocked | `ai: blocked` |
| needsTriage | `needs triage` |
| dependencies | `dependencies` |

A label missing on the tracker is reported. Skills never create labels, infrastructure code does.
