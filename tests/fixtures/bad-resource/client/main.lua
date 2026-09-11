-- fxlint bad-resource fixture: client side.
-- Deliberately bad code. Every line meant to trip a rule is marked with
-- `-- expect: RULE_ID` so tests/test_fxlint.py can assert an exact match.

TotalTicks = 0 -- expect: C003

function HelperNotExported() -- expect: C003
    return true
end

-- P002 (per-frame Wait with no adaptive branch), P005 (expensive natives in a
-- per-frame loop), P007 (PlayerPedId() called twice in one per-frame loop).
CreateThread(function()
    while true do -- expect: P007
        Wait(0) -- expect: P002
        local ped = PlayerPedId()
        local ped2 = PlayerPedId()
        local players = GetPlayers() -- expect: P005
        TriggerServerEvent('bad:spam', ped) -- expect: P005
    end
end)

-- P001: infinite loop with no Wait()/Delay() anywhere in its body.
CreateThread(function()
    while true do -- expect: P001
        HelperNotExported()
    end
end)

-- P003: Wait() in the 16..99 range -- fine, but worth reconsidering.
CreateThread(function()
    while true do
        Wait(50) -- expect: P003
    end
end)

-- P004: CreateThread() created inside an event handler -- leaks a thread per event.
RegisterNetEvent('bad:clientHandler', function(data)
    while true do
        Wait(0)
        CreateThread(function() print('leak', data) end) -- expect: P004
    end
end)

-- P006: TriggerClientEvent(..., -1, ...) broadcast from inside a loop.
CreateThread(function()
    while true do
        Wait(0)
        TriggerClientEvent('bad:broadcast', -1, TotalTicks) -- expect: P006
    end
end)

-- C001: legacy Citizen.* forms.
Citizen.CreateThread(function() -- expect: C001
    Citizen.Wait(1000) -- expect: C001
end)

-- C002: GetPlayerPed(-1) instead of PlayerPedId().
local ped3 = GetPlayerPed(-1) -- expect: C002

-- C006: handled locally, but triggered from the server (see server/main.lua)
-- without ever being RegisterNetEvent'ed -- it will never actually arrive.
AddEventHandler('bad:neverRegistered', function() -- expect: C006
    print('will not be delivered')
end)

-- C011: Wait() inside a resource-stop handler (must be synchronous).
AddEventHandler('onClientResourceStop', function(resourceName)
    Wait(100) -- expect: C011
end)

-- S007: triggered here, but no server file registers a handler for it.
TriggerServerEvent('bad:noServerHandler') -- expect: S007

-- C012: exports used without a matching manifest dependency.
exports.someOtherResource:doThing() -- expect: C012

-- C009: TriggerClientEvent only exists server-side.
TriggerClientEvent('bad:wrongSide', -1) -- expect: C009

-- C009: 'source' means nothing useful on the client.
if source then -- expect: C009
    print(source)
end
