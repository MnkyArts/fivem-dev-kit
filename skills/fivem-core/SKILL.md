---
name: fivem-core
description: Rulebook for Liam's own FiveM framework `core` and the plugins built on it. Use for the core framework, a core plugin, any `Core.` API (Core.Net/Callback/UI/Money/Factions/Vehicles/Interactions/Markers/DB/Doors/Stats/...), `@core/import.lua`, core_example, the Vue/Tailwind shell in `core/ui`, plugin pages, the Postgres document store — and for any resource in `resources/`, since they all follow core/AGENTS.md.
---

# core framework — plugins and core itself

`core` (`$CORE` = `resources/core`, path in `${CLAUDE_PLUGIN_ROOT}/config.json` → `core.path`) is a Lua 5.4,
standalone, no-ox_lib framework with **one** Vue/Tailwind CEF shell; a plugin is an ordinary resource with
`dependency 'core'`. This skill sits **on top of** `fivem-scripting` — every rule there (no native from memory,
`local src = source`, no loop without `Wait`, server authority, rate limits) still applies — and mirrors core's
own `AGENTS.md`, which stays the working agreement.

## 1. Sources of truth — in this order

| file | what it settles |
|---|---|
| `$CORE/AGENTS.md` | the working agreement (§1 truth, §2 layout, §3 rules, §4 plugins, §5 verify, §6 change protocol, §7 DB, §8 gotchas). Read it before touching anything; never contradict it. |
| `$CORE/DESIGN.md` §0–§33 | the binding contract. **Later sections override earlier ones**; §14, §29, §30, §30.1 are review-driven amendments. Cite `§n` when you quote a rule. |
| `$CORE/README.md` | integrator guide: install, "Writing a plugin", "API cheat sheet", "UI", "Plugin pages", "Styling with Tailwind", "Game blur", hooks/state bags, in-game checklist, troubleshooting. |
| `$CORE/types/core.lua` | LuaLS `---@meta` stubs: ~404 functions in ~45 namespaces, `(server)`/`(client)` markers in the descriptions, `---@class Core*Options` tables, `---@alias CoreHook` and the other enums. |

`fxref core` is the **index of `types/core.lua`** — use it for every `Core.*` call exactly like `fxref show`
for a native (kit DESIGN §9.2): `fxref core search "give money" --side server` · `show Money.add` · `resolve
Core.UI.open Core.Money.add` · `ns` (counts, side mix, lib/proxy) · `hooks` · `classes`, `--json` everywhere;
`show` takes `Money.add`, `Core.Money.add` or `money.add`. **Never write a `Core.*` call you have not resolved
this session** — the card gives side, lib-or-proxy, params, `design_ref`. Not built yet? Then `grep -n
'^function Core\.' $CORE/types/core.lua`, never memory. `core_example` shows every rule below; copy its shapes.

## 2. Two modes

**(a) Writing a plugin** — the default. A plugin is a separate resource; never edit core for something that
belongs in a plugin: inventory/items, jobs, character creator, garages, housing, voice, radial menu and nametags are plugin territory on purpose (DESIGN §13).

**(b) Changing core itself** — contract first (AGENTS §6). One change moves **together**: the `DESIGN.md`
section → the code → `README.md` → the `types/core.lua` stub → tests (server logic ⇒ `tests/server_tests.lua`
+ `tests/stubs.lua`; new lib ⇒ `tests/run_tests.lua`; new shell action ⇒ a `ui/tests/shell-regression.js` check
**and** a Storybook story). Multi-agent work appends a run table to `$CORE/PLAN.md`; every subagent gets exact
file ownership, parallel runs never share a file, scratch files live in the session scratchpad under a
run-named folder, and the orchestrator re-runs lint and tests itself before believing a report. Commits
`<area>: <imperative summary>` (`ui:`, `db:`, `client:`), body says *why* (`html/` is committed on purpose);
Rebar inspired the API surface only — never copy its code.

## 3. Plugin anatomy

Scaffold with `fxnew <name>` (core plugin by default) or `$CORE/scripts/new-plugin.sh <name>`; both copy
`$CORE/templates/plugin` and rewrite `my_plugin` / `MyPluginPage` / `MY_PLUGIN`. The manifest:

```lua
fx_version 'cerulean'   game 'gta5'   dependency 'core'     -- core must be started first
shared_scripts { '@core/import.lua', 'shared/config.lua' }  -- import.lua FIRST, always
client_scripts { 'client/*.lua' }  server_scripts { 'server/*.lua' }  files { 'locales/*.json' }
```

- `'@core/import.lua'` missing/not first or no `dependency 'core'` ⇒ `attempt to index a nil value (global 'Core')` (**K009**). No `ui_page`, no `html/**`, no `ui/**` in a plugin manifest. List the natives a file uses in its header comment (AGENTS §3).
- **The onReady rule** (AGENTS §4.1, DESIGN §2.4) — registrations *inside* core (`Markers.add`,
  `TextLabels.add`, `Blips.add`, `Interactions.add`/`addGlobal`/`addFor`, `Doors.register`, `UI.registerPage`,
  cron jobs) go **inside `Core.onReady(function() … end)`**, which replays after every core restart; in-VM
  registrations (`Core.Net.on`, `Callback.register`, `Commands.register`, `Keys.register`, `UI.on`, `Core.on`)
  stay at **file scope**; also `Core.onPlayerLoaded(fn)` (client) / `Core.on('playerLoaded', fn)` (server).
  **K004** — "everything vanished after `restart core`" is always this rule.
- **Never write an `onResourceStop` cleanup** for core registrations — `Core.Registry` tracks each one under the calling resource and removes it when that resource stops (DESIGN §2.3; **K005**).
- Prefix every event, callback, command and page id with the resource name (`my_plugin:server:buy`). `Config`
  (a deliberate global) lives in `shared/config.lua`, loaded in both VMs; core's own config is `Core.Config`
  inside a plugin, never the `Config` global (§2.0). Locale strings: `locales/<lang>.json` with `{{var}}`
  placeholders, listed in `files {}`, read with `Core.Locale.t('key', { name = x })` — your file first, then
  core's, then the key (§26; **K011**).
- No `package.json`/`node_modules` inside a resource: FXServer's Node sandbox refuses modules behind the
  symlinked path and its `yarn` builder would run on every start (AGENTS §3; **K007**). Node code is bundled
  (`core/ui` → `server/db_pg.js`); `ui/package.json.example` is the one exception the template ships.

## 4. The API map

Two access classes (§2.1/§2.2; `fxref core show` prints which). **lib** = compiled into *your* VM by
`import.lua`, no hop, callable anywhere (`LIB_MODULES`: Utils, Math, Validate, Log, Callback, Net, Commands,
Keys, Streaming, Anim, Player, UI, Locale, Audio). **proxy** = one `exports.core:call` msgpack hop into core:
needs core **started** and a **coroutine** (thread, handler, command, `onReady` body) — never at file scope,
never per frame (**K010**); yielding calls (`UI.progress`, `UI.menu.open`, `Callback.await*`) suspend you.

| namespace | side | access | for |
|---|---|---|---|
| `Utils` `Math` `Validate` `Log` `Locale` | both | lib | guards, table/string/vector helpers, `sanitize`, `formatMoney`; distance/heading/zone math; the one validator (`check`/`checkTable`/`value` → `ok, err`, never throws); `info/warn/error/debug` + server `audit`; `t(key, vars)` (§3.1–§3.4, §26) |
| `Callback` `Net` `Commands` | both | lib | RPC (`register`/`await`/`awaitClient`); validated net events (`on`/`emit`/`broadcast`); typed commands (§3.5–§3.7) |
| `Keys` `Streaming` `Anim` `Audio` `Player` (reads) | client | lib | rebindable keybinds; model/dict load with timeout + release; anims; frontend sounds; state-bag reads `isLoaded` `get` `getServerId` `getPed` `getCoords` `getFaction` `onChange` (§3.8–§3.11, §20) |
| `DB` `Player` | server | proxy | the document store (`create/get/set/update/delete/find/findOne/all/count/nextId/migrate/export/import`; adapters `kvp` default, `postgres` production, `mysql` untested — schema changes are `DB.migrate` functions, never hand-edited rows, and `/dbimport` is only safe with nobody online, AGENTS §7); sessions, persistence, `getData/setData`, kick/ban/respawn/setCoords, §17 ped control, §22 getters (§4.1, §4.2, §27) |
| `Money` `Perms` `Notify` `Factions` `Vehicles` | server (Vehicles both) | proxy | `get/add/remove/set/canAfford/transfer` (integers only); `has/getGroup/setGroup/grant`; `send`/`broadcast`; faction create/invite/rank/kick/bank; vehicle spawn, keys, ownership, records — client: closest/current, props, locks (§4.3–§4.7, §6.8, §22) |
| `Markers` `TextLabels` `Blips` `Interactions` `Doors` | both | proxy | client `add/update/remove/removeAll`, server `addGlobal/addFor/updateGlobal/removeGlobal`; doors `register/setLocked/toggle/canUse` (§6.4–§6.7, §15, §16) |
| `World` `Screen` `Cron` `Stats` `Weapons` | server | proxy | time/weather global + per player; fades/effects/timecycles; `every/at/schedule`; needs with decay+thresholds; persisted loadouts (§17–§19) |
| `Native` `Attachments` `Waypoint` `Screenshot` (server) · `Spawn` `Raycast` (client) | both | proxy | remote client control: allowlisted native invoke, props, waypoints, `screenshot-basic`; spawn/appearance/teleport, camera and point raycasts (§6.1, §6.9, §20) |
| `UI` | both | proxy | pages and every built-in; the server forms take `src` first; the sub-namespaces `menu` `input` `alert` `progress` `textUI` `hud` `keys` `spinner` `stats` `state` `locale` proxy too (§6.10, §21, §31, §32) |
| `Globals` `Services` `Api` `Chat` `Http` `Webhook` `Security` | server | proxy | persisted server-wide values, swappable interfaces, plugin-to-plugin tables; chat channels/filters; `fetch`/`route`/tokens; Discord embeds from convars; `setDamageFilter` (§22–§25) |
| `Registry` | both | **blocked** | core-internal — blocked through the export with `DB.setAdapter`, `DB.markDegraded`, `Player.loadSession/loadAllConnected/startAutosave/stopAutosave` (AGENTS §3) |

On `Core` itself: `name` `isServer` `isClient` `isCore` `version` `Config`, `on(hook, fn)` `emitHook`
`isReady()` `onReady(fn)` `onPlayerLoaded(fn)` (§2.4); server sugar `Core.Player(src):getInfo()` and
`Core.Player(src).money:add('cash', 10)` map to `Core.Player.*`/`Core.Money.*`, nothing else. Hooks are local
events on the same side (`Core.on('moneyChanged', …)`, full list `fxref core hooks`); state bags are
**server-written, client-read** (`sv_stateBagStrictMode true`) — `Core.Player.get(key)`, `Entity(veh).state.x` (§8). No `Core.Getters` exists: the §22 getters sit on `Core.Player`/`Core.Vehicles`.

## 5. Server rules

The server decides; the client is an input device and a renderer (AGENTS §3). Register **every** net event with
`Core.Net.on` — the wrapper enforces `local src = source` → schema → cooldown → `requireLoaded` → `permission` → `distance` → handler (in `pcall`), and rejections are silent unless you pass `onReject` (§3.6, §5):

```lua
Core.Net.on('my_plugin:server:buy', { { 'integer', min = 1, max = 10 } }, function(src, amount)
    if not Core.Money.remove(src, 'cash', amount * Config.Price, 'snack') then return end  -- our price, not theirs
    Core.Net.emit(src, 'my_plugin:client:bought', amount)
end, {
    cooldown = 1000, requireLoaded = true,   -- ms per src (cleared in playerDropped) · session must exist
    permission = 'core.admin',               -- optional; ACE + the Core.Perms group fallback
    distance = { coords = Config.Shop.coords, max = 4.0 },   -- #(ped coords - coords) <= max
})
```

- Schema specs (`Core.Validate`, §3.3): `'integer' 'number' 'string' 'boolean' 'table' 'function' 'any'
  'vector3' 'netId' 'src' 'id'`, `{ 'integer', min =, max = }`, `{ 'string', min =, max =, pattern = }`,
  `{ 'enum', 'cash', 'bank' }`, `{ 'array', of =, max = }`, `{ 'table', keys = {…}, max = }`; a trailing `?` or
  `optional = true` allows `nil`; `{}` = no arguments. Validate callback args too — they are client input.
- RPC `Core.Callback.register(name, fn(src, …))` + `await(name, …)` (client→server, `nil` on timeout) /
  `awaitClient(src, name, …)` (§3.5). Commands: `Core.Commands.register(name, opts, handler(src, args, raw))`
  with `params`/`permission`/`allowConsole` — console is `src == 0` and always passes the check, so handle
  that branch first. **Money only through `Core.Money`** (integers), **persistence only through `Core.DB`
  collections** — never your own files, `SaveResourceFile` or a second database (AGENTS §4.3).
- A callback that crossed the export hop is a **callable table**: test `Core.Utils.isCallable(v)`, never
  `type(v) == 'function'` (**K001**). `Core.Utils.sanitize(s, maxLen)` every string a player typed before
  storing, printing or sending it to the UI; `Core.Log.audit(category, src, …)` for privileged actions, and
  never log identifiers beyond `src` + name. Raw `RegisterNetEvent`/`RegisterCommand`/`TriggerClientEvent` in
  a plugin is **K003** — go through core.

## 6. Client rules

- Markers, text labels, blips and interactions go through core's APIs: core runs **one** scan loop and **one**
  draw loop for every resource (§6.3, §9) — never write your own proximity loop, no `Wait(0)` unless something
  is drawn now. Interaction handlers (`onEnter`/`onExit`/`onInteract`, server also `canInteract(src)`) fire
  once each — the right place to show or hide UI.
- Keys through `Core.Keys.register({ name, key, description, onPress, onRelease?, debounce? })` — a
  `+cmd`/`-cmd` pair plus `RegisterKeyMapping`, zero per-frame cost, ignored while NUI has focus; never poll a
  control (AGENTS §3). UI from Lua: `Core.UI.textUI.show(key, text)`, `notify`, `progress(opts)`,
  `menu.open(opts)`, `input.open(opts)`, `alert(opts)`, `keys.show(hints)` — the awaiting ones need a
  coroutine (handler, command, `onInteract`), never file scope.
- Net ids: call `NetworkDoesEntityExistWithNetworkId(netId)` **before** `NetworkGetEntityFromNetworkId` or
  `GetEntityFromStateBagName('entity:…')` — FiveM logs `GetNetworkObject: no object by ID` for every id this
  client does not hold, and entity bags reach out-of-scope clients (AGENTS §3, DESIGN §30.1; **K002**). A
  state-bag change handler never fires for a key that existed before your script started — seed on load (§8).
- Player facts are `Core.Player` lib state-bag reads (no hop); models/anims via `Core.Streaming`/`Core.Anim`;
  guard proxy calls that may run mid-restart with `if not Core.isReady() then return end`.

## 7. UI pages

One dist: players download core's `html/` and nothing else. A page is `<plugin>/ui/src/index.js` + `Page.vue`,
and `core/ui/src/plugins.js` globs every sibling `*/ui/src/index.js` at build time (DESIGN §7.4):

```lua
-- ui/src/index.js:  export const id = 'my_plugin';  export { default } from './Page.vue'
-- inside Page.vue:  const { props, emit, on, close } = window.CoreUI.usePage('my_plugin')
Core.onReady(function() Core.UI.registerPage('my_plugin', { type = 'page' }) end)  -- 'overlay' takes no focus
Core.UI.open('my_plugin', { stats = stats })          -- server: Core.UI.open(src, 'my_plugin', props)
Core.UI.send('my_plugin', 'greeting', { text = t })   -- Lua -> page;  page -> Lua: Core.UI.on(id, ev, fn)
```

- Build: `cd $CORE/ui && npm run build` (once per machine: `npm install` at `resources/`, the npm workspace
  root) — that one build compiles core's shell **and** every plugin page and its Tailwind CSS.
- Style with the Tailwind v4 tokens and `.core-*` classes (`bg-panel`, `text-fg-dim`, `rounded-ui`,
  `text-ui-sm`, `core-panel`, `core-btn`, `core-interactive` — the shell is click-through, so anything
  clickable needs it). Root font 16px, `body` 14px; `@apply` in a scoped `<style>` first needs
  `@reference "../../../core/ui/src/styles.css";`.
- **Never `backdrop-filter` / `-webkit-backdrop-filter` / Tailwind `backdrop-*`** — the game frame is not in
  the CEF compositing surface, so it paints a solid black box; glass is `data-core-blur` on the panel (≤ 12 on
  screen, panels only, §32). Never write `*/` in a CSS comment or spell the banned token in a source comment —
  Tailwind scans it (AGENTS §3; **K006**, an *error*). The shell auto-hides over the pause menu, fades,
  switches and cutscenes (§31), and hiding with a modal open **cancels** it (`menu`/`input`/`alert` resolve as
  ESC); a plugin's hide reasons are stored as `<resource>:<reason>`.
- The plugin ships **no UI files**: no `ui_page`, `files { 'ui/**' }`, vite config, `dist` or `node_modules`
  (**K008**); an extra runtime library gets a minimal `ui/package.json` (never `vue`) plus `npm install` at
  `resources/`. Direct `SendNUIMessage`/`RegisterNUICallback`/`SetNuiFocus` is **K012**.

## 8. Verification — run these yourself, do not trust a report (AGENTS §5)

| what | command (from `$CORE`) | expect |
|---|---|---|
| syntax + lint + libs + server + UI build | `scripts/check.sh` (`--full` adds Storybook) | exits 0 |
| libs and loader | `lua5.4 tests/run_tests.lua` | `379 passed, 0 failed` |
| server modules | `lua5.4 tests/server_tests.lua` | `628 passed, 0 failed` |
| rulebook lint | `fxlint resources/core` and the plugin | `0 error(s), 0 warning(s)`, K rules included |
| shell bundle | `cd ui && npm run build` | writes `html/`, no CSS warnings |
| shell regression | `python3 -m http.server 8765 --directory html`, `agent-browser open http://127.0.0.1:8765/index.html`, `agent-browser eval --stdin < ui/tests/shell-regression.js` | `PASS 52/52` (`file://` blocks ES modules) |
| Storybook | `cd ui && npm run build-storybook` | builds; play functions green |
| Postgres bridge | `cd ui && npm run build:server`; `CORE_PG_URL=… node tests/pg_smoke.js` | `pg_smoke: PASS` |
| live | `fxserver logs --errors --resource core`, `fxclient logs --errors` | nothing new |

A plugin needs only the rows that apply to it. Diagnostics: `/uiblur diag|test`, `/doorfind`, `/dbexport`, `/dbimport` (console), `/id`.

## 9. Deploy dance

`fxserver deploy <plugin_dir>` (symlink + `ensure` line) → `fxclient exec --server "refresh"` → `ensure
<plugin>`. FXServer caches manifests, so **`refresh` before `ensure`** or a new file "does not exist" (AGENTS
§8). After a **manifest edit or a page change**: rebuild the UI if a page changed (`cd $CORE/ui && npm run
build`), then `refresh`, `restart core`, `ensure <plugin>` — `restart core` stops every resource with
`dependency 'core'`, so each must be re-`ensure`d (AGENTS §3). After a **core change** the same, plus
re-`ensure` *every* plugin. `fxserver rcon` / `fxclient exec --server` are that console (`src == 0`).

## 10. In-game checklist — core additions

On top of the `fivem-scripting` §13 shape; you never test in-game, Liam does (AGENTS §4.7):

1. Walk into the interaction → marker/label/`[E]` pill appear; walk out → gone. Money/stat/notify effects land
   exactly once, with the server's numbers.
2. The key or command opens the page with a cursor; `ESC` closes it and releases the cursor.
3. `restart <plugin>` with the page open and the marker visible → page closed, focus released, marker, label,
   blip, interaction and key hints gone (the registry did that, no `onResourceStop` code); `restart core` while online → the registrations come back (the `Core.onReady` replay), no re-spawn.
4. A second client fires the event from ~10 m away (F8 `TriggerServerEvent`) → nothing happens, no error;
   spam the key for 10 s → at most one action per cooldown, no kick, no duplicate charge.
5. `resmon 1` (client started with `+set moo 31337`): idle 0.00–0.02 ms, in range < 0.06 ms.

## 11. Secrets

Convars only — never a file in the resource, never logged, never printed (AGENTS §3): `core_pg_url` in
`core_pg.cfg` (`exec core_pg.cfg` from `server.cfg`), Discord webhooks in `core_webhook_<name>`, reached with
`Core.Webhook.send(name, embed)` / `Core.Http.setToken(name, convar)`. Never print `server.cfg`, `sv_licenseKey` or `rcon_password`; never paste a connection string into a report or a commit.
