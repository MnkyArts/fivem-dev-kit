-- fxmanifest.lua -- NUI-enabled resource (pairs with patterns/nui-bridge.lua
-- + patterns/nui/index.html + script.js + style.css, copied here as html/*).
-- See templates/fxmanifest.lua for comments on the keys omitted below
-- (lua54, use_experimental_fxv2_oal).

fx_version 'cerulean'
game 'gta5'

author 'MnkyArts'
description 'NUI-enabled resource.'
version '1.0.0'

shared_scripts {
    'shared/config.lua',
}

client_scripts {
    'client/*.lua', -- e.g. a copy of patterns/nui-bridge.lua
}

server_scripts {
    'server/*.lua',
}

-- The NUI page itself (a bundled file, not a URL). Since fx_version is
-- 'cerulean' or later, the page loads in a browser secure context and its
-- callback fetches must target https://cfx-nui-<resource>/... or
-- https://<resource>/... (GetParentResourceName() builds this for you) --
-- see reference/manifest.md.
ui_page 'html/index.html'

-- Every file the client needs to download must be listed here, including
-- ones only ui_page's own <script>/<link> tags reference -- NUI pages don't
-- get an implicit "everything in html/" download like client_scripts globs.
files {
    'html/index.html',
    'html/script.js',
    'html/style.css',
}

dependencies {
    -- 'ox_lib',
}
