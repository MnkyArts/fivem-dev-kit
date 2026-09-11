fx_version 'cerulean' -- expect: C005
use_experimental_fxv2_oal 'yes'
author 'fxlint fixtures'
description 'deliberately bad resource for fxlint tests -- every rule should fire at least once'
version '1.0.0'

shared_scripts { 'shared/config.lua' }
client_scripts { 'client/*.lua' }
server_scripts { 'server/*.lua' }
