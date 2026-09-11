fx_version 'cerulean'
game 'gta5'

author 'MnkyArts'
description 'fivem-dev-kit observability agent: remote screenshot/profile/logs/info/exec for Claude Code, dev-server only.'
version '1.0.0'

-- lua54 'yes' deliberately omitted -- dead no-op on current FXServer builds
-- (see $KIT/DESIGN.md §8).

shared_scripts {
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
}

server_scripts {
    'server/main.lua',
}

-- agent/fxclient-agent.ps1 is deliberately NOT listed in `files` -- it is
-- fetched by the *server* via LoadResourceFile (apiset: shared, no manifest
-- entry required for server-side reads; see docs/fxclient.md) and served
-- back out over our own HTTP handler at GET /agent, never loaded into the
-- client's Lua/NUI runtime.

dependency 'screenshot-basic'
