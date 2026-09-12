--- core-plugin-good -- server side.
-- Net handlers, callbacks and commands are in-VM libs: file scope, not Core.onReady.
-- The server owns the price, the money and the distance check; the client only asks.

--- One snack, charged once.
---@param src integer
---@return boolean sold
local function sellSnack(src)
    if not Core.Money.remove(src, 'cash', Config.SnackPrice, 'snack') then
        Core.Notify.send(src, Core.Locale.t('broke'), 'error')
        return false
    end
    Core.Net.emit(src, 'core_plugin_good:client:snack', Config.SnackHeal)
    return true
end

--- The wrapper checks the schema, the per-src cooldown, the session and the distance
--- to the shop before this handler ever runs.
Core.Net.on('core_plugin_good:server:buySnack', {}, function(src)
    if not sellSnack(src) then return end
    Core.Notify.send(src, Core.Locale.t('bought', {
        price = Core.Utils.formatMoney(Config.SnackPrice),
    }), 'success')
end, {
    cooldown = 1000,
    requireLoaded = true,
    distance = { coords = Config.Shop.coords, max = 4.0 },
})

--- Everything the client may display is looked up here.
Core.Callback.register('core_plugin_good:getCash', function(src)
    if not Core.Player.isLoaded(src) then return nil end
    return Core.Money.get(src, 'cash')
end)

--- /snack -- anyone may use it, the handler still validates the caller.
Core.Commands.register('snack', { description = 'Buy a snack' }, function(src)
    if src == 0 then
        Core.Log.info('/snack needs a player')
        return
    end
    sellSnack(src)
end)

Core.on('playerLoaded', function(src)
    Core.Log.debug('core-plugin-good: %d loaded', src)
end)
