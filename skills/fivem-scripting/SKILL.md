---
name: fivem-scripting
description: Rulebook for writing FiveM/Cfx.re resources (Lua 5.4 first, JS notes) that are resmon-friendly and server-authoritative. Use for ANY FiveM, FXServer, fxmanifest, GTA V server, ESX/QBCore/qbox/ox_lib, client/server event, state bag, OneSync, NUI or native-related coding task, before writing or reviewing code.
---

# FiveM scripting rulebook

`(runtime-facts §N)` cites `reference/runtime-facts.md` (source-verified); it wins over anything you remember. Deep
dives: `reference/{manifest,events,frameworks,security-checklist,performance-cookbook,lint-rules}.md`; copy-paste code
in `patterns/<name>.lua`.

## 1. Workflow — the 90 % loop

1. **Understand.** Restate the feature in one sentence. Decide the split *before* writing: what the client may
   decide (rendering, input, local feel) vs what the server owns (money, items, entities, permissions).
2. **Look up every native.** `fxref search "lock vehicle doors" --side client` to find it, then
   `fxref show SetVehicleDoorsLocked` for the signature, or `fxref resolve A B C` to batch-check.
3. **Plan files.** `fxnew <name> [--nui]` scaffolds; otherwise list the files and what each owns.
4. **Write** (§3–§12) **one file per tool call, ≤ ~150 lines per write** (skeleton first, then sections via
   `Edit`; copy `patterns/*.lua` with `cp` instead of retyping), then **lint**: `fxlint <resource_dir>` — fix
   every error, fix or justify every warning.
5. **Self-review** against §14 — before deploying, not after — then `fxserver deploy <resource_dir>` and
   `fxserver restart <name>`.
6. **Hand over** an in-game test checklist (§13); Liam tests, you do not. Then read
   `fxserver logs --errors --resource <name>` once he reports back — plus `fxclient logs --errors` and
   `fxclient profile <name>` for client-side errors and resmon numbers `fxserver.log` can't show.

**Hard rule — no native from memory.** Every native you write must have been confirmed by `fxref show` or `fxref
resolve` *in this session*. Check three things on the card: exact name, argument order, and `apiset`. A `client`
native in a `server_script` (or vice versa) is a runtime error — `shared` works on both. A typo'd native does not
error where it is written: Lua's global lookup silently returns `nil` and caches the miss, so it only blows up at call
time, possibly in a rare branch (runtime-facts §1, §15). `MISSING` for a name you are sure of usually means a **Lua
runtime helper, not a native** — `GetPlayers`, `GetPlayerIdentifiers`, `GetPlayerTokens` (runtime-facts §11),
`PerformHttpRequest` (runtime-facts §12) are fine to call; anything else that resolves MISSING does not exist. Docs
beyond natives: `fxref docs search "state bags"`, `fxref docs show docs/scripting-manual/networking/state-bags`.

## 2. Project defaults

Read `$KIT/config.json` → `project` before scaffolding: `language`, `framework`, `ox_lib`, `game`, `author`,
`workspace`. Today: **Lua, framework `core` (Liam's own — load the `fivem-core` skill for any `Core.*` work), ox_lib false, gta5, author MnkyArts**. Write code that works
with no library; where a helper exists add one line — *"if ox_lib is available, prefer `lib.callback`"* — but never
hard-depend on it while `ox_lib` is `false`. Never emit `lua54 'yes'` (§3).

## 3. Resource anatomy

```lua
fx_version 'cerulean'
game 'gta5'
author 'MnkyArts'
description 'One line, what it does.'
version '1.0.0'
shared_scripts { 'shared/config.lua' }   -- '@ox_lib/init.lua' first, only if ox_lib is enabled
client_scripts { 'client/*.lua' }
server_scripts { 'server/*.lua' }
```

- **No `lua54 'yes'`** — a dead no-op. Lua 5.3 was removed in June 2025; everything runs 5.4 (runtime-facts §8).
- **No `use_experimental_fxv2_oal 'yes'`** by default — faster native calls, but it disables `vector3` auto-unpacking,
  so every vector argument must become `v.x, v.y, v.z` or you pass garbage (runtime-facts §8).
- The modern runtime is enabled by the file being named `fxmanifest.lua` (`is_cfxv2`), not by `fx_version`; a resource
  below `adamant` is refused at start (runtime-facts §8).
- Layout `client/`, `server/`, `shared/config.lua` (one `Config` table, `Config.Debug = false`), `html/`, `locales/`.
  Resource names `snake_case`; events `resource:verbNoun`; exports via `exports('name', fn)`. Full key list:
  `reference/manifest.md`.

## 4. Threads & performance

Target in `resmon`: **0.00–0.02 ms idle, < 0.10 ms active**; permanently above 0.05 ms idle is a bug.

- **No loop without `Wait`** — a thread that never yields hangs the client (runtime-facts §1). `Wait(0)` = the *next
  tick*, frame-bound: ≈16.6 ms at 60 fps, ≈5.5 ms at 180 fps (runtime-facts §1), so per-frame work costs a high-FPS
  player ~3× more. `Wait(n)` is a minimum, never exact.
- **Per-frame (`Wait(0)`) only for drawing and control reads, and only while the interaction is active.** Start the
  loop on enter, stop it on exit — never leave one running "just in case". Adaptive wait otherwise:

| Player distance to the point | Wait |
|---|---|
| > 50 m, or wrong job/zone/vehicle | 1000 ms |
| 10–50 m | 250–500 ms |
| in range (marker/prompt visible) | 0 ms |

- **Never poll `IsControlJustPressed` outside an active interaction** — use `RegisterKeyMapping` + a `+cmd`/`-cmd`
  `RegisterCommand` pair: zero cost when unpressed, rebindable (§8). **Cache per tick:** `local ped = PlayerPedId()`,
  `local coords = GetEntityCoords(ped)` once at the top of the loop body. **Never per frame:** `GetGamePool`,
  `GetAllVehicles`, `GetAllPeds`, `GetActivePlayers`, `GetPlayers()`, `GetClosest*`, `json.encode/decode`,
  `TriggerServerEvent`/`TriggerClientEvent`, `exports.x:y()`, `.state` reads, `RequestModel`/`RequestAnimDict` — batch
  or cache them. Why: exports and funcrefs cross msgpack + a native invoke, not a cheap Lua call (runtime-facts §3);
  every `.state.key` read deserializes the whole value (runtime-facts §4); `GetPlayers()` is a Lua loop over two
  natives (§11).
- **`SetTimeout(ms, fn)` for one-shots** — a separate scheduling path needing no coroutine of its own; there is no
  `SetInterval` in Lua (runtime-facts §1). **One thread per concern, stopped by a flag**: never `CreateThread` in an
  event handler or loop body, that leaks a thread per event.
- **No allocation in hot loops:** hoist tables/strings/vectors out; `string.format` on change, not per frame. **NUI:**
  `SendNuiMessage` ≤ 10 messages/s, and only on change — never per frame (§8).
- **`TriggerClientEvent(name, -1, ...)` sparingly** — one call fans out to every client; prefer targeted
  `TriggerClientEvent(name, src, ...)` or a state bag. **Engine ceilings per client** (runtime-facts §4, §5): net
  events 50/s burst 200 (flood 75/300 → client **dropped**), payload 128 KB/s burst 384 KB → dropped; state bags 75/s
  burst 125 (flood 150/175), 128 KB/s burst 256 KB. Under the base limit the packet is **silently discarded**, no
  error either side (runtime-facts §15). Design an order of magnitude below these. Payloads > 64 KB go through
  `TriggerLatentClientEvent(name, target, bps, ...)` / `TriggerLatentServerEvent`, which have their own 75/s burst 125
  budget (runtime-facts §2, §5).

Canonical interaction loop (enter/exit driven, adaptive; full version in `patterns/interaction-zone.lua`):

```lua
local POINT <const> = vector3(25.7, -1347.3, 29.49)

CreateThread(function()
    while true do
        local sleep = 1000
        local dist = #(GetEntityCoords(PlayerPedId()) - POINT)
        if dist < 50.0 then sleep = 250 end
        if dist < 10.0 then
            sleep = 0
            DrawMarker(21, POINT.x, POINT.y, POINT.z + 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                0.3, 0.3, 0.3, 0, 150, 255, 120, false, true, 2, false, nil, nil, false)
            if dist < 1.5 and IsControlJustReleased(0, 38) then
                TriggerServerEvent('shop:open') -- the server re-checks the distance itself
            end
        end
        Wait(sleep)
    end
end)
```

With ox_lib, prefer `lib.points`/`lib.zones` over hand-rolled proximity loops, and `cache.ped` /
`lib.onCache('ped', fn)` over `PlayerPedId()` per tick. 12 recipes: `reference/performance-cookbook.md`.

## 5. Events & security

**The client is an input device and a renderer, nothing else.** A cheater can trigger any `RegisterNetEvent` with any
payload, call any client native, patch out any client-side check and read every client file, so **the server decides,
validates and acts** — details in `reference/security-checklist.md`.

- `RegisterNetEvent(name, handler)` — two-argument form (runtime-facts §2). Use it **only** for events that actually
  arrive over the network; a locally-triggered event uses `AddEventHandler`, and an `AddEventHandler`-only
  registration is not network-triggerable, which is the point (runtime-facts §2).
- **`local src = source` must be the first line** of every server handler — the dispatcher resets `source` right after
  starting the handler coroutine, so it is stale after any `Wait` (runtime-facts §15). Then validate cheapest first:
  **types → ranges → existence → cooldown → distance → permission → rules → act.**

```lua
local lastUse = {}

RegisterNetEvent('shop:buy', function(itemId, amount)
    local src = source
    if type(itemId) ~= 'string' or type(amount) ~= 'number' then return end
    if amount % 1 ~= 0 or amount < 1 or amount > 10 then return end
    local item = Config.Items[itemId]   -- server-side price and stock, never the client's
    local now = GetGameTimer()
    if not item or now - (lastUse[src] or 0) < 1000 then return end
    lastUse[src] = now
    local ped = GetPlayerPed(src)
    if ped == 0 or #(item.coords - GetEntityCoords(ped)) > 3.0 then return end
    Shop.Sell(src, item, amount)
end)
```

- **Never trust from a payload:** player ids (identity is `src`, full stop), prices, amounts, item names used as raw
  keys, entity handles, coordinates, job/rank — anything the server can look up itself. **Per-player cooldowns**
  (table keyed by `src`, cleared in `playerDropped`): 250 ms for interaction events, 1 s for money/items, 5 s for
  DB/HTTP. Client-side rate limiting is **cosmetic** — UX only, never a control.
- **Commands & permissions:** `RegisterCommand(name, fn, true)` in a **server** script, plus
  `add_ace group.admin command.<name> allow`. `restricted` is meaningless client-side (no client permission system)
  and `source` is `0` for console/RCON, so handle that branch first (runtime-facts §10). Elsewhere use
  `IsPlayerAceAllowed(src, 'myres.admin')` — never a client-supplied "isAdmin" flag.
- **Callbacks** (client asks the server a question): with ox_lib, `lib.callback.register(name, fn)` server-side and
  `lib.callback.await(name, false, ...)` client-side; on `core`, `Core.Callback.register/await`; standalone, `patterns/callback.lua`. A callback handler needs
  exactly the same validation as any other net event.
- **Entity creation belongs on the server** for anything persistent or trusted — use
  `CreateVehicleServerSetter(model, 'automobile', x, y, z, heading)` (returns `0` on failure, check it) over server
  `CreateVehicle`, which is dispatched to a client and explicitly fallible (runtime-facts §6, §7). Server
  `CreatePed`/`CreateObjectNoOffset` genuinely create server-side; `NetworkGetEntityOwner(entity)` returns `-1`
  while nothing owns it (runtime-facts §6).
- **State bags:** server writes, clients read. Under `sv_stateBagStrictMode true` every client write is a silent no-op
  at the packet level (runtime-facts §4, §15) — no logic may depend on a client writing state.

## 6. State bags & sync

| Need | Use |
|---|---|
| one-off action, request, or RPC | event |
| durable property others must see: locked/fuel/plate, job/on-duty | `Entity(e).state`, `Player(src).state` |
| server-wide flag or shared config | `GlobalState` |
| big or rarely-read data | server-side table + a callback |

- Server writes replicate by default, client writes do not; `state:set(key, value, replicated)` is explicit. Bag
  names: `player:<serverId>`, `entity:<netId>`, `localEntity:<handle>`, `global`.
  `AddStateBagChangeHandler(keyFilter, bagFilter, handler)` → `function(bagName, key, value, _reserved, replicated)`;
  it **cannot** reject a change, and a `nil` filter matches everything (runtime-facts §4). Resolve the subject with
  `GetEntityFromStateBagName`/`GetPlayerFromStateBagName` — `0` means it is gone. Entity bags also reach clients
  that have the entity **out of scope**, and the client-side `GetEntityFromStateBagName` (like `NetworkGetEntityFromNetworkId`)
  logs `GetNetworkObject: no object by ID <n>` for every id the client does not hold — a server writing a bag on a
  far-away ped every 2 s spams every console. Parse `entity:(%d+)` and check `NetworkDoesEntityExistWithNetworkId`
  (warning-free) before resolving (seen in-game 2026-09-12).

```lua
AddStateBagChangeHandler('locked', nil, function(bagName, _, value)
    local entity = GetEntityFromStateBagName(bagName)
    if entity == 0 or type(value) ~= 'boolean' then return end
    SetVehicleDoorsLocked(entity, value and 2 or 1)
end)
```

- **State is shallow:** `Entity(v).state.data.fuel = 50` never replicates — write the whole value, or use flat keys
  (`state['fuel'] = 50`). Read once into a local, since every read deserializes the whole value; `LocalPlayer` does
  not exist in server scripts at all (runtime-facts §4, §15). Rate limits as in §4; a change handler fires on *every*
  matching change, so filter by key and keep it cheap.

## 7. OneSync & entities

- OneSync is on by default; Infinity supports 2048 players and hardcodes a **424-unit focus zone** per player, outside
  of which no peds/vehicles/players exist client-side — **all player iteration happens server-side** (runtime-facts
  §6).
- **Send net ids, never handles.** `NetworkGetNetworkIdFromEntity(entity)` to send,
  `NetworkGetEntityFromNetworkId(netId)` to receive, then `DoesEntityExist(entity)` before touching it. Net ids are
  16-bit and reused over time (runtime-facts §6).
- Entities created server-side persist without an owner nearby. Track every one you create and `DeleteEntity` them in
  `onResourceStop` and when no longer needed. `SetEntityOrphanMode(entity, 2)` (KeepEntity) only stops the **server**
  culling it — a client can still delete it; `SetEntityDistanceCullingRadius` / `SetPlayerCullingRadius` are
  deprecated with "known, unfixable issues" (runtime-facts §6).
- Don't use `playerEnteredScope`/`playerLeftScope` for per-player logic — O(n) per scope change; use state bags +
  change handlers (runtime-facts §6). To veto entity creation hook the `...ing` event: `entityCreating` +
  `CancelEvent()` removes the clone, while `entityCreated` is queued and cancelling it does nothing (§9).
- Server-side "RPC" natives (`SetEntityCoords`, `TaskPlayAnim`, `SetVehicleDoorsLocked`, …) run on a client and are
  documented as fallible — read back or re-apply; never assume they took effect (runtime-facts §7, §15).
- Model loading always with a timeout, and always released (`patterns/model-loading.lua`):

```lua
local function requestModel(model)          -- with ox_lib: lib.requestModel(model, timeout)
    if not IsModelValid(model) then return false end
    RequestModel(model)
    local deadline = GetGameTimer() + 5000
    while not HasModelLoaded(model) and GetGameTimer() < deadline do Wait(0) end
    return HasModelLoaded(model)
end   -- after spawning, always: SetModelAsNoLongerNeeded(model)
```

## 8. Client patterns

- **Keys:** register a `+`/`-` command pair and map only the `+` one — `RegisterCommand('+res_sprint', fn, false)`,
  `RegisterCommand('-res_sprint', fn, false)`, `RegisterKeyMapping('+res_sprint', 'Sprint', 'keyboard', 'lshift')`;
  `~!` prefixes an alternate binding (runtime-facts §10). With ox_lib, `lib.addKeybind`. Full version:
  `patterns/keymapping.lua`.
- **Interactions:** enter/exit driven (§4); markers only inside ~20 m, text UI only inside ~2 m. **Anims:**
  `RequestAnimDict` + timed wait + `RemoveAnimDict` after — same shape as §7's model helper.
- **NUI:** `SendNUIMessage({ action = 'open', data = data })` (runtime helper, auto-encodes; the raw native
  `SendNuiMessage` takes a JSON string) and `RegisterNUICallback(name, fn)` (scheduler.lua:793-807); the page fetches
  `https://${GetParentResourceName()}/<callback>`, other resources' files come from `https://cfx-nui-<resource>/`
  (runtime-facts §8, §12). Every `RegisterNuiCallback` **must** call `cb(...)` — even `cb({})` — or the page's `fetch`
  hangs until it times out; every `SetNuiFocus(true, true)` needs a guaranteed path back to
  `SetNuiFocus(false, false)` (close button, ESC, `onResourceStop`). NUI input is player-controlled: re-validate it
  server-side like any event. **No `backdrop-filter`** (blur/saturate, Tailwind `backdrop-*`) in NUI CSS: the game
  frame is not part of the CEF compositing surface, so the filtered area renders as a solid black box in-game
  (seen on the `core` menus 2026-09-12). Blurring the game behind a panel IS possible the way the FiveM main menu
  does it: a WebGL texture that receives `TEXTURE_WRAP_T` = CLAMP_TO_EDGE → MIRRORED_REPEAT → REPEAT is bound to
  the game's back buffer by `nui-core` (`NUIInitialize.cpp` glTexParameterfHook); draw it into a canvas at ~30 fps
  and CSS-blur the canvas (`core` ships this as `data-core-blur`, DESIGN §32; reference: cfx-ui app.component.ts).
- **Lifecycle:** guard `onClientResourceStart`/`onClientResourceStop` with
  `if GetCurrentResourceName() ~= resourceName then return end` — they fire for every resource (runtime-facts §9),
  and the stop handler must be synchronous, no `Wait`. Client Lua has **no `io`/`os`** (runtime-facts §15): use
  `GetGameTimer()` for all timing.

## 9. Server patterns

- **`playerConnecting(name, setKickReason, deferrals)`**: for async checks call `deferrals.defer()`, then `Wait(0)` at
  least one tick before `update`/`presentCard`/`done` — `done()` on the same tick is the classic footgun
  (runtime-facts §9, §15). Without deferrals you cannot `Wait`; reject with `CancelEvent()` + `setKickReason(msg)`.
- **`playerJoining(oldId)`**, **`playerDropped(reason, resourceName, clientDropReason)`** — clear every per-player
  table (cooldowns, caches, owned entities) in `playerDropped` or you leak.
- **Persistence:** KVP for small resource-local data (`SetResourceKvp`, `GetResourceKvpString`, `DeleteResourceKvp`);
  bulk = `*NoSync` writes + one `FlushResourceKvp()` (runtime-facts §12). KVP is `shared` apiset, so the client store
  is client-writable — never a security boundary. Real data: oxmysql if present, `?` placeholders only —
  `MySQL.query.await('SELECT cash FROM users WHERE id = ?', { id })`.
- **HTTP:** `PerformHttpRequest(url, cb, method, body, headers)`, server only. Tokens live in convars, never in a
  client or shared file; responses are untrusted; `PerformHttpRequestAwait` needs build 9515+ (§12).
- **Convars:** plain `set` convars are invisible to clients, only `setr`/`sets` reach them; never print or log
  `sv_licenseKey` (runtime-facts §11). **Scheduling:** `SetTimeout` for one-shots, one loop thread for periodic work,
  never one per player. **Logging:** players by `src` + one identifier, never a `GetPlayerIdentifiers` dump.

## 10. Framework adapters

`config.json` → `project.framework` decides; it is `core` today (Liam's framework: `fivem-core` skill, `fxref core`), so do not import ESX/QBCore. If another one is configured, get
the core object once at file scope (never per call) and **never reimplement** money, items, inventory, jobs or
notifications — call the framework. Snippets + detection: `reference/frameworks.md`.

## 11. Lua 5.4 style

`local` everything, no globals except deliberate exports, `<const>` for config constants.
`CreateThread`/`Wait`/`SetTimeout`, never `Citizen.*` (legacy aliases — runtime-facts §1).
`RegisterNetEvent(name, handler)`, two args. Vectors are first-class: `vector3(x, y, z)`, `#(a - b)` for distance,
`.x/.y/.z` fields — never `Vdist`/`GetDistanceBetweenCoords` in new code, and `json.encode` on a vector is
unsupported, so convert to a table first (runtime-facts §15). `Hash` parameters accept a Lua string (auto
`GetHashKey`), backtick literals are the compile-time form, and passing `0`/`nil` to a **string** parameter sends a
null string, not `"0"` (runtime-facts §15). Early returns over nesting, small named functions, `string.format` over
concatenation chains, `//` for integer division. A missing export **raises** rather than returning nil
(runtime-facts §3), so `pcall` cross-resource calls that may run before the other resource started. No
`load`/`loadstring`/`dofile`/`os.execute`/`io.popen`; comments only where the *why* is non-obvious; English
identifiers.

## 12. JS/TS notes

Only when `project.language` is `js`. `on(name, fn)` local, `onNet(name, fn)` network-triggerable, `emitNet` to cross;
JS `RegisterNetEvent(name)` takes **no handler**, it only marks the name net-safe (runtime-facts §2).
`const src = source` first, same as Lua — JS never restores an outer `source` after a nested `emit` (§15).
`setTick(fn)` runs every tick: return a Promise to gate it, `clearTick(id)` to stop; `setTimeout(fn, 0)` really means
~1 ms (runtime-facts §13). Vectors and multiple returns arrive as arrays (`fxref show` prints the JS signature). Hop
back to the main thread from a Node callback with `setImmediate` or natives throw "No current resource manager"
(runtime-facts §15). Typings `@citizenfx/client`/`-server`; `node_version '22'` opts into Node 22 (runtime-facts §8).

## 13. Testing hand-off

You cannot test in-game. After `fxserver deploy` + `fxserver restart`, hand Liam a checklist in this shape (`resmon 1`
needs the client started with `+set moo 31337` — runtime-facts §14):

```
1. Happy path: <exact steps> → expect <exact result>
2. Do it at 4 m away → nothing happens, no error
3. Do it with no money/item → refusal message, no state change
4. Restart the resource while the UI is open → focus released, no stuck cursor
5. Spam the key for 10 s → at most 1 action/s, no kick, no duplication
6. Trigger the event from a 2nd client, targeting player 1 → refused
7. Disconnect mid-action (during the anim/timer) → no orphaned entity, no dupe on rejoin
8. resmon 1: far away → 0.00–0.02 ms; inside the zone → < 0.10 ms
```

Then `fxserver logs --errors --resource <name>`: `attempt to call a nil value` = a native that does not exist (verify
with `fxref`) or an export used before its resource started; `attempt to index a nil value` = an unvalidated payload
field; `attempt to compare nil with number` = a missing type check; `was not safe for net` = the event needs
`RegisterNetEvent` (runtime-facts §2); `Reliable network event overflow` = the §4 rate limits. For CPU spikes,
`fxclient profile <name> --frames 300` for a per-resource breakdown, or `fxclient screenshot --resmon` for a
quick resmon snapshot.

## 14. Review checklist

Run this before deploying. Bad → good for each item: `reference/security-checklist.md`, same numbering.

1. Every native verified with `fxref` this session; each one's `apiset` matches the file's side.
2. Every server net-event handler starts with `local src = source`.
3. Every net-event argument is type-checked before use.
4. Numbers are range- and integer-checked (no negative, fractional, NaN or absurd values).
5. Identity comes from `src` only — no player id from the payload.
6. Prices/amounts/rewards/stock come from server-side config, never from the payload.
7. Any world action distance-checks against `GetEntityCoords(GetPlayerPed(src))`.
8. Privileged actions check `IsPlayerAceAllowed(src, ...)`.
9. Every money/item/DB/entity event has a per-player cooldown.
10. `RegisterNetEvent` only for genuinely network-triggered events; local ones use `AddEventHandler`.
11. Admin commands are `RegisterCommand(name, fn, true)` on the server + ACE; `source == 0` handled.
12. No client entity handle trusted: net id → `NetworkGetEntityFromNetworkId` → `DoesEntityExist` → owner check.
13. Persistent entities are created server-side and tracked for cleanup.
14. State bags: server writes, clients read; nothing depends on a client write.
15. State-bag change handlers validate `value` and check the resolved entity/player is non-zero.
16. Every `RegisterNuiCallback` calls `cb(...)`; NUI input is re-validated server-side.
17. Every `SetNuiFocus(true, ...)` has a guaranteed path back to `SetNuiFocus(false, false)`.
18. Exported functions validate arguments as if they came from the network.
19. SQL uses `?` placeholders only — no concatenation or interpolation of user data.
20. No secrets in client/shared files; HTTP responses treated as untrusted.
21. KVP is not used as a security boundary.
22. Logs carry no unnecessary identifiers/IPs/tokens; `sv_licenseKey` never printed.
23. `onResourceStop` deletes created entities/blips/peds, clears NUI focus, stops threads — and never `Wait`s.
24. Per-player tables are cleared in `playerDropped`.
25. No `load`/`loadstring`/`os.execute`/`io.popen`/`dofile`; no event name built from client input.
26. No per-frame or per-player-loop `TriggerClientEvent(-1)`; payloads stay far below 128 KB/s.
