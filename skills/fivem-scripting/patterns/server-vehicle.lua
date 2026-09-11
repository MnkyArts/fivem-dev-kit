--[[
    Pattern: server-authoritative vehicle spawn, ownership, cleanup

    Purpose:
        Spawn a vehicle from a server script (persists without needing a
        client owner nearby), wait until it actually exists before touching
        it, set its plate and a couple of Entity state values, and hand the
        network id to a client so it can resolve the same entity locally.
        Tracks what this resource created so onResourceStop can delete it.

    Side: server.

    Usage:
        local veh, netId = spawnVehicleForPlayer(src, 'adder', someCoords, 0.0)
        if not veh then
            -- spawn failed or timed out
        end
        -- netId is already sent to `src` via 'myres:client:vehicleSpawned'
        -- (see the CLIENT COMPANION comment block at the bottom of this file).

    Dependencies: none.

    Ownership notes:
        A server-created vehicle has no client owner until a nearby client
        claims it (normal OneSync migration). NetworkGetEntityOwner(entity)
        returns -1 until that happens -- don't assume a specific player owns
        it right after spawn; check NetworkGetEntityOwner if you need to know
        who currently controls it before mutating client-authoritative state.

    Verified with fxref on 2026-09-11: CreateVehicleServerSetter (apiset
    server), DoesEntityExist (client+server), SetVehicleNumberPlateText
    (client+server, called here server-side), NetworkGetNetworkIdFromEntity
    (client+server), NetworkGetEntityOwner (shared), DeleteEntity
    (client+server). Entity(veh).state is scheduler.lua sugar, not a native.
]]

local SPAWN_TIMEOUT_MS = 5000

local resourceName = GetCurrentResourceName()
local spawnedVehicles = {} -- entity handles this resource created, for cleanup on stop

--- Spawns `model` at `coords`/`heading` for `src`, waits until it exists,
--- sets plate + Entity state, and hands the netId to `src`. Returns
--- entity, netId on success or nil on failure/timeout.
local function spawnVehicleForPlayer(src, model, coords, heading, vehicleClass, plate)
    local hash = type(model) == 'string' and GetHashKey(model) or model
    local veh = CreateVehicleServerSetter(hash, vehicleClass or 'automobile', coords.x, coords.y, coords.z, heading or 0.0)

    if veh == 0 then
        return nil
    end

    local start = GetGameTimer()
    while not DoesEntityExist(veh) do
        if GetGameTimer() - start > SPAWN_TIMEOUT_MS then
            return nil
        end
        Wait(0) -- per-frame: waiting for the server-created vehicle to exist, bounded by SPAWN_TIMEOUT_MS
    end

    SetVehicleNumberPlateText(veh, plate or ('TMP%04d'):format(math.random(0, 9999)))
    Entity(veh).state:set('locked', false, true)
    Entity(veh).state:set('owner', src, true) -- server id at spawn time; use a stable
                                               -- identifier instead if this must survive reconnects

    spawnedVehicles[#spawnedVehicles + 1] = veh

    local netId = NetworkGetNetworkIdFromEntity(veh)
    TriggerClientEvent('myres:client:vehicleSpawned', src, netId)

    return veh, netId
end

AddEventHandler('onResourceStop', function(stoppedResource)
    if stoppedResource ~= resourceName then return end
    -- synchronous cleanup -- no Wait, the resource is already tearing down
    for i = 1, #spawnedVehicles do
        local veh = spawnedVehicles[i]
        if DoesEntityExist(veh) then
            DeleteEntity(veh)
        end
    end
end)

--[[
    ---------------------------------------------------------------------
    CLIENT COMPANION -- save this half as e.g. client/vehicle-receive.lua
    ---------------------------------------------------------------------

    local RECEIVE_TIMEOUT_MS = 5000

    RegisterNetEvent('myres:client:vehicleSpawned', function(netId)
        local start = GetGameTimer()
        while not NetworkDoesEntityExistWithNetworkId(netId) do
            if GetGameTimer() - start > RECEIVE_TIMEOUT_MS then
                return -- gave up: the entity never reached this client
            end
            Wait(0) -- per-frame: waiting for the netId to resolve locally, bounded by RECEIVE_TIMEOUT_MS
        end

        local veh = NetworkGetEntityFromNetworkId(netId)
        -- veh is now usable like any local entity handle (SetVehicleDoorsLocked, etc.)
    end)

    Verified with fxref on 2026-09-11 (client apiset): NetworkDoesEntityExistWithNetworkId,
    NetworkGetEntityFromNetworkId.
]]
