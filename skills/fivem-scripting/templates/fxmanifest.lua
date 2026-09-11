-- Canonical fxmanifest.lua -- copy into a new resource and trim what you don't need.
-- Every key is explained in reference/manifest.md; this file only comments
-- the choices that aren't self-explanatory.

fx_version 'cerulean' -- newest FXv2 tier (adamant < bodacious < cerulean) -- reference/manifest.md
game 'gta5'           -- 'gta5' | 'rdr3' | 'common' -- a resource must declare exactly one

author 'MnkyArts'
description 'Describe what this resource does in one line.'
version '1.0.0'

-- lua54 'yes' is deliberately NOT set here: Lua 5.3 support was removed from
-- FXServer entirely in June 2025, so every script already runs on 5.4
-- regardless of this key -- it's a dead no-op on current builds (see
-- reference/runtime-facts.md §8). Safe to omit.

-- use_experimental_fxv2_oal 'yes' is deliberately NOT set here: enabling it
-- disables vector3 auto-unpacking in native calls -- e.g. SetEntityCoords(ped,
-- coords) would have to become SetEntityCoords(ped, coords.x, coords.y,
-- coords.z) for every vector-taking native in this resource -- and it is
-- still explicitly marked experimental. Only turn it on if you specifically
-- need its corrected native return types and are willing to update every
-- vector argument (see reference/runtime-facts.md §8).

shared_scripts {
    -- '@ox_lib/init.lua', -- uncomment if this resource uses ox_lib (lib.*)
    'shared/config.lua',
}

client_scripts {
    'client/*.lua', -- non-recursive glob; use 'client/**/*.lua' to include subfolders
}

server_scripts {
    'server/*.lua',
}

-- files { 'html/index.html', 'html/script.js', 'html/style.css' } -- static
-- assets clients can fetch (NUI pages, data files, ...); see
-- templates/fxmanifest.nui.lua for a full NUI-enabled example.

-- ui_page 'html/index.html' -- sets this resource's NUI page; see
-- templates/fxmanifest.nui.lua.

dependencies {
    -- 'ox_lib',
}
