--[[
    Pattern: server writes state bags, client reacts via change handlers

    Purpose:
        The server sets Player(src).state and Entity(veh).state values with
        `replicated = true`; every client (and the server) can then react to
        the change via AddStateBagChangeHandler instead of a bespoke event
        for every field. Shows both state-bag name formats: `player:<id>`
        (via GetPlayerFromStateBagName) and `entity:<netId>` (via
        GetEntityFromStateBagName).

    Side: shared (one file, branches on IsDuplicityVersion() -- the server
        half writes, the client half only ever reads; see the strict-mode
        note below for why that split matters).

    Usage:
        -- from a validated server handler (see patterns/validated-event.lua):
        setPlayerJob(src, 'police')
        setVehicleLock(vehEntity, true, src)

    Dependencies: none.

    Strict mode: with `sv_stateBagStrictMode true`, the server silently
    no-ops every client-originated state-bag write (runtime-facts §4/§15) --
    so clients must only ever *read* state here, never call `.state:set(...)`
    or assign `.state.key = v` themselves. All writes below happen in the
    IsDuplicityVersion() server branch for exactly this reason.

    Verified with fxref on 2026-09-11: AddStateBagChangeHandler,
    GetEntityFromStateBagName, GetPlayerFromStateBagName -- all apiset
    shared. Player(...)/Entity(...) and their .state sugar are scheduler.lua
    Lua constructs, not natives (see runtime-facts §4).
]]

if IsDuplicityVersion() then
    -- ============================== SERVER ==============================

    --- Sets a player's job and replicates it to every client.
    function setPlayerJob(playerSrc, jobName)
        Player(playerSrc).state:set('job', jobName, true) -- true = replicated
    end

    --- Sets a vehicle's lock state + owner and replicates both.
    function setVehicleLock(vehicleEntity, locked, ownerSrc)
        Entity(vehicleEntity).state:set('locked', locked, true)
        Entity(vehicleEntity).state:set('owner', ownerSrc, true)
    end

    -- Call these from your own validated event handlers (see
    -- patterns/validated-event.lua) after checking the caller is allowed to
    -- make the change -- state bags replicate whatever you hand them, they
    -- don't validate anything on their own.
else
    -- ============================== CLIENT ==============================
    -- Read-only reactions. Never .state:set(...) here -- see the strict-mode
    -- note above.

    AddStateBagChangeHandler('job', nil, function(bagName, key, value, reserved, replicated)
        local playerSrc = GetPlayerFromStateBagName(bagName)
        if playerSrc == 0 then return end
        -- e.g. refresh this player's job-dependent UI/blip/loadout
    end)

    AddStateBagChangeHandler('locked', nil, function(bagName, key, value, reserved, replicated)
        local vehicle = GetEntityFromStateBagName(bagName)
        if vehicle == 0 then return end
        -- e.g. reflect the lock state in a nearby "hold E to unlock" prompt
    end)

    AddStateBagChangeHandler('owner', nil, function(bagName, key, value, reserved, replicated)
        local vehicle = GetEntityFromStateBagName(bagName)
        if vehicle == 0 then return end
        -- e.g. only show the unlock prompt to the owning player
    end)
end
