--- fxlint fixture -- core plugin, server side.

-- K003: Core.Commands.register / Core.Net.emit exist for exactly this.
RegisterCommand('badcmd', function(src)                -- expect: K003
    TriggerClientEvent('core_plugin_bad:client:ping', src)  -- expect: K003
end, false)

--- K011: Core.Locale.t reads locales/<lang>.json of THIS resource, but the
--- manifest ships no locales/*.json, so LoadResourceFile never sees them.
local function greet(src)
    return Core.Locale.t('greeting', { name = Core.Player.getName(src) })  -- expect: K011
end

Core.Net.on('core_plugin_bad:server:buy', { 'integer' }, function(src, price)
    if price ~= 5 then return end
    if not Core.Money.remove(src, 'cash', price, 'fixture') then return end
    Core.Notify.send(src, greet(src), 'success')
end)

--- K005: core's owner registry removes everything this resource registered.
AddEventHandler('onResourceStop', function(resource)   -- expect: K005
    if resource ~= GetCurrentResourceName() then return end
    Core.Interactions.removeAll()
    Core.Blips.removeAll()
end)
