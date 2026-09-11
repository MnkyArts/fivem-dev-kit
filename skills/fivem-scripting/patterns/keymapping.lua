--[[
    Pattern: RegisterKeyMapping + RegisterCommand, with debounce

    Purpose:
        Two worked examples of binding a key to a command instead of polling
        IsControlJustPressed in a per-frame loop:
          1. a simple tap command (debounced) that notifies the server;
          2. a hold-to-act command using the documented +cmd/-cmd convention
             (down = '+name' fires, up = '-name' fires).
        RegisterKeyMapping lets players rebind the key in FiveM's own Key
        Bindings menu -- prefer this over reading raw controls whenever the
        action is "press a key", not "hold a control while driving/aiming".

    Side: client.

    Usage:
        Rename the command/event strings, then adjust the default key
        ('defaultMapper' 'keyboard', 'defaultParameter' the key letter).
        Players can still rebind both from Settings > Key Bindings > FiveM.

    Dependencies: none.

    Server-notify example: the matching server-side listener (put in a
    server script, see patterns/validated-event.lua for the full validation
    shape):
        RegisterNetEvent('myres:server:honk', function()
            local src = source
            -- ...
        end)

    Verified with fxref on 2026-09-11: RegisterKeyMapping (apiset client),
    GetGameTimer (client+server); RegisterCommand/TriggerServerEvent are
    runtime globals (scheduler.lua, apiset shared/client respectively).
]]

-- 1. simple tap command, debounced -------------------------------------

local DEBOUNCE_MS = 500
local lastHonkAt = 0

RegisterCommand('myres:honk', function()
    local now = GetGameTimer()
    if now - lastHonkAt < DEBOUNCE_MS then
        return
    end
    lastHonkAt = now

    TriggerServerEvent('myres:server:honk')
end, false)

RegisterKeyMapping('myres:honk', 'Honk the horn', 'keyboard', 'H')

-- 2. hold-to-act command, +cmd/-cmd convention ---------------------------

local isBracing = false

RegisterCommand('+myres:brace', function()
    if isBracing then return end
    isBracing = true
    -- start whatever "holding" behaviour this represents
end, false)

RegisterCommand('-myres:brace', function()
    if not isBracing then return end
    isBracing = false
    -- stop it
end, false)

RegisterKeyMapping('+myres:brace', 'Brace (hold)', 'keyboard', 'B')
