// fxlint fixture -- the UI plugin entry of a correct core plugin (core DESIGN §38.3, §38.7).
// Module scope is for DEFINITIONS only: every side effect lives in setup(ctx) and is disposed
// with the plugin, so a `restart` can never leave a second listener behind.
import { defineUIPlugin, definePage } from '@core/ui'
import Page from './Page.vue'

/** What Core.UI.open('core_plugin_good', ...) sends from client/main.lua. */
export interface GoodProps {
    cash: number
}

export default defineUIPlugin({
    pages: {
        core_plugin_good: definePage<GoodProps>({ component: Page }),
    },
    setup(ctx) {
        ctx.log('activated, generation', ctx.generation)
    },
})
