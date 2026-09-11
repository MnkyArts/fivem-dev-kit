# Security checklist (reviewer's full list)

Same 26 items, same order, as `SKILL.md` §14 — rule, then a bad → good pair. `(runtime-facts §N)` cites
`runtime-facts.md`. Lua 5.4, standalone (no ox_lib) unless labelled.

## What a cheater can actually do

Assume all of this, always:

- **Trigger any `RegisterNetEvent` on the server, with any arguments, at any rate** — event names ship to every
  client inside your client scripts, so there is no secret name.
- **Call any client native** — spawn entities, teleport, give weapons, write their own state bag (unless
  `sv_stateBagStrictMode true`, which makes client writes silent no-ops at the packet level — runtime-facts §4).
- **Patch out any client-side check**: cooldowns, distance checks, "isAdmin" booleans, UI gating and client
  `RegisterCommand` handlers are all suggestions.
- **Read every client and shared file** — they are downloaded to disk, so API keys, webhook URLs, prices, item
  lists and admin identifiers in them are public.
- **Lie in every payload** — player ids, entity handles, net ids, coordinates, amounts, prices, item names.

So on the server: identity from `source` only; prices, amounts, stock, permissions and cooldowns from
server-side data only; entity existence and ownership re-checked; secrets in `server_scripts` or convars.
Client-side checks stay for UX (they save a round trip); they are never controls.

## Engine rate limits (per client, from source)

| Path | Rate / burst | Over base | Flood limit → client dropped |
|---|---|---|---|
| net events | 50/s, 200 | packet dropped, silent | 75/s, burst 300; payload 128 KB/s, burst 384 KB |
| latent events | 75/s, 125 | packet dropped | 150/s, burst 175 |
| state bags | 75/s, 125 | dropped, logged ≤1×/15 s | 150/s, 175; payload 128 KB/s, burst 256 KB |

Source: runtime-facts §4, §5, §15. Exceeding the *base* limit silently loses events/state with no error on
either side — so your own rate limiting has to keep you an order of magnitude below these, not just under them.

## The `source`-after-`Wait` gotcha

The Lua dispatcher starts each handler in its own coroutine and then immediately restores the previous
`_G.source` without waiting for the handler to finish, so after any `Wait`/`Await` the global is stale and may
belong to a different player (runtime-facts §15). JS resets `global.source = null` at the end of every dispatch
and never restores an outer one (runtime-facts §2).

```lua
RegisterNetEvent('bank:withdraw', function(amount)
    -- bad:  Wait(100); Accounts.Take(source, amount)  -- `source` is now someone else's, or nil
    local src = source                     -- good: first statement, always
    Wait(100)
    Accounts.Take(src, amount)
end)
```

## The checklist

**1. Every native verified with `fxref` this session; each one's `apiset` matches the file's side.** A `client`
native in a server script is a runtime error, and a typo'd native resolves to `nil` silently and only errors
when called (runtime-facts §1, §15).

```lua
SetVehicleDoorsLockedForPlayer(veh, player, true)  -- bad in a server script: apiset is client
SetVehicleDoorsLocked(veh, 2)                      -- good: fxref says apiset client+server
```

**2. Every server net-event handler starts with `local src = source`** (see the gotcha above; `fxlint` S001
flags handlers that never reference `source`). **3–4. Type-check every argument; range- and integer-check every
number** — an unchecked argument is an arithmetic error at best, a duplication exploit at worst.

```lua
RegisterNetEvent('shop:buy', function(id, amount)
    local src = source
    -- bad: Inventory.Add(src, id, amount)  -- nil, -5, 1e9, 0.5, {} all accepted
    if type(id) ~= 'string' or type(amount) ~= 'number' then return end   -- good
    if amount ~= amount or amount % 1 ~= 0 then return end                -- NaN and fractions out
    if amount < 1 or amount > 10 then return end
    Inventory.Add(src, id, amount)
end)
```

**5. Identity comes from `src` only.** Never a player id out of the payload — that is impersonation by design.

```lua
RegisterNetEvent('police:cuff', function(targetId)
    -- bad: TriggerClientEvent('police:getCuffed', targetId) -- cuff anyone, from anywhere
    local src = source                                   -- good
    if type(targetId) ~= 'number' or targetId == src then return end
    if not Jobs.IsPolice(src) then return end            -- server-side job, not a payload flag
    local a, b = GetPlayerPed(src), GetPlayerPed(targetId)
    if a ~= 0 and b ~= 0 and #(GetEntityCoords(a) - GetEntityCoords(b)) < 2.5 then
        TriggerClientEvent('police:getCuffed', targetId)
    end
end)
```

**6. Prices, amounts, rewards and stock come from server-side config.**

```lua
Money.Remove(source, price)                              -- bad: the client names its own price
local def = Config.Items[item]                           -- good: the server owns the price
if def then Money.Remove(src, def.price * amount) end
```

**7. Distance-check any world action against the acting player's ped.**

```lua
SetEntityCoords(GetPlayerPed(src), x, y, z, false, false, false, false)  -- bad: free teleport
local ped = GetPlayerPed(src)                                            -- good
if ped == 0 or #(Config.Shop.coords - GetEntityCoords(ped)) > 3.0 then return end
-- server-side SetEntityCoords is a fallible RPC to a client (runtime-facts §7, §15)
```

**8. Privileged actions check `IsPlayerAceAllowed(src, ...)`** — never a client-supplied flag, never a
hardcoded identifier list in a client/shared file.

```lua
RegisterNetEvent('admin:revive', function(target, isAdmin)
    -- bad: if isAdmin then Revive(target) end  -- the client says it is admin
    local src = source                                   -- good
    if not IsPlayerAceAllowed(src, 'myres.revive') then return end
    if type(target) ~= 'number' or GetPlayerPed(target) == 0 then return end
    Revive(target)
end)
```

Configure with `add_ace group.admin myres.revive allow` + `add_principal identifier.license:… group.admin`; a
principal cannot grant itself access (runtime-facts §10, §15).

**9. Every money/item/DB/entity event has a per-player cooldown** — 250 ms interactions, 1 s money/items, 5 s
DB/HTTP; clear the table in `playerDropped`.

```lua
local last = {}
local function onCooldown(src, key, ms)                  -- use: if onCooldown(src,'buy',1000) then return end
    local now, k = GetGameTimer(), src .. key
    if now - (last[k] or 0) < ms then return true end
    last[k] = now
    return false
end
```

**10. `RegisterNetEvent` only for genuinely network-triggered events** — an `AddEventHandler`-only
registration cannot be reached from the network at all, the cheapest possible hardening (runtime-facts §2):
`RegisterNetEvent('myres:internalRecalc', recalc)` (bad, exposed for no reason) →
`AddEventHandler('myres:internalRecalc', recalc)` (good, local only).

**11. Admin commands use `RegisterCommand(name, fn, true)` in a server script + ACE, and handle `source == 0`
(console/RCON).** `restricted` does nothing client-side (runtime-facts §10).

```lua
RegisterCommand('giveweapon', handler, false)            -- bad: unrestricted, anyone can run it
RegisterCommand('giveweapon', function(source, args)     -- good (server script)
    local src = source
    if src > 0 and not IsPlayerAceAllowed(src, 'command.giveweapon') then return end
    local target = tonumber(args[1])
    if not target or GetPlayerPed(target) == 0 then return end
    GiveWeaponToPed(GetPlayerPed(target), `WEAPON_PISTOL`, 50, false, true)
end, true)                                               -- restricted = true
```

**12. Never trust a client entity handle.** Send net ids; convert, then verify existence, ownership and
distance — net ids are 16-bit and get reused (runtime-facts §6).

```lua
RegisterNetEvent('veh:lock', function(netId)
    -- bad: SetVehicleDoorsLocked(entityFromPayload, 2) -- any handle, anyone's vehicle
    local src = source                                   -- good
    if type(netId) ~= 'number' then return end
    local veh, ped = NetworkGetEntityFromNetworkId(netId), GetPlayerPed(src)
    if veh == 0 or ped == 0 or not DoesEntityExist(veh) then return end
    if NetworkGetEntityOwner(veh) ~= src then return end
    if #(GetEntityCoords(veh) - GetEntityCoords(ped)) > 5.0 then return end
    Entity(veh).state:set('locked', true, true)
end)
```

**13. Persistent entities are created server-side and tracked for cleanup** — `CreateVehicleServerSetter` over
server `CreateVehicle` (dispatched to a client, fallible); check the `0` return (runtime-facts §6, §7).

```lua
TriggerClientEvent('veh:spawn', src, model, coords)      -- bad: the client spawns it, and owns it
local veh = CreateVehicleServerSetter(model, 'automobile', coords.x, coords.y, coords.z, heading)
if veh == 0 then return end                              -- good
spawned[#spawned + 1] = veh                              -- deleted in onResourceStop
```

**14. State bags: the server writes, clients read** — under `sv_stateBagStrictMode true` client writes are
no-ops at the packet level, so anything depending on them silently breaks (runtime-facts §4, §15):
`LocalPlayer.state:set('job', 'police', true)` (bad, client-authored truth) →
`Player(src).state:set('job', job, true)` (good, server).

**15. State-bag change handlers validate `value` and check the resolved subject.** The writer may be a client,
the handler cannot reject a change, and the resolvers return `0` when the subject is gone (runtime-facts §4).

```lua
AddStateBagChangeHandler('cuffed', nil, function(bagName, _, value)
    local ply = GetPlayerFromStateBagName(bagName)
    if ply == 0 or type(value) ~= 'boolean' then return end   -- good: subject and type checked
end)
```

**16–17. Every `RegisterNuiCallback` calls `cb(...)`; NUI input is re-validated server-side; every
`SetNuiFocus(true, …)` has a guaranteed path back.** A missing `cb` hangs the page's `fetch` until timeout
(runtime-facts §12); NUI is a browser the player can open devtools on, so it is client input, not a source.

```lua
-- bad: RegisterNuiCallback('buy', function(data) TriggerServerEvent('shop:buy', data.item, data.price) end)
RegisterNuiCallback('buy', function(data, cb)                 -- good
    if type(data) == 'table' and type(data.item) == 'string' then
        TriggerServerEvent('shop:buy', data.item, 1)          -- the server prices it
    end
    cb({ ok = true })                                         -- always answer, or the page hangs
end)
AddEventHandler('onClientResourceStop', function(res)
    if GetCurrentResourceName() == res then SetNuiFocus(false, false) end
end)
```

**18. Exported functions validate arguments as if they came from the network** — any resource can call your
export, and a sloppy one will pass junk. A missing export *raises* rather than returning nil (runtime-facts §3),
so `pcall` cross-resource calls made at startup.

```lua
exports('addMoney', function(src, amount) Money.Add(src, amount) end)         -- bad
exports('addMoney', function(src, amount)                                     -- good
    if type(src) ~= 'number' or type(amount) ~= 'number' or GetPlayerName(src) == nil then return false end
    if amount % 1 ~= 0 or amount <= 0 or amount > 1000000 then return false end
    return Money.Add(src, amount)
end)
```

**19. SQL uses `?` placeholders only.**

```lua
MySQL.query.await('SELECT * FROM users WHERE id = ' .. id)   -- bad: injection
MySQL.query.await('SELECT * FROM users WHERE id = ?', { id })  -- good (oxmysql)
-- table/column names cannot be parameterized: map a varying one through a fixed allow-list table
```

**20. No secrets in client or shared files; HTTP responses are untrusted.** Those files are downloaded to every
player's disk. Keep webhooks, tokens and API keys in `server_scripts`, read from a convar set in `server.cfg`;
plain `set` convars never reach clients (runtime-facts §11).

```lua
Config.Webhook = 'https://discord.com/api/webhooks/…'    -- bad, in shared/config.lua: public
local webhook <const> = GetConvar('myres_webhook', '')   -- good, in server/main.lua
PerformHttpRequest(webhook, cb, 'POST', json.encode(payload), headers)  -- treat the response as untrusted
```

**21. KVP is not a security boundary** — `SetResourceKvp` is `apiset: shared` and the client store lives on the
player's disk, fully writable by them (runtime-facts §12, §15). Client preferences only.

```lua
SetResourceKvp('balance', tostring(balance))  -- bad (client): the player edits the file and "has" money
SetResourceKvp('uiScale', '1.25')             -- good (client): cosmetic preference only
```

**22. Logs carry no unnecessary identifiers/IPs/tokens; `sv_licenseKey` is never printed** — it is readable as
a plain convar, and a "dump all convars" debug helper leaks it (runtime-facts §11, §15).

```lua
print(json.encode(GetPlayerIdentifiers(src)), GetPlayerEndpoint(src))         -- bad: PII in the log
print(('[shop] %s (%d) bought %s'):format(GetPlayerName(src), src, item))     -- good
```

**23–24. `onResourceStop` cleans up; per-player tables are cleared in `playerDropped`.** The stop handler must
be synchronous, no `Wait`; both events fire for every resource, so guard on the name (runtime-facts §9).

```lua
AddEventHandler('onResourceStop', function(res)
    if GetCurrentResourceName() ~= res then return end
    for i = 1, #spawned do
        if DoesEntityExist(spawned[i]) then DeleteEntity(spawned[i]) end
    end
end)
AddEventHandler('playerDropped', function()
    local src = source
    cooldowns[src], sessions[src] = nil, nil
end)
```

**25. No `load`/`loadstring`/`os.execute`/`io.popen`/`dofile`; no event or export name built from client
input.** Client Lua has no `io`/`os` at all (runtime-facts §15); server-side they are remote code execution
waiting to happen, and a dynamic name lets a client reach handlers you never meant to expose.

```lua
TriggerEvent('myres:' .. action, data)                   -- bad: the client picks the handler
local fn = Handlers[action]                              -- good: fixed allow-list table
if fn then fn(src, data) end
```

**26. No per-frame or per-player-loop `TriggerClientEvent(-1)`; payloads stay far below 128 KB/s.** One
broadcast is one message per connected client, so a loop over players plus a `-1` broadcast sends the same data
n² times. Targeted events or a state bag instead, and `TriggerLatentClientEvent` above ~64 KB (§2, §5).

```lua
for _, id in ipairs(GetPlayers()) do
    TriggerClientEvent('myres:sync', -1, bigTable)       -- bad: n × n messages
end
GlobalState.shopStock = stock                            -- good: written once, read by everyone
```
