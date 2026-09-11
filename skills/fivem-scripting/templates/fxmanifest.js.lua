-- fxmanifest.lua -- JavaScript resource (client runs on V8, server runs on
-- Node.js). The manifest file itself is still named fxmanifest.lua and
-- still written in the small manifest-DSL Lua -- only the *scripts* it lists
-- are .js. See templates/fxmanifest.lua for comments on the keys omitted
-- below (lua54, use_experimental_fxv2_oal -- both Lua-only concerns).

fx_version 'cerulean'
game 'gta5'

author 'MnkyArts'
description 'JavaScript resource.'
version '1.0.0'

-- Server JS runs on Node.js 16 by default; opt into Node 22 if you need it
-- (reference/runtime-facts.md §8/§13). Client JS always runs on V8 -- this
-- key only affects the server side.
-- node_version '22'

shared_scripts {
    'shared/config.js',
}

client_scripts {
    'client/*.js',
}

server_scripts {
    'server/*.js',
}

dependencies {
    -- 'ox_lib',
}
