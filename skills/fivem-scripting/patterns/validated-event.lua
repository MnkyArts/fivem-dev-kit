--[[
    Pattern: validated server net-event handler template

    Purpose:
        The shape every server-side RegisterNetEvent handler should follow:
        capture source first, validate types/ranges with early returns, check
        distance/permission where relevant, rate-limit per player, and reject
        with a logged reason instead of silently ignoring bad input. Copy the
        helpers below once per resource, then copy the buyItem handler shape
        per event.

    Side: server.

    Usage:
        Client side fires this with:
            TriggerServerEvent('myres:server:buyItem', 'bread', 2)
        Adjust SHOP_COORDS/MAX_SHOP_DISTANCE/cooldown/ACE object to taste and
        add real money/inventory integration where the comment says to.

    Dependencies: none.

    Verified with fxref on 2026-09-11: GetPlayerPed (client+server, used here
    server-side with an explicit src), GetEntityCoords (client+server),
    IsPlayerAceAllowed (server), GetGameTimer (client+server). source/local
    capture per runtime-facts §15 (source is reset right after the handler
    coroutine starts, so it must be read into a local before any Wait/Await).
]]

local COOLDOWN_MS = 1500
local MAX_BUY_AMOUNT = 20
local SHOP_COORDS = vector3(0.0, 0.0, 0.0) -- replace with your real shop location
local MAX_SHOP_DISTANCE = 5.0

local cooldowns = {} -- [src] = GetGameTimer() of the last accepted request

--- Logs why a request was rejected. Swap print() for your own logger/export.
local function reject(src, reason)
    print(('[validated-event] rejected src=%s: %s'):format(tostring(src), reason))
end

--- ACE permission check helper -- use for anything admin-flavoured.
--- Example: if not hasAce(src, 'command.givemoney') then return reject(src, 'no permission') end
local function hasAce(src, aceObject)
    return IsPlayerAceAllowed(src, aceObject)
end

--- True (and records the hit) if `src` hasn't triggered this within COOLDOWN_MS.
local function checkCooldown(src)
    local now = GetGameTimer()
    local last = cooldowns[src]
    if last and now - last < COOLDOWN_MS then
        return false
    end
    cooldowns[src] = now
    return true
end

-- Per-player tables must be cleaned up on disconnect or they leak for the
-- lifetime of the resource.
AddEventHandler('playerDropped', function()
    local src = source
    cooldowns[src] = nil
end)

RegisterNetEvent('myres:server:buyItem', function(itemName, amount)
    local src = source

    -- 1. type/range checks, early return on anything malformed
    if type(itemName) ~= 'string' or itemName == '' then
        return reject(src, 'invalid itemName')
    end
    amount = tonumber(amount)
    if not amount or amount ~= math.floor(amount) or amount <= 0 or amount > MAX_BUY_AMOUNT then
        return reject(src, 'invalid amount')
    end

    -- 2. rate limit
    if not checkCooldown(src) then
        return reject(src, 'buying too fast')
    end

    -- 3. distance check -- never trust that the client is where it claims;
    --    recompute from the actual server-side ped position.
    local ped = GetPlayerPed(src)
    local playerCoords = GetEntityCoords(ped)
    if #(playerCoords - SHOP_COORDS) > MAX_SHOP_DISTANCE then
        return reject(src, 'too far from the shop')
    end

    -- All checks passed. Integration point: deduct money / add the item
    -- through your economy system (framework export, oxmysql, KVP, ...) --
    -- deliberately not implemented here since it's project-specific.
    TriggerClientEvent('myres:client:itemBought', src, itemName, amount)
end)
