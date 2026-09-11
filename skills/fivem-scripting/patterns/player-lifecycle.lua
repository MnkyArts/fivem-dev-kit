--[[
    Pattern: player connection lifecycle (connecting / joining / dropped)

    Purpose:
        playerConnecting with deferrals (defer -> update -> done, with the
        required one-tick gap after defer()), playerJoining to populate a
        per-player table once a real server id exists, and playerDropped to
        clean that table up again so it doesn't leak for the life of the
        resource. Plus a small identifier-by-type lookup helper.

    Side: server.

    Usage: copy as-is; replace the placeholder name check in playerConnecting
        with your real allow/ban logic, and read playerData[src] anywhere
        else in your resource after playerJoining has fired for that src.

    Dependencies: none.

    Note: these three are registered with AddEventHandler, not
    RegisterNetEvent -- they are server-internal events, not something a
    client should be able to fake by calling TriggerServerEvent with the same
    name (an event only becomes network-triggerable once RegisterNetEvent
    marks it "safe for net" -- runtime-facts §2).

    Verified with fxref on 2026-09-11: GetPlayerIdentifierByType (apiset
    server). playerConnecting/playerJoining/playerDropped are core server
    events (runtime-facts §9), not natives, so they aren't fxref-checked.
]]

local playerData = {} -- [src] = { identifiers = { license = ..., discord = ... } }

--- Looks up one identifier type for a connected player
--- (identifier types: license, discord, steam, fivem, xbl, live, ...).
local function getIdentifier(src, idType)
    return GetPlayerIdentifierByType(src, idType)
end

AddEventHandler('playerConnecting', function(playerName, setKickReason, deferrals)
    local src = source

    deferrals.defer()
    Wait(0) -- required: at least one tick must pass between defer() and update()/done()

    deferrals.update(('Checking %s...'):format(playerName))

    -- example check: reject an empty name. Replace with your real
    -- allowlist/banlist/whitelist check (can be async: deferrals lets you
    -- Wait/await a DB or HTTP call here before calling done()).
    if playerName == nil or playerName == '' then
        return deferrals.done('Invalid player name.')
    end

    deferrals.done()
end)

-- playerJoining fires once `src` is a stable, final server id (unlike the
-- temporary id playerConnecting sees). Declare zero handler params and read
-- the ambient `source` global -- the event's own first positional argument
-- is documented as unreliable (runtime-facts §9); `oldID` is available as a
-- second param (function(_, oldID)) if you need the temporary id.
AddEventHandler('playerJoining', function()
    local src = source
    playerData[src] = {
        identifiers = {
            license = getIdentifier(src, 'license'),
            discord = getIdentifier(src, 'discord'),
        },
    }
end)

AddEventHandler('playerDropped', function(reason)
    local src = source
    playerData[src] = nil
end)
