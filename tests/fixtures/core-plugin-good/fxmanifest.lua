-- fxlint fixture: a correct core plugin, shaped like resources/core_example.
-- It must stay at 0 errors / 0 warnings with the K rules on.

fx_version 'cerulean'
game 'gta5'

author 'fixture'
description 'core-plugin-good -- the shape every core plugin should have'
version '1.0.0'

dependency 'core'

shared_scripts {
    '@core/import.lua',
    'shared/config.lua',
}

client_scripts { 'client/*.lua' }
server_scripts { 'server/*.lua' }

-- No UI files: a page would live in <plugin>/ui/src and compile into core's shell.
-- Core.Locale.t reads locales/<lang>.json of THIS resource, so they must ship.
files { 'locales/*.json' }
