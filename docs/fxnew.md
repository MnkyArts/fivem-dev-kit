# fxnew

Scaffolds a new FiveM resource. It has **two modes**:

- **`--framework core`** (the default while `project.framework` is `core` in
  `config.json`) — copies `core/templates/plugin` and rewrites its
  placeholders exactly like `core/scripts/new-plugin.sh`. See
  "core plugins" below.
- **every other `--framework`** — the built-in standalone/ESX/QB/qbox/ox
  skeleton described in the rest of this file.

Both modes lint their own output and fail loudly (exit 1) if it is not clean.

The standalone skeleton: `fxmanifest.lua`, `shared/config.{lua,js}`,
`client/main.{lua,js}`, `server/main.{lua,js}`, `README.md`, `.fxlintrc.json`,
and (with `--nui`) a minimal `html/` page. Every generated resource is
guaranteed to pass `fxlint` with **0 errors and 0 warnings** -- `fxnew` lints
its own output before reporting success and fails loudly (exit 1) if that
ever regresses, so this isn't just a claim, it's self-checked on every run
(skip the check with `--no-lint-check` if you need to for some reason, e.g.
`fxref` being unavailable making a check slow).

## Usage

```
fxnew <name> [--dir DIR] [--lang lua|js] [--framework core|standalone|esx|qb|qbox|ox]
             [--ox-lib] [--no-client] [--no-server] [--nui] [--no-ui]
             [--author X] [--desc "..."] [--version 1.0.0] [--force] [--no-lint-check]
```

| Flag | Default | Notes |
|---|---|---|
| `<name>` | required | Also the directory name. Sanitized to `[a-z0-9_-]` (lowercased, spaces/punctuation collapsed to `-`) if it isn't already safe -- a notice is printed to stderr when this happens. |
| `--dir DIR` | `project.workspace` from config.json | Parent directory the resource is created under (`DIR/<name>`). |
| `--lang lua\|js` | `project.language` from config.json | Selects `.lua` or `.js` for every generated script file. `fxmanifest.lua` itself is always Lua (FiveM requires this regardless of script language). |
| `--framework ...` | `project.framework` from config.json | `core` (a core plugin — see below), `standalone`, `esx`, `qb`, `qbox`, or `ox`. The non-core ones add the framework's dependency and a bootstrap line in `shared/config.{ext}` (see below). |
| `--ox-lib` | off | Adds `'@ox_lib/init.lua'` to `shared_scripts` and `dependency 'ox_lib'`. |
| `--no-client` | off | Skips `client/`. Mutually exclusive with `--no-server` (an empty resource isn't useful). |
| `--no-server` | off | Skips `server/`. |
| `--nui` | off | Adds `html/index.html`, `html/style.css`, `html/script.js`, `ui_page`/`files` in the manifest, and open/close plumbing in `client/main.{ext}`. Requires a client (don't combine with `--no-client`). |
| `--author X` | `project.author` from config.json | |
| `--desc "..."` | `"<name> -- a FiveM resource"` | |
| `--force` | off | Overwrite an existing directory of the same name. Without it, `fxnew` refuses (exit 1) rather than silently merge into/clobber something that's already there. |
| `--no-ui` | off | **core mode only.** Deletes the template's `ui/` folder (a plugin with no page). |
| `--version X` | `1.0.0` | `version` in the generated `fxmanifest.lua`. |
| `--no-lint-check` | off | Skip the post-generation fxlint self-check. |

In core mode `--lang`, `--ox-lib`, `--no-client` and `--no-server` are ignored:
the shape of a core plugin is the template's, not fxnew's.


## core plugins (`--framework core`)

With `project.framework == "core"` (or an explicit `--framework core`),
`fxnew <name>` copies `<core>/templates/plugin` to
`<project.workspace>/<name>` — **core itself is only ever read** — and rewrites
every placeholder the way `core/scripts/new-plugin.sh` does, longest first so
`my_plugin` cannot eat the other two:

| placeholder | becomes | example for `shop_robbery` |
|---|---|---|
| `MyPluginPage` | `<CamelName>Page` | `ShopRobberyPage` |
| `MY_PLUGIN` | `<UPPER_NAME>` | `SHOP_ROBBERY` |
| `my_plugin` | `<name>` | `shop_robbery` |

The name must be a valid FXServer resource name (`^[a-z][a-z0-9_]*$`; anything
else is sanitized with a stderr notice), and `core` and `my_plugin` are
rejected outright. `author`, `description` and `version` are then filled into
the copied `fxmanifest.lua` from `--author`/`--desc`/`--version`
(`project.author` is the default author). An existing directory is **never**
overwritten without `--force`.

```
<name>/
  fxmanifest.lua          dependency 'core' + '@core/import.lua' first in shared_scripts
  shared/config.lua       the Config global (both VMs)
  client/main.lua         keys/net/callbacks at file scope, registrations in Core.onReady
  server/main.lua         Core.Net.on / Core.Callback.register / Core.Commands.register
  locales/en.json         Core.Locale.t strings
  ui/src/{index.js,Page.vue}, ui/package.json.example    (unless --no-ui)
  README.md
```

`ui/` is kept by default (like `new-plugin.sh`). `--nui` keeps it and says so
explicitly: the page is **compiled into core's shell** (`cd core/ui && npm run
build`) and the plugin itself ships no UI files, no `ui_page`, no `files {}`
entry. `--no-ui` deletes it.

The generated plugin is linted with the K rules on and must come back at 0
errors / 0 warnings, then the next steps are printed:

```
$ fxnew shop_robbery --author MnkyArts --desc "Rob the 24/7"
fxnew: created .../resources/shop_robbery from .../core/templates/plugin (8 file(s) rewritten)
fxnew: fxlint self-check passed (0 errors, 0 warnings)

next steps:

  1. server.cfg -- start it after core:
       ensure core
       ensure shop_robbery

  2. Write the plugin (shop_robbery/):
       shared/config.lua   the Config global (both VMs)
       client/main.lua     keys/net/callbacks at file scope, registrations in Core.onReady
       server/main.lua     Core.Net.on / Core.Callback.register / Core.Commands.register
       locales/en.json     Core.Locale.t strings ({{var}} placeholders)

  3. The page in shop_robbery/ui/src is compiled into CORE's shell -- this plugin ships no UI files.
       uncomment Core.UI.registerPage('shop_robbery', { type = 'page' }) in client/main.lua
       cd .../resources && npm install      # once, or after adding a ui dependency
       cd .../core/ui && npm run build
       server console: refresh; restart core
     No page? Delete shop_robbery/ui -- a plugin without a page ships no UI files at all.

  4. refresh; ensure shop_robbery
```

Without a `core` block in `config.json`, `--framework core` exits `2` and
points at `--framework standalone`.

## What gets generated (standalone mode)

```
<name>/
  fxmanifest.lua
  shared/config.{lua,js}
  client/main.{lua,js}        (unless --no-client)
  server/main.{lua,js}        (unless --no-server)
  html/{index.html,style.css,script.js}   (only with --nui)
  README.md
  .fxlintrc.json
```

**fxmanifest.lua**: `fx_version 'cerulean'`, `game 'gta5'`, `author`,
`description`, `version '1.0.0'`, `shared_scripts`/`client_scripts`/
`server_scripts` (globs, e.g. `client/*.lua`), `dependencies` (framework +
ox_lib, if any), and (with `--nui`) `ui_page 'html/index.html'` +
`files { 'html/**' }`. Deliberately **never** includes `lua54` (a no-op
since Lua 5.3 was removed) or `use_experimental_fxv2_oal` (real, but changes
vector-argument behaviour -- off by default; add it yourself if you want it,
see `docs/fxlint.md`'s C005 entry for what changes).

**shared/config.{lua,js}**: a `Config` table (`Debug = false`) as a genuine
global (Lua: bare `Config = {...}`; JS: `globalThis.Config = {...}`, not
`const`/`let`, so every other script on that side can see it the same way
Lua's `local`-less globals work), plus the framework bootstrap line if
`--framework` isn't `standalone`:

| Framework | Lua | JS |
|---|---|---|
| esx | `ESX = exports['es_extended']:getSharedObject()` | `globalThis.ESX = exports['es_extended'].getSharedObject();` |
| qb | `QBCore = exports['qb-core']:GetCoreObject()` | `globalThis.QBCore = exports['qb-core'].GetCoreObject();` |
| qbox | `QBCore = exports.qbx_core:GetCoreObject()` | `globalThis.QBCore = exports.qbx_core.GetCoreObject();` |
| ox | `Ox = require '@ox_core.lib.init'` | *(unverified -- left as a `// TODO` comment; ox_core's JS-side API wasn't confirmed against source/docs. Lua's `require '@ox_core...'` form is confirmed correct: it's Lua's paren-less single-string call sugar, resolved by ox's `require` shim the same way `@ox_lib/init.lua` is resolved as a shared script.)* |

qbox's exact bootstrap call is a reasonable best-effort (qbox/`qbx_core` is
designed as a QBCore-API-compatible replacement) but wasn't independently
verified against qbox source, since it isn't checked out in this workspace --
double check it against the qbox docs before relying on it.

**client/main.{lua,js}**: an `onClientResourceStart` guard
(`if GetCurrentResourceName() ~= resourceName then return end`) and nothing
else -- no loops, minimal by design. With `--nui`, also a
`RegisterNUICallback('close', ...)`/`RegisterNuiCallback('close', ...)` that
calls `SetNuiFocus(false, false)`, and a `RegisterCommand('<name>_ui', ...)`
that opens it (`SetNuiFocus(true, true)` + `SendNUIMessage({action='open'})`).

**server/main.{lua,js}**: a `local function debugPrint(...)` gated by
`Config.Debug`, `onResourceStart`/`onResourceStop` guards that call it, and a
**commented-out** example of a properly validated net event -- `source`
captured as the handler's first statement, a `type`/range check on the
payload, a per-player cooldown table, all wired together. It's commented out
on purpose (an unused `RegisterNetEvent` would trip fxlint's own S004) and is
there to copy-paste-adapt, not to run as-is.

**README.md**: purpose, a config table, the file tree, and an **In-game test
checklist** (`- [ ]` bullets) covering `ensure`/`refresh`, an `fxlint` pass,
restart-repeatedly-for-leaks, the NUI open/close flow (if `--nui`), and a
reminder to test the example server event once it's uncommented. Meant to be
extended with resource-specific bullets before shipping, not treated as
exhaustive.

**.fxlintrc.json**: `{"ignore": []}` -- read automatically by `fxlint` when
you run it against this resource directory directly (see `docs/fxlint.md`).

## Examples

```
fxnew shop_robbery                              # a core plugin (project.framework = core)
fxnew shop_robbery --no-ui                      # ... with no page
fxnew my-garage --framework standalone
fxnew my-shop --framework qb --ox-lib
fxnew my-hud --lang js --no-server
fxnew my-menu --nui --author "Jane Doe" --desc "A simple radial menu"
fxnew existing-thing --force        # overwrite what's there
```

Every one of the above (plus every `--framework`/`--nui`/`--ox-lib`
combination) is exercised by `tests/test_fxnew.py`, each asserted to lint
with 0 errors/0 warnings.
