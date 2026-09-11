--[[
    Pattern: enter/exit-driven interaction zone (config list of points)

    Purpose:
        One scheduler thread that adaptively sleeps based on distance to the
        nearest configured point (far = long sleep, near = short sleep), and
        only runs a per-frame draw+keypress loop while the player is actually
        inside a point's activation range -- never a bare per-frame loop that
        runs for the whole resource lifetime.

    Side: client.

    Usage:
        Add entries to Config.points, then TriggerServerEvent (or TriggerEvent
        locally) whatever `event` you configured when the player presses E
        inside range. Adjust ACTIVATE_RANGE/NEAR_RANGE to taste.

    Dependencies: none.

    Key: INPUT_CONTEXT, control index 51, default key E -- verified via
    `fxref docs show docs/game-references/controls` (docs.fivem.net), whose
    own worked example for IsControlJustReleased uses control 51. Control 38
    (INPUT_PICKUP) also defaults to E and is a common alternative; INPUT_CONTEXT
    is the one the docs' own example targets, so this pattern uses that.

    Verified with fxref on 2026-09-11: PlayerPedId, GetEntityCoords,
    IsControlJustReleased, GetScreenCoordFromWorldCoord, SetTextFont,
    SetTextScale, SetTextColour, SetTextCentre, SetTextDropshadow,
    SetTextEdge, BeginTextCommandDisplayText, AddTextComponentSubstringPlayerName,
    EndTextCommandDisplayText -- all apiset client.
]]

local Config = {
    points = {
        { coords = vector3(0.0, 0.0, 0.0), label = 'Interact here', event = 'myres:server:interact' },
    },
}

local ACTIVATE_RANGE = 1.5 -- start the per-frame draw/key loop inside this radius
local NEAR_RANGE = 15.0    -- tighten the scheduler's sleep once within this radius
local INTERACT_CONTROL = 51 -- INPUT_CONTEXT (default key E)

--- Draws `text` at the given world position, only if it's on-screen.
local function drawText3D(coords, text)
    local onScreen, x, y = GetScreenCoordFromWorldCoord(coords.x, coords.y, coords.z)
    if not onScreen then return end

    SetTextScale(0.35, 0.35)
    SetTextFont(4)
    SetTextColour(255, 255, 255, 215)
    SetTextDropshadow(0, 0, 0, 0, 255)
    SetTextEdge(2, 0, 0, 0, 150)
    SetTextCentre(true)
    BeginTextCommandDisplayText('STRING')
    AddTextComponentSubstringPlayerName(text)
    EndTextCommandDisplayText(x, y, 0)
end

--- Nearest configured point to `coords` and the distance to it (or nil, huge).
local function findNearest(coords)
    local nearest, nearestDist = nil, NEAR_RANGE + 1.0
    for i = 1, #Config.points do
        local point = Config.points[i]
        local dist = #(coords - point.coords)
        if dist < nearestDist then
            nearest, nearestDist = point, dist
        end
    end
    return nearest, nearestDist
end

CreateThread(function()
    while true do
        local sleep = 1000
        local ped = PlayerPedId()
        local coords = GetEntityCoords(ped)
        local point, dist = findNearest(coords)

        if point then
            if dist < NEAR_RANGE then
                sleep = 250
            end

            if dist < ACTIVATE_RANGE then
                sleep = 0
                local interacted = false

                -- per-frame: draw/key-check loop only runs while inside ACTIVATE_RANGE
                while dist < ACTIVATE_RANGE do
                    drawText3D(point.coords, ('[E] %s'):format(point.label))

                    if IsControlJustReleased(0, INTERACT_CONTROL) then
                        interacted = true
                        break
                    end

                    Wait(0) -- per-frame: bounded by ACTIVATE_RANGE, ends the moment the player steps out
                    coords = GetEntityCoords(ped)
                    dist = #(coords - point.coords)
                end

                -- fire the event *after* the per-frame loop, not inside it, so
                -- the network call never runs on a per-tick cadence
                if interacted then
                    TriggerServerEvent(point.event)
                end
            end
        end

        Wait(sleep)
    end
end)
