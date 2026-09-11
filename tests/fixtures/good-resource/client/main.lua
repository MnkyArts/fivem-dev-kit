-- fxlint good-resource fixture: a small, realistic zone-reward script.
-- Must lint 100% clean (0 errors, 0 warnings; infos are fine).

local zoneCenter = vector3(100.0, 200.0, 30.0)
local inZone = false

-- Adaptive-wait zone loop: far from the zone we barely check at all; only
-- while actually inside it do we drop to a per-frame Wait to draw the marker.
CreateThread(function()
    while true do
        local ped = PlayerPedId()
        local coords = GetEntityCoords(ped)
        local distance = #(coords - zoneCenter)

        if distance < Config.ZoneRadius then
            inZone = true

            DrawMarker(1, zoneCenter.x, zoneCenter.y, zoneCenter.z, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                Config.ZoneRadius * 2, Config.ZoneRadius * 2, 2.0, 0, 200, 0, 100, false, false, 2, false, nil, nil, false)

            Wait(0) -- per-frame: only while standing inside the zone, to draw the marker smoothly
        else
            inZone = false
            Wait(1000)
        end
    end
end)

RegisterKeyMapping('fxlint_good_claim', 'Claim the zone reward', 'keyboard', 'E')

RegisterCommand('fxlint_good_claim', function()
    if not inZone then
        return
    end

    TriggerServerEvent('fxlintGood:claimReward')
end, false)

RegisterNetEvent('fxlintGood:rewardGranted', function(amount)
    print(('Claimed a reward of %d'):format(amount))
end)
