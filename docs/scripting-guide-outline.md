# Outline for skills/fivem-scripting (the rulebook)

Audience: Claude, writing FiveM resources for Liam. Tone: terse, imperative, example-driven. Every rule
must be actionable and, where it comes from the runtime/source, cite `reference/runtime-facts.md`.

## SKILL.md (≤ 350 lines; loaded into context on every FiveM task, so dense)

Front matter: name `fivem-scripting`, description that triggers on: FiveM, Cfx, FXServer, fxmanifest, resource,
script, native, ESX, QBCore, qbox, ox_lib, txAdmin, "GTA V server", client/server event, state bag, OneSync, resmon.

1. Workflow (the 90 % loop): understand → `fxref` every native (never from memory) → plan files → write → `fxlint` →
   self-review against checklist → `fxserver deploy` + `restart` → hand over an in-game test checklist → read `fxserver logs --errors` after the test.
2. Project defaults (read `config.json`: language, lua54, framework, ox_lib, workspace). Standalone unless configured.
3. Resource anatomy: fxmanifest (canonical block), folders, `shared/config.lua`, naming, exports, versioning.
4. Threads & performance — the resmon rules with idiomatic snippets: no busy loops; per-frame only while needed
   (start/stop pattern); adaptive Wait; event/statebag/keymapping instead of polling; cache PlayerPedId; batching;
   distance checks with `#(a-b)`; `lib.points`/`lib.zones` if ox_lib; timers vs threads; `SetTimeout` for one-shots;
   avoid per-frame natives that are expensive (list); NUI messaging throttling; string/table allocation in hot loops.
5. Events & security — server-authoritative model; the validated-handler template (source, type/range checks,
   distance, permission/ACE, cooldown, rate limits numbers); never trust client ids/prices/amounts/handles;
   RegisterNetEvent only for network-reachable events; `TriggerClientEvent(-1)` sparingly; latent events for big data;
   callbacks (ox_lib `lib.callback` or minimal own implementation in `patterns/callback.lua`); commands with ACE;
   anti-cheat hygiene (server creates money/items/vehicles, `sv_entityLockdown`/`sv_filterRequestControl` awareness,
   entity creation on server with `CreateVehicleServerSetter`, ownership checks `NetworkGetEntityOwner`, routing buckets).
6. State bags & sync — when to use GlobalState / Entity state / Player state vs events; replicated flag; change handlers;
   limits; entity state for vehicles (locks, fuel), player state for jobs; `LocalPlayer.state`.
7. OneSync & entities — server-side creation, `DoesEntityExist`, netIds vs handles, migration, culling radius,
   `SetEntityDistanceCullingRadius`, `SetEntityOrphanMode`, deleting entities safely, spawn/despawn hygiene, model loading (`RequestModel` + wait + `SetModelAsNoLongerNeeded`).
8. Client patterns — key mappings (`RegisterKeyMapping` + `RegisterCommand` with `+`/`-`), interaction loops
   (start on enter zone, stop on exit), markers/text-UI, model/anim loading, NUI (focus, callbacks, message throttle),
   `onClientResourceStart` guards, cleanup in `onResourceStop`.
9. Server patterns — player lifecycle (`playerConnecting` deferrals, `playerJoining`, `playerDropped`), persistence
   (KVP for small data; `oxmysql` if present — parametrized queries only), HTTP (`PerformHttpRequest`), scheduling,
   per-player cooldown table, logging.
10. Framework adapters — standalone (default), ESX, QBCore, qbox, ox_core: how to get player/identifier/money/item
    and where NOT to reimplement; detect from `config.json` or from the server's resources folder.
11. Lua 5.4 style & idioms — locals, vector types, `#(a-b)`, `RegisterNetEvent(name, fn)`, `CreateThread`, string
    formatting, tables, `json`, `msgpack`, integer division, `<const>`, error handling (`pcall` around exports), no globals.
12. JS/TS notes (short) — when Liam picks JS: `on`/`onNet`/`emitNet`, arrays for vectors, `setTick` rules, `Delay`, typings.
13. Testing hand-off — what to put in the in-game checklist; how to read `fxserver logs --errors`; `resmon 1` expectations;
    `profiler record`; common runtime errors and their meaning.
14. Review checklist (the same list `fivem-reviewer` uses; ~25 checkboxes).

## reference/ (loaded on demand; each ≤ 250 lines)

- `runtime-facts.md` (from the source, with citations) — already being written.
- `manifest.md` — fxmanifest keys + canonical examples (lua, js, nui, map).
- `events.md` — core events with args, `CancelEvent`, deferrals.
- `security-checklist.md` — the reviewer's checklist in full, with bad → good examples.
- `performance-cookbook.md` — 10 before/after snippets (busy loop → adaptive; polling key → keymapping; per-frame
  distance to all players → statebag/zones; broadcast storm → targeted; string concat; pool scans; etc.).
- `frameworks.md` — adapter snippets for ESX / QBCore / qbox / ox_core / standalone (player object, identifier, money,
  items, notifications, callbacks), and how to detect which one is installed.
- `lint-rules.md` — copy of docs/fxlint.md rule table (or link).

## patterns/ (copy-paste-ready, must pass fxlint clean)

- `patterns/callback.lua` — minimal client/server callback implementation (standalone; ox_lib alternative noted).
- `patterns/validated-event.lua` — server handler template with all checks + cooldown helper.
- `patterns/interaction-zone.lua` — enter/exit driven per-frame loop (adaptive wait), text UI, key press.
- `patterns/keymapping.lua` — RegisterKeyMapping + command pair.
- `patterns/server-vehicle.lua` — server-side vehicle creation, ownership, entity state (locked, plate), cleanup.
- `patterns/statebag-sync.lua` — entity/player state bag with change handler client-side.
- `patterns/player-lifecycle.lua` — playerConnecting deferrals, joining, dropped, cleanup table.
- `patterns/nui-bridge.lua` + `patterns/nui/index.html|script.js` — focus, callbacks, messages.
- `patterns/model-loading.lua` — request/wait/release helpers with timeouts.
- `patterns/resource-lifecycle.lua` — onResourceStart/Stop guards, cleanup of created entities/blips/threads.

## templates/

- `fxmanifest.lua` canonical (lua), `fxmanifest.js.lua`, `README.md` template with test checklist (used by fxnew).
