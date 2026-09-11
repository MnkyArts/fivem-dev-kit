# Framework adapters

Every pattern in `patterns/` is standalone by design -- no framework calls.
This doc is where framework-specific snippets live instead, for when
`config.json`'s `project.framework` (or the detection checklist below) says
this project actually needs one.

## Detect installed framework

1. Read `config.json`'s `project.framework` first -- it's the authoritative,
   explicit setting for this project (`standalone` by default).
2. If unset/unclear, look in the server's resources directory for one of
   these (first match wins):
   | Resource present | Framework |
   |---|---|
   | `es_extended` | ESX |
   | `qb-core` | QBCore |
   | `qbx_core` | qbox |
   | `ox_core` | ox_core |
3. Check for `ox_lib` and `oxmysql` **independently** of the above -- both
   are commonly layered on top of any framework, or used standalone.
4. When nothing is found: standalone. Never silently assume a framework.

## Standalone (default)

No adapter needed -- this is what every file in `patterns/` already is. Use
`patterns/callback.lua` for client<->server calls, `patterns/player-lifecycle.lua`
for identifiers, plain `TriggerServerEvent`/state bags for everything else.

## ESX (`es_extended`)

`(unverified — check the framework's docs)`: not fetched live for this pass;
this is the long-stable, widely-documented ESX shape.

```lua
-- client
ESX = exports['es_extended']:getSharedObject()

CreateThread(function()
    while ESX.GetPlayerData().job == nil do Wait(0) end
    local playerData = ESX.GetPlayerData()
end)

-- server
ESX = exports['es_extended']:getSharedObject()

RegisterNetEvent('myres:server:buyItem', function(itemName, amount)
    local src = source
    local xPlayer = ESX.GetPlayerFromId(src)
    if xPlayer == nil then return end

    if xPlayer.getMoney() < price then
        return xPlayer.showNotification('Not enough money.')
    end
    xPlayer.removeMoney(price)
    xPlayer.addInventoryItem(itemName, amount)
    xPlayer.showNotification(('You bought %sx %s.'):format(amount, itemName))
end)
```

- Player object: `ESX.GetPlayerFromId(src)` (server), `ESX.GetPlayerData()` (client).
- Money: `xPlayer.getMoney()`, `xPlayer.addMoney(n)`, `xPlayer.removeMoney(n)`
  (and `xPlayer.getAccount('bank').money` / `addAccountMoney`/`removeAccountMoney`
  for non-cash accounts).
- Items: `xPlayer.addInventoryItem(name, count)`, `xPlayer.removeInventoryItem(name, count)`.
- Notify: `xPlayer.showNotification(msg)` (server-forced) or client-side
  `ESX.ShowNotification(msg)`.
- Don't reimplement: money/inventory persistence, job/grade lookups,
  identifiers (`xPlayer.identifier`) -- ESX already owns all of it.

## QBCore (`qb-core`)

Verified 2026-09-11 via `overextended`/`qbcore.org` docs fetch where noted;
`(unverified — check the framework's docs)` elsewhere in this section.

```lua
-- client / server (same export both sides)
QBCore = exports['qb-core']:GetCoreObject()
```

Verified from docs.qbcore.org (`qb-core/server-function-reference`,
`qb-core/client-function-reference`):

```lua
-- server: get the Player object
local Player = QBCore.Functions.GetPlayer(source)

-- server: register + trigger a callback
QBCore.Functions.CreateCallback('resourceName:testCallback', function(source, cb)
    local Player = QBCore.Functions.GetPlayer(source)
    cb(Player)
end)
QBCore.Functions.TriggerClientCallback('resourceName:testCallback', source, function(data)
    print('Received from client:', data)
end)

-- client: current player data (no round-trip needed)
local Player = QBCore.Functions.GetPlayerData()
local jobName = Player.job.name

-- client: call a server callback
QBCore.Functions.TriggerCallback('callbackName', function(result)
    print(result)
end, 'my_parameter_name')

-- client: notify -- (message, type, length)
QBCore.Functions.Notify('This is a test', 'success', 5000)
QBCore.Functions.Notify({ text = 'Test', caption = 'Test Caption' }, 'police', 5000)
```

`(unverified — check the framework's docs)` -- money/item functions (stable,
long-documented shape across the QBCore ecosystem, but not re-fetched live
this pass):

```lua
Player.Functions.AddMoney('cash', amount, 'reason-string')   -- account: 'cash' | 'bank' | 'crypto'
Player.Functions.RemoveMoney('cash', amount, 'reason-string')
Player.Functions.AddItem('item_name', amount, nil, info)
Player.Functions.RemoveItem('item_name', amount)
```

- Player object: `QBCore.Functions.GetPlayer(src)` (server),
  `QBCore.Functions.GetPlayerData()` (client, no round-trip).
- Callbacks: prefer QBCore's own `CreateCallback`/`TriggerCallback` pair over
  `patterns/callback.lua` when QBCore is already the framework -- same idea,
  already wired into the framework's player object.
- Don't reimplement: money/inventory persistence, job/gang lookups --
  `Player.PlayerData.job`/`.gang`.

## qbox (`qbx_core`)

`(unverified — check the framework's docs)`: qbox is a QBCore-compatible
fork; its own docs (docs.qbox.re) weren't fetched this pass. Shape below
matches qbox's documented export-based access pattern (distinct from
QBCore's `GetCoreObject()` global-object pattern):

```lua
-- server
local player = exports.qbx_core:GetPlayer(source)

-- client
local playerData = exports.qbx_core:GetPlayerData()
```

Most `QBCore.Functions.*`/`Player.Functions.*` calls above have a qbox
equivalent (qbox is designed as a compatible superset) -- verify the exact
export name against qbox's own docs before relying on it, since the export
surface is the part most likely to have diverged from QBCore.

## ox_core

`(unverified — check the framework's docs)`: not fetched live this pass.

```lua
local Ox = require '@ox_core.lib.init'

-- server
local player = Ox.GetPlayer(source)

-- client
local player = Ox.GetPlayer(cache.playerId)
```

ox_core leans on `ox_lib`'s `cache` table (see below) and its own statebag
conventions rather than a QBCore/ESX-style monolithic Player object -- expect
a more granular, export/state-bag-driven API. Confirm exact member/method
names against ox_core's own docs before use.

## ox_lib

Verified 2026-09-11: the `shared_scripts` entry below is directly from
overextended.dev/ox_lib. Module call shapes (`lib.callback`, `lib.points`,
`lib.zones`, `lib.notify`, `lib.requestModel`, `lib.addKeybind`, `cache`)
are `(unverified — check the framework's docs)` for this pass -- the module
sub-pages weren't reachable; shapes below match the well-established,
long-stable ox_lib API.

```lua
shared_scripts {
    '@ox_lib/init.lua', -- must be first if other shared_scripts depend on lib.*
}
```
```lua
dependencies { 'ox_lib' }
```

- Callbacks: `lib.callback.register('name', function(source, ...) ... end)`
  (server), `lib.callback.await('name', false, ...)` or the shorthand
  `lib.callback('name', false, cb, ...)` (client) -- prefer this over
  `patterns/callback.lua` whenever ox_lib is already a dependency.
- Points: `lib.points.new({ coords = vector3(...), distance = 10.0 })`, then
  override `onEnter`/`onExit`/`nearby` on the returned point -- replaces
  hand-rolled scheduler loops like `patterns/interaction-zone.lua`.
- Zones: `lib.zones.box({...})` / `lib.zones.poly({...})` / `lib.zones.sphere({...})`.
- Notify: `lib.notify({ description = 'Bought item', type = 'success' })`.
- Model loading: `lib.requestModel(model, timeout)` -- replaces
  `patterns/model-loading.lua`'s `loadModel`.
- Keybinds: `lib.addKeybind({ name = 'myres:brace', description = 'Brace', defaultKey = 'B', onPressed = fn, onReleased = fn })`
  -- replaces `patterns/keymapping.lua`'s +/- command pair.
- `cache.ped` / `cache.vehicle` / `cache.seat` -- cached local player state,
  refreshed automatically; prefer over repeated `PlayerPedId()`/
  `GetVehiclePedIsIn()` calls in a hot loop.

## oxmysql

`(unverified — check the framework's docs)`: not fetched live this pass;
shape is the long-stable, widely-documented oxmysql API.

```lua
-- always parametrized -- never string-concatenate user input into SQL
local rows = MySQL.query.await('SELECT * FROM players WHERE identifier = ?', { identifier })
MySQL.insert.await('INSERT INTO logs (message) VALUES (?)', { message })
MySQL.update.await('UPDATE players SET money = ? WHERE identifier = ?', { money, identifier })
```

Never build a query with `..`/`string.format` on caller-supplied data --
that is the SQL-injection version of the raw-payload trust mistake
`patterns/validated-event.lua` exists to prevent. Parameters (`?` + the
array argument) are the only safe way to include client-supplied values.
