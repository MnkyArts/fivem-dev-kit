-- fxlint bad-resource fixture: server side.
-- Deliberately bad code. Every line meant to trip a rule is marked with
-- `-- expect: RULE_ID` so tests/test_fxlint.py can assert an exact match.

local cooldowns = {}

-- S001: never reads 'source'. S002: GiveMoney(...) gets a raw event argument
-- with no validation anywhere in the handler.
RegisterNetEvent('bad:giveMoney', function(amount) -- expect: S001
    GiveMoney(1, amount) -- expect: S002
end)

-- S003 (x2): trusts a payload player id ('targetId') instead of 'source'.
-- S009: SetEntityCoords from payload data with no distance check.
RegisterNetEvent('bad:teleportPlayer', function(targetId, x, y, z)
    local ped = GetPlayerPed(targetId) -- expect: S003
    SetEntityCoords(ped, x, y, z) -- expect: S009
end)

-- S003: DropPlayer() targets a payload-supplied id instead of 'source'.
RegisterNetEvent('bad:kickPlayer', function(playerId)
    DropPlayer(playerId, 'kicked') -- expect: S003
end)

-- S003 (downgraded to INFO): only ONE of {type-check, permission/distance
-- guard} is present (a type-check, no guard) -- partially validated, so this
-- is worth a heads-up but not a full warning.
RegisterNetEvent('bad:oneGuardOnly', function(targetId)
    if type(targetId) ~= 'number' then return end
    TriggerClientEvent('bad:oneGuardEvent', targetId) -- expect: S003-INFO
end)

-- S005: admin-looking command registered unrestricted (false).
RegisterCommand('kick', function(source, args) -- expect: S005
    DropPlayer(tonumber(args[1]), 'kicked')
end, false)

-- S008: event argument used in arithmetic with no type check.
RegisterNetEvent('bad:mathOnArg', function(source, amount)
    local total = amount + cooldowns[amount] -- expect: S008
    print(total)
end)

-- S006: dynamic code execution.
RegisterCommand('evalsomething', function(source, args)
    load(args[1])() -- expect: S006
end, true)

-- S004: registered as a net event but never triggered over the network.
RegisterNetEvent('bad:onlyLocal', function(data) -- expect: S004
    TriggerEvent('bad:onlyLocalDone', data)
end)

-- S010: reads 'source' again after a Wait() -- it may already be stale.
RegisterNetEvent('bad:staleSource', function()
    Wait(100)
    print(source) -- expect: S010
end)

-- C006: registered net-safe, but no AddEventHandler anywhere handles it.
RegisterNetEvent('bad:neverHandled') -- expect: C006

-- supports the C006 case in client/main.lua: triggered here, but the client
-- handler was only ever plain AddEventHandler'ed, never RegisterNetEvent'ed.
TriggerClientEvent('bad:neverRegistered', -1)

-- S007: triggered here, but no client file registers a handler for it.
TriggerClientEvent('bad:noClientHandler', -1) -- expect: S007

-- C009: TriggerServerEvent only exists client-side.
TriggerServerEvent('bad:wrongSideServer') -- expect: C009

-- C007/C008: verified only when fxref is available (see the stubbed-fxref
-- pass in tests/test_fxlint.py) -- these are not real natives.
SomeClientOnlyNative() -- expect: C007
SomeUnknownNative() -- expect: C008

-- P001: infinite loop with no Wait()/Delay() anywhere in its body.
while true do -- expect: P001
    print('server-side infinite loop')
end
