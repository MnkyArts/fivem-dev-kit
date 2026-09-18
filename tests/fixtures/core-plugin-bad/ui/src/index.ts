// fxlint fixture -- the UI plugin entry done every possible way wrong (core DESIGN §38).
// It never calls the SDK's plugin-definition helper, so the shell rejects the module: expect K015.
import { createApp } from 'vue'
import Page from './Page.vue'

// expect: K017 -- there is exactly one Vue app and it is core's; the shell mounts the page.
const app = createApp(Page)
app.mount('#app')

// expect: K017 -- window.CoreUI is the legacy surface; `usePage` from '@core/ui' is scoped.
const page = window.CoreUI.usePage('core_plugin_bad')

// expect: K017 -- a plugin resource has no NUI callbacks: its page lives in core's frame.
export function close() {
    fetch(`https://${GetParentResourceName()}/close`, { method: 'POST', body: '{}' })
    page.close()
}
