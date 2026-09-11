# fxmanifest.lua reference

Every resource needs exactly one `fxmanifest.lua` in its root (the legacy
`__resource.lua` name still loads if `fxmanifest.lua` is absent, but never
both -- exactly one is used) (runtime-facts §8). It runs in its own throwaway
Lua state with no `io`/`os` and no `dofile`/`load`/`loadfile` -- you cannot
compute keys dynamically or read other files from it (runtime-facts §8).

See `templates/fxmanifest.lua`, `fxmanifest.nui.lua`, `fxmanifest.js.lua` for
copy-paste starting points.

## Required keys

- **`fx_version 'cerulean'`** -- the FXv2 tier. Below `adamant` (or an
  unrecognized value), the server refuses to start the resource outright
  (runtime-facts §8). Always use `cerulean` for new resources; see "fx_version
  tiers" below for what each tier actually changes.
- **`game 'gta5'`** -- `'gta5'` | `'rdr3'` | `'common'` (game-agnostic,
  Citizen-only APIs). A resource must declare exactly one matching category;
  declaring both `common` and a specific game, or matching neither, gets the
  resource refused at start (runtime-facts §8).

Everything else is optional, but a resource with no scripts and no `game`/
`fx_version` still won't load.

## fx_version tiers (adamant < bodacious < cerulean)

Each tier inherits every effect of the tiers before it (runtime-facts §8).
There is no `lua54`-style "runtime version" implied by any of these -- don't
conflate `fx_version` with the Lua interpreter version (see "Common mistakes").

- **`adamant`** -- the floor. Requires `game` to be set at all (mandatory for
  RedM). Server-side, anything below this (no recognized `fx_version`) is
  refused at start: `"Resource %s does not specify an fx_version..."`
  (runtime-facts §8).
- **`bodacious`** -- implies `clr_disable_task_scheduler` (better third-party
  .NET library compatibility for C# resources, at the cost of needing an
  explicit `await Delay(0);` to hop back to the main thread). The JS runtime
  **stops** aliasing `window` to the global object at this tier and above --
  code written for `bodacious`+ that still does a bare `window.foo` breaks
  silently (runtime-facts §8).
- **`cerulean`** -- NUI resources load in a browser secure context (enables
  WASM/fetch). NUI callback fetches must target `https://cfx-nui-<resource>/`
  or `https://<resource>/`, not the old `nui://`/`http://<resource>/` forms.
  Bumping an older resource's `fx_version` to `cerulean` without checking its
  NUI callback URLs is a silent breakage (runtime-facts §8/§15).

The actual switch that makes native calls fast (`is_cfxv2`) is **not** tied to
`fx_version` at all -- it's set automatically whenever the manifest file is
literally named `fxmanifest.lua` (vs. `__resource.lua`), and your manifest
cannot set or unset it (runtime-facts §8).

## `lua54` and `use_experimental_fxv2_oal`

- **`lua54 'yes'`** -- a dead no-op on every current FXServer build. Lua 5.3
  support was fully removed in June 2025; all Lua scripts already run on 5.4
  regardless of this key (runtime-facts §8). `fxlint`'s C005 rule currently
  still warns if it's missing from a Lua resource -- that warning is safe to
  ignore; this reference and `templates/fxmanifest.lua` deliberately omit the
  key.
- **`use_experimental_fxv2_oal 'yes'`** -- opts into "One Argument List"
  native calls (corrected return types, faster dispatch). Still marked
  experimental, and it **disables `vector3` auto-unpacking**: a call like
  `SetEntityCoords(ped, coords)` must become
  `SetEntityCoords(ped, coords.x, coords.y, coords.z)` for every
  vector-taking native in the resource once this is on (runtime-facts §8).
  Leave it off unless you specifically need the corrected return types and
  are willing to update every vector argument.

## Scripts

- **`client_script(s)` / `server_script(s)` / `shared_script(s)`** -- load a
  file on client/server/both. Extension picks the loader: `.lua` -> Lua,
  `.js` -> V8 (client and server both run JS; server JS is Node.js-backed),
  `.net.dll` -> Mono/.NET (runtime-facts §8). The plural and singular forms
  are the same key (`client_scripts {...}` and `client_script '...'`
  populate the same list) -- use whichever reads better.
- **Globs**: `*.lua` (non-recursive, one folder), `**/*.lua` or `**.lua`
  (recursive), `**/cl_*.lua` (recursive + filename prefix) are all supported
  on script/`data_file` keys (runtime-facts §8).
- **`@resource/file.lua`** -- an include from another resource (e.g.
  `'@ox_lib/init.lua'`). Not itself a manifest key; it's a path convention
  the script host's file resolver understands inside `client_script`/
  `server_script`/`shared_script` entries. Always pair it with a matching
  `dependency` on that resource so start order is enforced.

## Other keys

- **`export` / `server_export`** -- declares a global function name as an
  export from a client/server script. The runtime `exports('name', fn)` call
  is preferred over this static form (runtime-facts §8) -- see
  `reference/events.md` for the export mechanism itself.
- **`ui_page 'html/index.html'`** -- this resource's NUI page (a bundled
  `file`, or an absolute URL). See `templates/fxmanifest.nui.lua`.
- **`files { ... }`** -- adds files to the client download packfile. NUI
  pages need every asset they reference listed here explicitly -- there's no
  implicit "everything under html/" download.
- **`data_file 'TYPE' 'path'`** -- registers an already-`file`'d path with
  the game's extra-content system (`AUDIO_WAVEPACK`, `VEHICLE_METADATA_FILE`,
  `HANDLING_FILE`, ...). Supports globs in the filename.
- **`this_is_a_map 'yes'`** -- marks the resource as a GTA map and reloads
  map storage on load:
  ```lua
  fx_version 'cerulean'
  game 'gta5'
  this_is_a_map 'yes'
  data_file 'DLC_ITYP_REQUEST' 'stream/my_prop.ityp'
  files { 'stream/my_prop.ityp' }
  ```
- **`server_only 'yes'`** -- marks the resource server-only; clients never
  download any of its files:
  ```lua
  fx_version 'cerulean'
  game 'gta5'
  server_only 'yes'
  server_scripts { 'server/*.lua' }
  ```
- **`dependency` / `dependencies`** -- another resource that must load first.
  Also accepts runtime-constraint strings in the same field:
  `/server:<build>` (minimum server build), `/onesync` (state awareness must
  be on), `/gameBuild:<code>`, `/policy:<name>`, `/native:<hash>` (runtime-facts
  §8).
- **`provide 'name'`** -- marks this resource as a drop-in replacement for
  `name`; anything depending on `name` starts this resource instead.
- **`node_version '22'`** -- server JS runtime version; default `16`
  (runtime-facts §8/§13). Client JS always runs on V8 regardless of this key.
- **`convar_category`** -- surfaces convars in FxDK's Project Settings UI;
  see the docs.fivem.net manifest reference for the full table-shorthand
  syntax if you need it (`fxref docs show
  docs/scripting-reference/resource-manifest/resource-manifest`).
- **`escrow_ignore { 'path' }`** -- excludes files from Asset Escrow.

## Canonical examples

**Plain Lua** -- `templates/fxmanifest.lua`.

**NUI** -- `templates/fxmanifest.nui.lua` (adds `ui_page` + `files`).

**JS** -- `templates/fxmanifest.js.lua` (`client/*.js` / `server/*.js`,
optional `node_version`).

**Map**:
```lua
fx_version 'cerulean'
game 'gta5'
this_is_a_map 'yes'
data_file 'DLC_ITYP_REQUEST' 'stream/my_prop.ityp'
files { 'stream/my_prop.ityp' }
```

**Server-only**:
```lua
fx_version 'cerulean'
game 'gta5'
server_only 'yes'
server_scripts { 'server/*.lua' }
```

## Common mistakes

- Setting `lua54 'yes'` expecting it to change runtime behavior -- it does
  nothing on current builds (runtime-facts §8).
- Assuming a higher `fx_version` implies a newer Lua version -- it doesn't;
  Lua version and `fx_version` are unrelated axes (runtime-facts §8).
- Enabling `use_experimental_fxv2_oal` and leaving old
  `Native(ped, coordsVector)`-style calls in place -- they silently pass
  garbage once OAL is on (runtime-facts §8/§15).
- Bumping `fx_version` to `cerulean` on an older NUI resource without
  checking its callback fetch URLs still work under `https://cfx-nui-<resource>/`
  (runtime-facts §15).
- Forgetting `files {}` entries for NUI assets that only `ui_page`'s HTML
  references (CSS/JS aren't auto-included).
- Using `@ox_lib/init.lua` (or any `@resource/...` include) without also
  declaring `dependency 'ox_lib'` -- the include can race the dependency's
  own start.
- Declaring both `client_script` and a stray `__resource.lua` in the same
  resource -- only one manifest file is ever read, so edits to the one that
  isn't loaded silently do nothing (`fxlint` C004 catches a leftover
  `__resource.lua` outright).
