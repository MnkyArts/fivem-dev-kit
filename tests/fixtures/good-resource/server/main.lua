-- fxlint good-resource fixture: validated server event with a per-player
-- cooldown, plus a state bag write. Must lint 100% clean.

local claimCooldowns = {}

RegisterNetEvent('fxlintGood:claimReward', function()
    local src = source -- capture immediately: 'source' resets after a Wait

    local last = claimCooldowns[src]
    local now = GetGameTimer()

    if last and (now - last) < Config.Cooldown then
        return
    end

    local ped = GetPlayerPed(src)
    if not ped or ped == 0 then
        return
    end

    claimCooldowns[src] = now

    Entity(ped).state:set('lastReward', now, true)

    TriggerClientEvent('fxlintGood:rewardGranted', src, Config.RewardAmount)
end)

AddEventHandler('playerDropped', function()
    local src = source
    claimCooldowns[src] = nil
end)

-- S003: a payload player id is fine to act on once it's type-checked AND
-- guarded (here: a role check via Jobs.IsPolice plus a distance check
-- against the fetched ped) -- must not be flagged.
local Jobs = { IsPolice = function(src) return true end }
RegisterNetEvent('police:cuff', function(targetId)
    local src = source
    if type(targetId) ~= 'number' or targetId == src then return end
    if not Jobs.IsPolice(src) then return end
    local a, b = GetPlayerPed(src), GetPlayerPed(targetId)
    if a ~= 0 and b ~= 0 and #(GetEntityCoords(a) - GetEntityCoords(b)) < 2.5 then
        TriggerClientEvent('police:getCuffed', targetId)
    end
end)
