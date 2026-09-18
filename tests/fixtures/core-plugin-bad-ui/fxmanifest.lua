-- fxlint fixture: a core plugin whose UI wiring is broken in the two ways the first bad fixture
-- cannot also hold (core DESIGN section 38.4). Everything else about it is correct, so the only
-- findings here are K014 and K015.
--
-- 1. `core_ui` promises core a frontend under ui/dist, but no files {} entry packs it for the
--    client -- the CEF resolves https://cfx-nui-core-plugin-bad-ui/ui/dist/... to a 404.
-- 2. Nothing is built there and there is no ui/src to build it from, so the promise can never
--    be kept: core prints a loud error for this resource on every start.

fx_version 'cerulean'
game 'gta5'

author 'fixture'
description 'core-plugin-bad-ui -- core_ui without a build behind it'
version '1.0.0'

dependency 'core'

shared_scripts {
    '@core/import.lua',
    'shared/config.lua',
}

client_scripts { 'client/*.lua' }

core_ui 'ui/dist'                             -- expect: K014 (nothing in files {} covers it)
                                              -- expect: K015 (and nothing is built there)

files { 'locales/*.json' }
