// fxlint fixture -- a stand-in for the content-hashed bundle `vite build` emits.
// The real one is the plugin ES module core imports; fxlint only checks that manifest.json
// names files that exist.
export default { __coreUIPlugin: true, apiVersion: 1 }
