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

client_scripts { 'client/*.lua' }
server_scripts { 'server/*.lua' }

ui_page 'ui/index.html'                       -- expect: K008 (pages live in core's shell)

files {
    'ui/**',                                  -- expect: K008 (a plugin ships no UI files)
}
-- and no 'locales/*.json' although server/main.lua calls Core.Locale.t -> K011
