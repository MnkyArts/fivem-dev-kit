--[[
    Pattern: resource start/stop guards + tracked-object cleanup

    Purpose:
        onResourceStart (server) / onClientResourceStart (client) fire for
        EVERY resource's start, so both need the
        `if startedResource ~= resourceName then return end` guard. Anything
        this resource creates that survives past the resource stopping on its
        own (blips, in this example) gets tracked in a table and deleted
        synchronously in onResourceStop. A long-running background thread
        uses a `stopFlag` so its own loop condition ends it cleanly instead
        of just being torn down mid-body.

    Side: shared (one file; branches on IsDuplicityVersion() so the same
        resourceName/stopFlag/onResourceStop logic serves both sides without
        duplicating it into two files).

    Usage: copy as-is, replace the placeholder blip with whatever this
        resource actually creates (peds, objects, blips, ...), and put real
        periodic work in the background thread.

    Dependencies: none.

    Verified with fxref on 2026-09-11: GetCurrentResourceName (apiset
    shared), AddBlipForCoord / SetBlipSprite / RemoveBlip (client+server, used
    here client-side), DoesEntityExist / DeleteEntity (client+server, listed
    for completeness if you track entities instead of/alongside blips).
]]

local resourceName = GetCurrentResourceName()
local stopFlag = false
local trackedBlips = {} -- client: blips this resource created

-- Long-running background work lives at top level (not inside a start
-- handler) so it's created exactly once, when this file loads, and exits on
-- its own via stopFlag rather than needing to be torn down forcibly.
CreateThread(function()
    while not stopFlag do
        -- periodic upkeep for this resource goes here
        Wait(60000)
    end
end)

if IsDuplicityVersion() then
    -- SERVER: onResourceStart fires here too (see module comment above).
    AddEventHandler('onResourceStart', function(startedResource)
        if startedResource ~= resourceName then return end
        print(('^2[%s]^7 server-side started'):format(resourceName))
    end)
else
    -- CLIENT
    AddEventHandler('onClientResourceStart', function(startedResource)
        if startedResource ~= resourceName then return end

        local blip = AddBlipForCoord(0.0, 0.0, 0.0) -- replace with a real location
        SetBlipSprite(blip, 1)
        trackedBlips[#trackedBlips + 1] = blip
    end)
end

-- onResourceStop also fires on both sides; cleanup here must be synchronous
-- (no Wait) since the resource may already be torn down by the time an
-- async wait would resume.
AddEventHandler('onResourceStop', function(stoppedResource)
    if stoppedResource ~= resourceName then return end

    stopFlag = true -- lets the background thread above end its own loop cleanly

    for i = 1, #trackedBlips do
        RemoveBlip(trackedBlips[i])
    end
end)
