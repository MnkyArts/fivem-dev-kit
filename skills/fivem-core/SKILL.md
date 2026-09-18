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
| `$CORE/DESIGN.md` §0–§38 | the binding contract. **Later sections override earlier ones**; §37 is the design system, **§38 the runtime UI platform** (it supersedes §7.1, §7.4, §6.10's focus paragraph and §9's message budget). Cite `§n` when you quote a rule. |
| `$CORE/ui/sdk/src/contract.ts` | the TypeScript half of the contract (§38.6): `API_VERSION`, `CoreUIHost` and every type the shell and a plugin share. |
| `$CORE/README.md` | integrator guide: install, "Writing a plugin", "API cheat sheet", "UI", "UI plugins", "The three dev loops", "Page state", "Requests", "Design system (UI kit)", "Game blur", in-game checklist, troubleshooting. |
| `$CORE/types/core.lua` | LuaLS `---@meta` stubs: ~450 functions in ~46 namespaces, `(server)`/`(client)` markers in the descriptions, `---@class Core*Options` tables, `---@alias CoreHook` and the other enums. |

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
+ `tests/stubs.lua`; new lib ⇒ `tests/run_tests.lua`; client UI logic — focus, discovery, requests, patches,
feeds ⇒ `tests/client_ui_tests.lua`; runtime behaviour ⇒ a `ui/tests/unit/*.test.ts` case **and** a check in
`ui/tests/runtime-regression.js`; an SDK change ⇒ `ui/sdk/tests/*.test.mjs` **and** `contract.ts` + DESIGN §38
in the same commit; a new shell action ⇒ a regression check **and** a Storybook story; a new kit component ⇒
DESIGN §37.5 + its CSS partial + a `Kit/<Group>/<Name>` story + `ui/tests/kit-regression.js`).
Multi-agent work appends a run table to `$CORE/PLAN.md`; every subagent gets exact
file ownership, parallel runs never share a file, scratch files live in the session scratchpad under a
run-named folder, and the orchestrator re-runs lint and tests itself before believing a report. Commits
`<area>: <imperative summary>` (`ui:`, `db:`, `client:`), body says *why* (`html/` is committed on purpose);
Rebar inspired the API surface only — never copy its code.

## 3. Plugin anatomy

Scaffold with `fxnew <name>` (core plugin by default) or `$CORE/scripts/new-plugin.sh <name>`; both copy
`$CORE/templates/plugin` and rewrite `my_plugin` / `MyPlugin` / `MY_PLUGIN`. The manifest:

```lua
fx_version 'cerulean'   game 'gta5'   dependency 'core'     -- core must be started first
shared_scripts { '@core/import.lua', 'shared/config.lua' }  -- import.lua FIRST, always
client_scripts { 'client/*.lua' }  server_scripts { 'server/*.lua' }
core_ui 'ui/dist'                                            -- only with a page (§7 below)
files { 'locales/*.json', 'ui/dist/**' }
```

- `'@core/import.lua'` missing/not first or no `dependency 'core'` ⇒ `attempt to index a nil value (global 'Core')` (**K009**). Never a `ui_page` in a plugin (**K008**) — core owns the one CEF page; `core_ui` + the `files` glob are the whole UI opt-in (**K014**). List the natives a file uses in its header comment (AGENTS §3).
- **The onReady rule** (AGENTS §4.1, DESIGN §2.4) — registrations *inside* core (`Markers.add`,
  `TextLabels.add`, `Blips.add`, `Interactions.add`/`addGlobal`/`addFor`, `Doors.register`, `UI.registerPage`,
  `UI.onRequest`, cron jobs) go **inside `Core.onReady(function() … end)`**, which replays after every core restart; in-VM
  registrations (`Core.Net.on`, `Callback.register`, `Commands.register`, `Keys.register`, `UI.on`, `Core.on`)
  stay at **file scope**; also `Core.onPlayerLoaded(fn)` (client) / `Core.on('playerLoaded', fn)` (server).
  **K004** — "everything vanished after `restart core`" is always this rule.
- **Never write an `onResourceStop` cleanup** for core registrations — `Core.Registry` tracks each one under the calling resource and removes it when that resource stops (DESIGN §2.3; **K005**).
- Prefix every event, callback, command and page id with the resource name (`my_plugin:server:buy`). `Config`
  (a deliberate global) lives in `shared/config.lua`, loaded in both VMs; core's own config is `Core.Config`
  inside a plugin, never the `Config` global (§2.0). Locale strings: `locales/<lang>.json` with `{{var}}`
  placeholders, listed in `files {}`, read with `Core.Locale.t('key', { name = x })` — your file first, then
  core's, then the key (§26; **K011**).
- No `package.json`/`node_modules` at the resource **root** or under `server/`: FXServer's Node sandbox
  refuses modules behind the symlinked path and its `yarn` builder would run on every start (AGENTS §3;
  **K007**). Node code is bundled (`core/ui` → `server/db_pg.js`). `<plugin>/ui/package.json` is the opposite
  — it is required, it is a member of the npm workspace at `resources/`, it holds the plugin's own UI
  dependencies, and it never lists `vue` (the shell hands over its one Vue at runtime).

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

## 7. UI plugins (DESIGN §38)

**One** CEF page, one Vue, one kit, one focus stack — all core's. But every resource **owns, builds, ships and
restarts its own frontend**, and core imports it at runtime from `https://cfx-nui-<resource>/ui/dist/`. Core is
never rebuilt for a plugin page; a resource core has never seen can bring a UI along.

```
my_plugin/fxmanifest.lua   core_ui 'ui/dist'   files { 'locales/*.json', 'ui/dist/**' }   -- the whole opt-in
          ui/package.json  name '<resource>-ui'; scripts dev/dev:game/build/typecheck; devDep '@core/ui'; NEVER vue
          ui/vite.config.ts  export default defineConfig({ plugins: [coreUI()] })       -- '@core/ui/vite'
          ui/tsconfig.json   { "extends": "@core/ui/tsconfig.plugin.json", "include": ["src", "dev"] }
          ui/.gitignore      .core-ui/ and node_modules/ — dist/ is NOT ignored, it is COMMITTED
          ui/src/index.ts    export default defineUIPlugin({ pages, setup })   ui/src/Page.vue
          ui/dev/host.ts     createDevHost({ id, plugin, mock })   ui/dev/mock.ts   -- never shipped
          ui/dist/           manifest.json + plugin.<hash>.js/.css — the build, committed like core/html
```

```ts
// ui/src/index.ts — MODULE SCOPE IS FOR DEFINITIONS ONLY: the browser pins this module by URL for the life
// of core's page, while setup(ctx) runs once per activation (every start of the resource).
export default defineUIPlugin({
    pages: { my_plugin: definePage<MyPluginProps>({ component: Page }) },   // () => import('./Big.vue') = lazy
    setup(ctx) {                       // synchronous; may return a disposer; everything here dies with ctx.scope
        ctx.nui.on('sync', apply); ctx.nui.handle('whoAreYou', () => ({ id: ctx.id }))
        ctx.scope.listen(window, 'blur', onBlur); ctx.scope.interval(tick, 1000)
    },
})
// inside Page.vue — no id: usePage() resolves the page being rendered; `props` is ONE stable reactive object
const { props, emit, on, close } = usePage<Props, Out, In>()
const nui = useNui<Rpc>()            // emit · invoke(name, data) · on · handle — this plugin's own channel
const res = await nui.invoke('ping') // rejects with NuiError; .code = timeout|aborted|no_handler|handler_error|…
```

- SDK (`@core/ui`, §38.7): `defineUIPlugin` `definePage` `usePage` `useNui` `useScope` `useFeed` `useHud`
  `usePlayerState` `useStats` `t` `notify` `playSound` `registerIcons` `NuiError`. Only the first two are pure;
  the rest resolve the host lazily and throw outside the shell. Listeners made through them die with their scope.
- Lua (signatures unchanged): `Core.UI.registerPage(id, { type = 'page' | 'overlay' | 'modal' })` inside
  `Core.onReady` (**K004**; `script`/`style` were REMOVED — **K016**), `open` (snapshot), `send`, `on`,
  `close`; `update(id, partial)` (shallow merge) and `patch(id, path, value)` (one leaf, `nil` deletes) queue
  per page and flush as one message; `feed({ speed = … })` for telemetry plus `isFeedActive(channel?)`;
  `onRequest(name, fn)` / `offRequest` answer the page's `nui.invoke`, `request(target, name, data, ms)` asks
  the page; `plugins()` / `isPluginReady(res?)` and the hooks `uiPluginReady` / `uiPluginFailed`.
  **A patch path is Lua's view, 1-based**: a segment indexing a list (`1 ≤ n ≤ #t + 1`) writes `t[n]` in Lua
  and `arr[n - 1]` in the page (R1); everything else is a map key (R2) — so key collections by STRING
  (`slots = { ['12'] = … }`) and keep real lists lists. Server forms take `src` first.
- Three dev loops: `npm run dev -w <res>-ui` (real shell + typed fake Lua in a browser, HMR — the default),
  `npm run build -w <res>-ui` + `restart <res>` (in game), `npm run dev:game` + `/uidev <res>
  http://localhost:5173` (in game, needs `Config.UI.Dev.Enabled`; localhost only). `/uiplugins` prints every
  plugin's state — the first thing to look at when a page stays blank; `/uiinspect` is the inspector panel.
- Style from the kit only (`<CoreScreen>`, `<CorePanel>`, `<CoreButton>`, `<CoreKeyHints>`, … — globally
  registered, no import, §37.5). The plugin's sheet holds only its own Tailwind utilities and `<style scoped>`
  blocks — no preflight, no `:root` tokens, no kit classes, and an unscoped global selector is a bug. `@apply`
  in a scoped block first needs `@reference "@core/ui/reference.css";` (a package specifier, not a path into
  core). Tokens only (`bg-panel`, `text-fg-dim`, `rounded-ui`, `font-display`); opacity modifiers
  (`bg-error/15`) are fine, individual `translate-*`/`rotate-*`/`scale-*` are not (Chromium 103 ignores them —
  write `transform:`). **Never `backdrop-filter` / `-webkit-backdrop-filter` / Tailwind `backdrop-*`**: the
  game frame is not in the CEF compositing surface, so it paints a solid black box; glass is `data-core-blur`
  on the panel (≤ 12 on screen, panels only, §32). Never write `*/` in a CSS comment or spell the banned token
  in a source comment — Tailwind scans it (**K006**, an *error*). The shell auto-hides over the pause menu,
  fades, switches and cutscenes (§31), and hiding with a modal open **cancels** it; a plugin's hide reasons
  are stored as `<resource>:<reason>`.
- A plugin never touches NUI itself: no `SendNUIMessage`, `RegisterNUICallback`, `SetNuiFocus`,
  `GetParentResourceName` or `createApp` (**K012**, **K017**) — focus is a stack core alone owns. `ui/dist`
  must be built, committed and matched by `core_ui` + `files` (**K014**, **K015**); a `client_scripts` glob
  must never reach into it (FiveM would serve those files as garbage).

## 8. Verification — run these yourself, do not trust a report (AGENTS §5)

**The expected counts live in `$CORE/AGENTS.md` §5 — read them there, never from memory.** They move with
every change, so quoting a number here would only teach a stale one.

| what | command (from `$CORE`) | expect |
|---|---|---|
| the whole offline gate | `scripts/check.sh` (`--full` adds the browser suites + Storybook) | exits 0 |
| libs and loader · server modules | `lua5.4 tests/run_tests.lua` · `lua5.4 tests/server_tests.lua` | `N passed, 0 failed` (AGENTS §5) |
| client UI (focus stack, discovery, requests, patches, feeds) · chat | `lua5.4 tests/client_ui_tests.lua` · `lua5.4 tests/client_chat_tests.lua` | `N passed, 0 failed` |
| runtime + SDK units | `node --test 'ui/tests/unit/**/*.test.ts' 'ui/sdk/tests/*.test.mjs'` (GLOBS — a directory finds nothing) | `# fail 0` |
| types · generated kit tags | `npx vue-tsc --noEmit -p ui/tsconfig.json` · `node ui/scripts/gen-kit-types.mjs --check` | no output, exit 0 · `up to date` |
| **every plugin's dist** | `node ui/scripts/check-plugins.mjs` | `N UI plugin(s) …, 0 error(s), 0 warning(s)` |
| rulebook lint | `fxlint resources/core` and the plugin | `0 error(s), 0 warning(s)`, K rules included |
| shell bundle · **a plugin's bundle** | `cd ui && npm run build` · `npm run build -w <resource>-ui` (from `resources/`) | writes `html/` · writes `<plugin>/ui/dist` (~1 s) |
| kit compile check | `node ui/tests/kit-compile-check.mjs <file>` | `0 error(s)` |
| the three browser suites | `node ui/tests/run-browser-suites.mjs` (builds fixtures, one origin per fixture resource, drives agent-browser) | `PASS n/n` ×3 |
| Storybook | `cd ui && npm run build-storybook` | builds; play functions green |
| Postgres bridge | `cd ui && npm run build:server`; `CORE_PG_URL=… node tests/pg_smoke.js` | `pg_smoke: PASS` |
| live | `fxserver logs --errors --resource core`, `fxclient logs --errors` | nothing new |

A plugin needs only the rows that apply to it — typically `fxlint`, its own `npm run build` + `npm run
typecheck`, and `check-plugins.mjs`. Diagnostics: `/uiplugins`, `/uidev <res> <origin|off>`, `/uiinspect`
(the last two need `Config.UI.Dev.Enabled`), `/uiblur diag|test`, `/doorfind`, `/dbexport`, `/dbimport`
(console), `/id`; inside the CEF `nui_devtools` / `localhost:13172`.

## 9. Deploy dance

`fxserver deploy <plugin_dir>` (symlink + `ensure` line) → `fxclient exec --server "refresh"` → `ensure
<plugin>`. FXServer caches manifests, so **`refresh` before `ensure`** or a new file "does not exist"
(AGENTS §8). After that, deploy the smallest thing that works:

| what changed | what to run |
|---|---|
| the plugin's **page** | `npm run build -w <plugin>-ui` (from `resources/`), then `restart <plugin>`. New hash → new URL → new code. **No core rebuild, no `restart core`, no CEF reload** |
| a plugin's Lua, or a new file under an existing `files {}` glob | `restart <plugin>` |
| a **new manifest entry** or a new resource folder | `refresh`, then `restart`/`ensure <plugin>` |
| **core itself** | `refresh`, `restart core`, then re-`ensure` *every* plugin — `restart core` stops every resource with `dependency 'core'` (AGENTS §3) |

`fxserver rcon` / `fxclient exec --server` are that console (`src == 0`). A page that stays blank after a
deploy: `/uiplugins` first (state, generation, build, error), then the server console (core validates every
`ui/dist` at start-up), then the CEF devtools.

## 10. In-game checklist — core additions

On top of the `fivem-scripting` §13 shape; you never test in-game, Liam does (AGENTS §4.7):

1. Walk into the interaction → marker/label/`[E]` pill appear; walk out → gone. Money/stat/notify effects land
   exactly once, with the server's numbers.
2. `/uiplugins` lists the plugin as `ready` with its build hash; the key or command opens the page with a
   cursor, `ESC` closes it and releases the cursor, and a modal on top of it hands focus back on close.
3. `restart <plugin>` with the page open and the marker visible → page closed, focus released, marker, label,
   blip, interaction and key hints gone (the registry did that, no `onResourceStop` code); open it again →
   the new build runs (generation n+1 in `/uiplugins`) and no listener fires twice; `restart core` while
   online → the registrations come back (the `Core.onReady` replay), no re-spawn.
4. A second client fires the event from ~10 m away (F8 `TriggerServerEvent`) → nothing happens, no error;
   spam the key for 10 s → at most one action per cooldown, no kick, no duplicate charge.
5. `resmon 1` (client started with `+set moo 31337`): idle 0.00–0.02 ms, in range < 0.06 ms.

## 11. Secrets

Convars only — never a file in the resource, never logged, never printed (AGENTS §3): `core_pg_url` in
`core_pg.cfg` (`exec core_pg.cfg` from `server.cfg`), Discord webhooks in `core_webhook_<name>`, reached with
`Core.Webhook.send(name, embed)` / `Core.Http.setToken(name, convar)`. Never print `server.cfg`, `sv_licenseKey` or `rcon_password`; never paste a connection string into a report or a commit.
