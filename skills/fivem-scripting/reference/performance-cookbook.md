# Performance cookbook

Twelve before/after recipes for the patterns that actually show up in `resmon`. Target: **0.00–0.02 ms idle,
< 0.10 ms active**. `(runtime-facts §N)` cites `runtime-facts.md`; the ms figures are orders of magnitude on a
60 fps client, not promises. Two facts drive most of this: `Wait(0)` resumes on the **next tick**, which is
frame-bound (≈16.6 ms at 60 fps, ≈5.5 ms at 180 fps), so a per-frame loop runs ~3× more often for a high-FPS
player; and a thread that never `Wait`s hangs the runtime outright (runtime-facts §1).

## 1. Busy loop → adaptive wait

**Symptom:** a proximity check runs every frame everywhere on the map. **resmon:** ~0.8–2.0 ms constant → 0.01 ms.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        if #(GetEntityCoords(PlayerPedId()) - SHOP) < 2.0 then DrawPrompt() end
    end
end)

-- after
CreateThread(function()
    while true do
        local sleep = 1000
        local dist = #(GetEntityCoords(PlayerPedId()) - SHOP)
        if dist < 50.0 then sleep = 250 end
        if dist < 10.0 then sleep = 0; if dist < 2.0 then DrawPrompt() end end
        Wait(sleep)
    end
end)
```

**Why:** the body is identical, only its frequency changes; at 1000 ms it costs ~1/60 of the per-frame version
and nobody perceives a 1 s delay 50 m from a shop. With ox_lib, `lib.points` does this for you.

## 2. Polling keys → `RegisterKeyMapping`

**Symptom:** a `Wait(0)` thread exists only to read one key. **resmon:** ~0.5–1.5 ms constant → 0.00 ms.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        if IsControlJustPressed(0, 38) then ToggleMenu() end
    end
end)
-- after — no thread at all
RegisterCommand('+myres_menu', function() ToggleMenu() end, false)
RegisterCommand('-myres_menu', function() end, false)
RegisterKeyMapping('+myres_menu', 'Open the menu', 'keyboard', 'e')
```

**Why:** the binding is handled by the game's input layer, so the resource costs nothing until the key is
pressed and the player can rebind it (runtime-facts §10). `IsControlJustPressed` polling is only acceptable
*inside* an interaction that is already per-frame for other reasons.

## 3. Per-frame distance to all players → state bag

**Symptom:** a client loops `GetActivePlayers()` every frame. **resmon:** ~2–6 ms at 30 players → 0.01 ms.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        for _, p in ipairs(GetActivePlayers()) do
            if #(GetEntityCoords(GetPlayerPed(p)) - GetEntityCoords(PlayerPedId())) < 3.0 then Show(p) end
        end
    end
end)

-- after — the server writes, every client just reacts
AddStateBagChangeHandler('onDuty', nil, function(bagName, _, value)
    local ply = GetPlayerFromStateBagName(bagName)
    if ply ~= 0 and type(value) == 'boolean' then Show(ply, value) end
end)
```

**Why:** the loop is O(players) per frame, each iteration two natives plus a vector subtraction. Under OneSync
Infinity only players inside the 424-unit focus zone exist client-side anyway, so this iteration belongs on the
server (runtime-facts §6); change handlers fire once per change instead of 60×/s.

## 4. Broadcast storm → targeted event

**Symptom:** a server loop sends the same event to everyone, per player. **Impact:** n² network messages;
clients stutter and the server may drop them (runtime-facts §5).

```lua
-- before
for _, id in ipairs(GetPlayers()) do
    TriggerClientEvent('myres:refresh', -1, state)   -- -1 inside a per-player loop = n × n
end
-- after
TriggerClientEvent('myres:refresh', src, state)      -- only the player who needs it
GlobalState.shopState = state                        -- or: written once, read by everyone
```

**Why:** `TriggerClientEvent(..., -1, ...)` is already one message per connected client, so wrapping it in a
loop over players squares that. Each client has a 50/s (burst 200) event budget and 128 KB/s of payload; over
it, the packet is dropped silently or the client is disconnected (runtime-facts §5, §15).

## 5. Ungated per-frame text draw → gated draw

**Symptom:** 3D text is drawn for every marker in the config, every frame. **resmon:** ~1–3 ms → 0.02 ms.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        for i = 1, #Config.Points do Draw3DText(Config.Points[i]) end
    end
end)

-- after
CreateThread(function()
    while true do
        local sleep, coords = 500, GetEntityCoords(PlayerPedId())
        for i = 1, #Config.Points do
            if #(Config.Points[i].coords - coords) < 8.0 then sleep = 0; Draw3DText(Config.Points[i]) end
        end
        Wait(sleep)
    end
end)
```

**Why:** each `Draw3DText` is a `GetScreenCoordFromWorldCoord` plus five HUD natives, and text beyond ~10 m is
unreadable anyway. The `sleep` flips to 0 only while something is actually in range.

## 6. Allocation in a hot loop → hoisted

**Symptom:** tables/strings/vectors built per frame. **resmon:** ~0.4 ms + a GC sawtooth → 0.05 ms flat.

```lua
-- before (inside a Wait(0) loop)
local label = 'Fuel: ' .. math.floor(fuel) .. '%'   -- 2 garbage strings per frame
local pos = vector3(base.x, base.y, base.z + 1.0)   -- new vector per frame
SendNuiMessage(json.encode({ fuel = fuel }))        -- encode per frame

-- after: POS is a file-scope constant, the label is rebuilt only when the value changes
local POS <const> = base + vector3(0.0, 0.0, 1.0)
if math.floor(fuel) ~= lastShown then
    lastShown = math.floor(fuel)
    label = ('Fuel: %d%%'):format(lastShown)
end
```

**Why:** every concatenation, table constructor and `json.encode` allocates, and Lua's collector runs inside
your frame budget. Hoist anything constant; recompute derived strings only when their inputs change.

## 7. Pool scans → cached list

**Symptom:** `GetGamePool('CVehicle')`/`GetAllVehicles()` per frame. **resmon:** ~1–4 ms in traffic → 0.02 ms.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        for _, veh in ipairs(GetGamePool('CVehicle')) do Check(veh) end
    end
end)

-- after: consumers iterate `vehicles` and guard each handle with DoesEntityExist(veh)
local vehicles = {}
CreateThread(function()
    while true do
        vehicles = GetGamePool('CVehicle')      -- one scan every 5 s
        Wait(5000)
    end
end)
```

**Why:** a pool scan walks the whole pool and allocates a fresh table each call, and vehicles do not appear
60×/s. Always re-check `DoesEntityExist` on a cached handle — entities die between refreshes.

## 8. Many threads → one scheduler thread

**Symptom:** five features, five `CreateThread` loops. **resmon:** five wake-ups per second → one.

```lua
-- before
CreateThread(function() while true do Wait(1000); Fuel() end end)
CreateThread(function() while true do Wait(1000); Hunger() end end)
CreateThread(function() while true do Wait(5000); Save() end end)
-- after
CreateThread(function()
    local n = 0
    while true do
        n = n + 1
        Fuel(); Hunger()
        if n % 5 == 0 then Save() end
        Wait(1000)
    end
end)
```

**Why:** each coroutine is scheduled independently by deadline (runtime-facts §1); one thread ticking a
counter does the same work with one wake-up, in a deterministic order — which matters when tasks share state.

## 9. Loop left running after the interaction ends → stop flag

**Symptom:** a `Wait(0)` loop is started on enter, never stopped. **resmon:** 0.5 ms forever after first use,
plus another 0.5 ms per re-entry.

```lua
-- before
AddEventHandler('zone:enter', function()
    CreateThread(function() while true do Wait(0); DrawUi() end end)   -- never ends, and stacks
end)

-- after
local active = false
AddEventHandler('zone:enter', function()
    if active then return end                       -- the guard is what makes P004 acceptable here
    active = true
    -- fxlint-disable-next-line P004
    CreateThread(function() while active do Wait(0); DrawUi() end end)
end)
AddEventHandler('zone:exit', function() active = false end)
```

**Why:** nothing stops a coroutine from outside — it ends when its function returns. Without the flag and the
re-entry guard you accumulate a permanent per-frame loop per entry; `fxlint` P004 flags `CreateThread` inside
an event handler for exactly this reason.

## 10. NUI message spam → throttled, on-change

**Symptom:** the UI is pushed the full state every frame. **resmon:** ~0.6 ms + a busy browser → ~0.01 ms.

```lua
-- before (inside a Wait(0) loop)
SendNuiMessage(json.encode({ action = 'hud', hp = hp, armour = armour, fuel = fuel }))

-- after
local lastSent, lastHash = 0, ''
local function pushHud(payload)
    local now, hash = GetGameTimer(), ('%d|%d|%d'):format(payload.hp, payload.armour, payload.fuel)
    if hash == lastHash or now - lastSent < 100 then return end   -- ≤ 10 messages/s, only on change
    lastSent, lastHash = now, hash
    SendNuiMessage(json.encode(payload))
end
```

**Why:** `SendNuiMessage` takes a JSON string, so every call is a `json.encode` plus a hop into the browser,
which re-renders. A HUD updating 10×/s looks identical to one updating 60×/s.

## 11. `SetTimeout` misuse → the right primitive

**Symptom:** `SetTimeout` used as an interval, or scheduled from inside a loop so timers pile up.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        SetTimeout(1000, Save)        -- one new timer every frame: 60 saves/s, forever
    end
end)

-- after — periodic work is a thread; SetTimeout is for genuine one-shots
CreateThread(function() while true do Wait(60000); Save() end end)
SetTimeout(5000, function() Notify('Welcome') end)   -- fires once, needs no coroutine of its own
```

**Why:** Lua has no `SetInterval` (runtime-facts §1) and `SetTimeout` never replaces a pending timer — each
call schedules another callback. Threads for repeats, `SetTimeout` only for "do this once, later".

## 12. Server loop over all players → event-driven

**Symptom:** the server polls every player's position on a tick. **Impact:** linear in player count — at 64
players a per-tick loop is ~3–8 ms per pass.

```lua
-- before
CreateThread(function()
    while true do
        Wait(0)
        for _, id in ipairs(GetPlayers()) do
            local ped = GetPlayerPed(id)
            if #(GetEntityCoords(ped) - JAIL) < 5.0 then Release(id) end
        end
    end
end)

-- after — the client already knows where it is; it tells the server once
RegisterNetEvent('jail:atGate', function()
    local src = source                                        -- validated server-side, as always
    local ped = GetPlayerPed(src)
    if ped ~= 0 and #(GetEntityCoords(ped) - JAIL) < 5.0 then Release(src) end
end)
```

**Why:** `GetPlayers()` is a Lua loop over `GetNumPlayerIndices`/`GetPlayerFromIndex`, not a single native
(runtime-facts §11), and `GetEntityCoords` per player per tick is O(n) server work for something one client
already knows. Let the client report, then re-verify server-side: the distance check stays, the poll goes. If a
poll really is needed, run it at 1000–5000 ms, never per tick.
