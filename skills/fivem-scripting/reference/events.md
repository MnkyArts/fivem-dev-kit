# Events reference

## RegisterNetEvent vs AddEventHandler

- `AddEventHandler(name, handler)` registers a handler for `name` and makes
  this resource receive that event -- but **only local/same-side triggers**
  reach it. An event arriving from the network (`source` starting with
  `"net"`) is dropped, untraced, unless it was separately marked "safe for
  net" (runtime-facts §2).
- `RegisterNetEvent(name[, handler])` marks `name` safe for net **and**, in
  the two-argument form, registers `handler` via `AddEventHandler` in the
  same call -- this is the form every pattern in this skill uses
  (`RegisterNetEvent('my:event', function(...) ... end)`). On the server,
  `RegisterServerEvent` is a plain alias of `RegisterNetEvent`
  (runtime-facts §2).
- Rule of thumb: **`RegisterNetEvent` only for events a `TriggerServerEvent`/
  `TriggerClientEvent`/`emitNet` call actually needs to reach.** A purely
  internal event (fired and handled on the same side, same resource) should
  stay a plain `AddEventHandler`/`TriggerEvent` pair -- marking it net-safe
  needlessly is exactly what `fxlint` rule S004 flags.
- `AddEventHandler` without a matching `RegisterNetEvent` for an event that's
  actually triggered from the other side across the network silently never
  fires (no error, just never invoked) -- `fxlint` rule C006.

## `source` -- capture it immediately

Event dispatch sets a per-invocation `source` global and resets it right
after starting the handler's coroutine, without waiting for the handler to
finish (runtime-facts §2/§15). If a handler `Wait()`s before reading `source`,
it may see a **different**, already-changed value. Every server net-event
handler in this skill starts with:

```lua
RegisterNetEvent('my:event', function(...)
    local src = source -- must be the first line, before any Wait/Await
    ...
end)
```

## Event naming convention

`resource:side:action`, e.g. `myres:server:buyItem`, `myres:client:itemBought`.
`side` names **who receives it** (a `:server:` event is triggered by a client
and handled on the server), not who sends it. Keeps event names collision-free
across resources and makes `fxlint`'s cross-file checks (S004/S007/C006)
meaningful.

## `CancelEvent()`

`CancelEvent()` (apiset `shared`) cancels the currently-executing event, but
**does not stop other handlers for the same event from running** -- every
registered handler still executes; cancellation only sets a flag the
*triggering* code can check (runtime-facts §2/§9). `WasEventCanceled()` only
reflects **locally** triggered events, never ones received over the network
(runtime-facts §2).

Whether cancellation matters at all depends on the event: for
`entityCreating` it's load-bearing (a canceled create is actually rolled
back); for the `...ed`/post-action sibling `entityCreated` it does nothing
(already queued, entity already exists) (runtime-facts §9/§15). General rule:
**to veto something, hook the `...ing` event, not the `...ed` one.**

## Deferrals (`playerConnecting`)

```lua
AddEventHandler('playerConnecting', function(playerName, setKickReason, deferrals)
    local src = source
    deferrals.defer()
    Wait(0) -- required: at least one tick between defer() and update()/done()
    deferrals.update('Checking allowlist...')
    if not allowed(src) then
        return deferrals.done('You are not allowlisted.')
    end
    deferrals.done()
end)
```

- `deferrals.defer()` must be called, then **at least one tick must pass**
  before `update`/`presentCard`/`done` (runtime-facts §9).
- `deferrals.update(message)` -- progress text shown to the connecting client.
- `deferrals.presentCard(card, cb?)` -- sends an Adaptive Card; `cb` fires on
  `Action.Submit`.
- `deferrals.done(failureReason?)` -- finalizes; a reason refuses the
  connection and the client sees it, no reason lets them in.
- Without `deferrals.defer()` at all, rejection must be synchronous:
  `CancelEvent()` + `setKickReason(msg)`, no `Wait()` possible
  (runtime-facts §9). Use deferrals whenever the check needs to `Wait`/await
  anything (a DB lookup, an HTTP call).

See `patterns/player-lifecycle.lua` for the full connecting/joining/dropped
shape.

## Core events (side, args)

| Event | Side | Args | Notes |
|---|---|---|---|
| `onResourceStarting` | both | `resourceName` | cancelable -- cancel prevents the start |
| `onResourceStart` | both | `resourceName` | fires for **every** resource; guard with `if GetCurrentResourceName() ~= resourceName then return end` |
| `onResourceStop` | both | `resourceName` | same guard; must clean up **synchronously**, no `Wait` |
| `onClientResourceStart` | client | `resourceName` | client-side mirror of a resource starting; same guard |
| `onClientResourceStop` | client | `resourceName` | same guard |
| `playerConnecting` | server | `playerName, setKickReason, deferrals` | `source` is a temporary id here; see Deferrals above |
| `playerJoining` | server | (none reliable -- read ambient `source`) | fires once `source` is the final, stable server id |
| `playerDropped` | server | `reason, resourceName, clientDropReason` | `source` is the disconnecting player -- clean up per-player tables here |
| `entityCreating` | server | `handle` | cancelable -- cancel deletes the just-created clone (OneSync) |
| `entityCreated` | server | `handle` | fired via `QueueEvent2`, **not** cancelable in practice |
| `entityRemoved` | server | `entity` | |
| `onEntityBucketChange` | server | `entity, bucket, oldBucket` | |
| `onPlayerBucketChange` | server | `player, bucket, oldBucket` | |
| `gameEventTriggered` | both | `name, args[]` | low-level GTA game events |
| `populationPedCreating` | client | `posX, posY, posZ, model, setters` | cancelable; `setters.setModel/setPosition` override the spawn |

Several event families a lot of scripts depend on (`weaponDamageEvent`,
`explosionEvent`, `fireEvent`, `ptFxEvent`, `startProjectileEvent`,
`giveWeaponEvent`, `removeWeaponEvent`, `removeAllWeaponsEvent`,
`clearPedTasksEvent`) are OneSync "parsed game events" documented only as
C++ comments, not on docs.fivem.net -- all server-side, signature
`(sender: number, data: table)` (runtime-facts §9). `weaponDamageEvent`
specifically **can be canceled** to block the damage.

## `TriggerClientEvent(name, playerId, ...)` and `-1`

`playerId = -1` broadcasts to every connected client. That's fine for
genuinely global state changes (a server-wide announcement, weather sync);
it is **not** fine from inside a loop or timer -- `fxlint` rule P006 flags
`TriggerClientEvent(..., -1, ...)` found inside a loop/timer body as a
broadcast-storm risk. Broadcast once, on the state change itself, not on a
polling cadence.

## Latent events

`TriggerLatentServerEvent`/`TriggerLatentClientEvent(name, target?, bps, ...)`
take an extra bytes-per-second throttle and are for **large, non-urgent**
payloads (a file transfer, a big table) you don't want competing with normal
event traffic (runtime-facts §2). They run on their own rate-limit budget,
separate from ordinary events:

| | rate | burst |
|---|---|---|
| ordinary net events | 50/s | 200 |
| ordinary net events (flood) | 75/s | 300 |
| latent events | 75/s | 125 |
| latent events (flood) | 150/s | 175 |

(runtime-facts §5). Payload size is separately capped at 128 KB/s per client,
burst 384 KB, for ordinary events. Exceeding the base rate (not flood) just
silently drops the packet; exceeding flood or size gets the client
disconnected (runtime-facts §5/§15) -- so a resource that spams events under
load can lose data with **no error on either side**.

## What serializes

Event/export payloads travel as msgpack, not JSON (runtime-facts §2/§15):

- Plain tables, strings, numbers, booleans round-trip normally.
- Functions become funcref proxies (still callable on the receiving side --
  see the exports/callbacks section of `reference/runtime-facts.md` §3 for
  cost caveats; not free).
- `Entity`/`Player` wrapper values pack down to their network id / server id
  and rehydrate back into a wrapper on the other end -- handles survive the
  trip, not just raw numbers.
- `vector2`/`vector3`/`vector4`/`quat` DO survive event payloads: FiveM's Lua runtime packs them as msgpack
  extension types 20–23 (citizenfx/lua-cmsgpack, branch `grit`, `src/lua_cmsgpack.h:333-336` — the submodule pinned in
  `fivem/.gitmodules:161-164`), so `TriggerServerEvent('x', GetEntityCoords(ped))` arrives server-side as a `vector3`
  and `#(coords - other)` works there. JS receives them as arrays. What is NOT supported is `json.encode()` on a vector
  (the bundled json has no vector branch — runtime-facts §15): convert to `{x=,y=,z=}` before encoding
