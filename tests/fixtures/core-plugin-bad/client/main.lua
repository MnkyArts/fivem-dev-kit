--- fxlint fixture -- core plugin, client side. Every line marked `-- expect: Kxxx`
--- must produce that rule; see docs/fxlint.md "core conventions (K0xx)".

local PAGE_ID <const> = 'core_plugin_bad'

-- K003: core has Core.Net.on / Core.Keys.register / Core.Net.emit for all of this.
RegisterNetEvent('core_plugin_bad:client:ping')        -- expect: K003
RegisterKeyMapping('+badkey', 'Bad key', 'keyboard', 'F6')  -- expect: K003

--- K001: a callback handed back by core is a callable *table*, never a function.
local function runCallback(cb)
    if type(cb) == 'function' then                     -- expect: K001
        cb()
    end
end

--- K002: the netId has to be checked before it is turned into an entity.
local function paintVehicle(netId)
    local veh = NetworkGetEntityFromNetworkId(netId)   -- expect: K002
    SetVehicleCustomPrimaryColour(veh, 255, 0, 0)
end

--- K012: a plugin never talks to the CEF itself -- core owns the single page.
local function openPanel(data)
    SetNuiFocus(true, true)                            -- expect: K012
    SendNUIMessage({ action = 'open', data = data })   -- expect: K012
end

--- K013: neither of these exists in core's API index.
local function brokenApi(src)
    Core.Money.nope(src, 'cash', 1)                    -- expect: K013
    Core.money.add(src, 'cash', 1, 'typo')             -- expect: K013
end

-- K010: a proxy call at file scope runs before core is up and outside a coroutine.
Core.UI.closeAll()                                     -- expect: K010

-- K004: core forgets this the moment it restarts -- it belongs in Core.onReady.
Core.Interactions.add({                                -- expect: K004
    coords = vector3(25.7, -1347.3, 29.49),
    radius = 2.0,
    label = 'Bad interaction',
    onInteract = function()
        runCallback(openPanel)
        paintVehicle(1)
        brokenApi(0)
    end,
})

Core.UI.registerPage(PAGE_ID, { type = 'page' })       -- expect: K004
