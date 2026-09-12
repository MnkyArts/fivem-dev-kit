--- core-plugin-good -- client side.
-- In-VM registrations (Core.Net.on, Core.Keys.register, Core.UI.on) stay at file scope;
-- everything that registers something INSIDE core goes into Core.onReady, which core
-- replays after every core restart. Core's owner registry cleans it all up on stop.
--
-- Natives used (verified with fxref): PlayerPedId, GetEntityHealth, GetEntityMaxHealth,
-- SetEntityHealth.

local MARKER <const> = {
    type = 1,
    size = vector3(1.5, 1.5, 0.5),
    color = { 0, 255, 255, 140 },
    drawDistance = 30.0,
    offsetZ = -0.9,
}

--- Buy a snack: core's progress bar awaits in this coroutine, then the server decides.
local function buySnack()
    if not Core.isReady() then return end
    if Core.UI.progress({ label = 'Buying...', duration = 2000, canCancel = true }) then
        Core.Net.emit('core_plugin_good:server:buySnack')
    end
end

--- Server -> client: the snack was paid for, apply the heal. Schema-checked.
Core.Net.on('core_plugin_good:client:snack', { 'integer' }, function(heal)
    local ped = PlayerPedId()
    local health = GetEntityHealth(ped)
    if health <= 0 then return end
    SetEntityHealth(ped, math.min(health + heal, GetEntityMaxHealth(ped)))
end)

--- A rebindable key instead of a polled control (zero per-frame cost).
Core.Keys.register({
    name = 'snack',
    key = 'F5',
    description = 'Buy a snack',
    onPress = buySnack,
})

Core.onReady(function()
    Core.Blips.add({
        coords = Config.Shop.coords,
        sprite = 52,
        color = 2,
        label = 'Snack shop',
        shortRange = true,
    })

    Core.Interactions.add({
        coords = Config.Shop.coords,
        radius = Config.Shop.radius,
        label = 'Buy a snack',
        marker = MARKER,
        cooldown = 1000,
        onInteract = buySnack,
    })
end)
