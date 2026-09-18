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

-- This resource owns its frontend (core DESIGN §38): ui/src is built into the committed ui/dist,
-- `core_ui` is the opt-in core probes for, and the CEF imports the module from
-- https://cfx-nui-core-plugin-good/ui/dist/ at runtime. Core is never rebuilt for it.
core_ui 'ui/dist'

-- Only files listed here are packed for the client, and the CEF can fetch nothing else.
-- Core.Locale.t reads locales/<lang>.json of THIS resource, so they must ship too.
files {
    'locales/*.json',
    'ui/dist/**',
}
