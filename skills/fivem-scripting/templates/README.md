# {{resource_name}}

{{one-line description of what this resource does}}

## Requirements

- FXServer, game build {{build}} or newer
- Framework: {{standalone | ESX | QBCore | qbox | ox_core}}
- Dependencies: {{list any, e.g. ox_lib, oxmysql -- or "none"}}

## Installation

1. Copy this folder into your server's resources directory.
2. Add `ensure {{resource_name}}` to `server.cfg` (after its dependencies, if any).
3. Adjust `shared/config.lua` to taste.
4. `refresh` then `start {{resource_name}}` (or restart the server).

## Configuration

Edit `shared/config.lua`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `Config.Debug` | boolean | `false` | extra console logging |
| `{{...}}` | | | |

## Exports

`{{none -- delete this section if there are none}}`

```lua
exports['{{resource_name}}']:{{exportName}}({{args}})
```

## In-game test checklist

Run every one of these against a live server (`fxserver deploy` + `restart`,
then `fxserver logs --errors` after) before calling this resource done.
Normal-path checks first, then the abuse cases -- a resource that only works
when used correctly isn't finished.

### Normal path

- [ ] Resource starts with no errors: `fxserver logs --errors --resource {{resource_name}}`
- [ ] `resmon 1` shows ~0.00-0.02 ms idle for this resource, < 0.10 ms while actively used
- [ ] Every client-visible feature works as intended for one player
- [ ] Restarting the resource (`restart {{resource_name}}`) leaves no duplicated
      blips/entities/NUI state behind, and no "attempt to call a nil value" on
      the next start
- [ ] Stopping the resource removes everything it created (blips, entities,
      NUI focus) -- check nothing is left behind in the world or on screen

### Abuse cases

- [ ] **Key/command spam** -- hold or mash the bound key / spam the command
      as fast as possible; the debounce/cooldown holds and the server never
      logs more than the expected rate (watch `resmon`/server console for a
      flood of triggers)
- [ ] **Second client triggering the same event** -- with two clients
      connected, have client B trigger an event/command meant for (or
      currently "owned" by) client A's session/entity; confirm the server
      rejects or ignores it instead of acting on client A's behalf
- [ ] **Disconnect mid-action** -- start a multi-step interaction (an open
      NUI, a pending callback, a cooldown-gated action) and disconnect the
      client before it finishes; confirm the server doesn't error and cleans
      up that player's entries in any per-player table (`playerDropped`)
- [ ] **Invalid payloads** -- trigger each server net event with wrong types,
      out-of-range numbers, empty strings, and (if reachable, e.g. via a dev
      console `TriggerServerEvent` call) missing arguments; confirm every
      handler rejects with a logged reason instead of erroring or acting on
      the bad data
- [ ] **Distance/permission bypass attempt** -- trigger a server event that
      should require proximity/ownership/ACE from far away or without the
      permission; confirm it's rejected
- [ ] **Two players racing the same action** -- both clients trigger the same
      one-shot server action (buy the last item, claim the same vehicle) at
      the same time; confirm only one succeeds, not both

## Known limitations

`{{...}}`
