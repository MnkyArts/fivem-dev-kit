# fxnew

Scaffolds a new FiveM resource: `fxmanifest.lua`, `shared/config.{lua,js}`,
`client/main.{lua,js}`, `server/main.{lua,js}`, `README.md`, `.fxlintrc.json`,
and (with `--nui`) a minimal `html/` page. Every generated resource is
guaranteed to pass `fxlint` with **0 errors and 0 warnings** -- `fxnew` lints
its own output before reporting success and fails loudly (exit 1) if that
ever regresses, so this isn't just a claim, it's self-checked on every run
(skip the check with `--no-lint-check` if you need to for some reason, e.g.
`fxref` being unavailable making a check slow).

## Usage

```
fxnew <name> [--dir DIR] [--lang lua|js] [--framework standalone|esx|qb|qbox|ox]
             [--ox-lib] [--no-client] [--no-server] [--nui]
             [--author X] [--desc "..."] [--force] [--no-lint-check]
```

| Flag | Default | Notes |
|---|---|---|
| `<name>` | required | Also the directory name. Sanitized to `[a-z0-9_-]` (lowercased, spaces/punctuation collapsed to `-`) if it isn't already safe -- a notice is printed to stderr when this happens. |
| `--dir DIR` | `project.workspace` from config.json | Parent directory the resource is created under (`DIR/<name>`). |
| `--lang lua\|js` | `project.language` from config.json | Selects `.lua` or `.js` for every generated script file. `fxmanifest.lua` itself is always Lua (FiveM requires this regardless of script language). |
| `--framework ...` | `project.framework` from config.json | `standalone` (default), `esx`, `qb`, `qbox`, or `ox`. Adds the framework's dependency and a bootstrap line in `shared/config.{ext}` (see below). |
| `--ox-lib` | off | Adds `'@ox_lib/init.lua'` to `shared_scripts` and `dependency 'ox_lib'`. |
| `--no-client` | off | Skips `client/`. Mutually exclusive with `--no-server` (an empty resource isn't useful). |
| `--no-server` | off | Skips `server/`. |
| `--nui` | off | Adds `html/index.html`, `html/style.css`, `html/script.js`, `ui_page`/`files` in the manifest, and open/close plumbing in `client/main.{ext}`. Requires a client (don't combine with `--no-client`). |
| `--author X` | `project.author` from config.json | |
| `--desc "..."` | `"<name> -- a FiveM resource"` | |
| `--force` | off | Overwrite an existing directory of the same name. Without it, `fxnew` refuses (exit 1) rather than silently merge into/clobber something that's already there. |
| `--no-lint-check` | off | Skip the post-generation fxlint self-check. |

## What gets generated

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
fxnew my-garage
fxnew my-shop --framework qb --ox-lib
fxnew my-hud --lang js --no-server
fxnew my-menu --nui --author "Jane Doe" --desc "A simple radial menu"
fxnew existing-thing --force        # overwrite what's there
```

Every one of the above (plus every `--framework`/`--nui`/`--ox-lib`
combination) is exercised by `tests/test_fxnew.py`, each asserted to lint
with 0 errors/0 warnings.
