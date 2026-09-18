--- fxlint fixture -- core-plugin-bad-ui, client side. The Lua here is deliberately correct:
--- the only problems in this resource are in fxmanifest.lua (K014, K015), so the test can
--- assert that a broken ui/dist wiring is reported on its own.

Core.onReady(function()
    Core.UI.registerPage('core_plugin_bad_ui', { type = 'page' })
end)
