-- fxlint fixture: a core plugin that gets every K rule wrong (DESIGN.md section 9.3).
-- Every offending line carries `-- expect: K0xx`; tests/test_fxlint.py asserts them.

fx_version 'cerulean'
game 'gta5'

author 'fixture'
description 'core-plugin-bad -- every K rule fires here'
version '1.0.0'

dependency 'core'

shared_scripts {
    'shared/config.lua',
    '@core/import.lua',                       -- expect: K009 (must be the FIRST entry)
}

-- expect: K014 -- the second glob reaches into ui/dist, and FiveM serves a client_script that is
-- not also a `file` as gameconfig.xml.
client_scripts {
    'client/*.lua',
    'ui/dist/*.js',
}
server_scripts { 'server/*.lua' }

ui_page 'ui/index.html'                       -- expect: K008 (core owns the one CEF page)

-- The opt-in itself is right; everything behind it is wrong (core DESIGN section 38):
-- ui/dist holds an invalid manifest.json and the files glob ships the whole ui/ folder.
core_ui 'ui/dist'

files {
    'ui/**',                                  -- expect: K014 (ships ui/src + ui/dev to players)
}
-- and no 'locales/*.json' although server/main.lua calls Core.Locale.t -> K011
