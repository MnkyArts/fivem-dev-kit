# fivem-dev-kit — design contract

Claude Code plugin that turns Claude into a FiveM (Cfx.re / GTA V) resource developer: it
looks up natives from a merged, locally indexed native database, searches the docs.fivem.net
source, writes resources following a hard set of performance and security rules, lints them,
deploys them to the local dev server and reads the server log. The human only tests in-game.

Everything below is a contract. Implementers build exactly this; reviewers check against it.

## 1. Locations and layout

Workspace: `/home/liamrbsn/Dokumente/Entwicklung/FiveM/` (call it `$WS`)

| Path | What |
|---|---|
| `$WS/gta5-nativedb-data/` | alloc8or native DB: `natives.json` (legacy, 6701), `natives_gen9.json` (Enhanced, 6748), `schema.json` |
| `$WS/fivem/` | FiveM source (git master). Relevant: `ext/native-decls/*.md` (826 CFX natives), `ext/natives/codegen*.lua` (naming/signature rules), `data/shared/citizen/scripting/lua/scheduler.lua` (Lua runtime), `data/shared/citizen/scripting/v8/*.js` (JS runtime), `code/components/citizen-server-impl/src/packethandlers/*.cpp` (rate limits), `ext/typings/` (TS typings) |
| `$WS/fivem-docs/` | docs.fivem.net source (Hugo). Pages in `content/docs/**/*.md` (342 files, front matter with `title`, `weight`, `nav_group`) |
| `$WS/Server/` | txAdmin-managed FXServer. `run.sh` starts it. Data: `txData/FiveMBasicServerCFXDefault_A41D86.base/` (`server.cfg`, `resources/[local]/`), log: `txData/default/logs/fxserver.log`. Game build 3751. Standalone (no framework). `server.cfg` contains the license key: NEVER print server.cfg wholesale, never echo `sv_licenseKey`. |
| `$WS/resources/` | where new resources are developed (created on demand), deployed into `[local]` by symlink |
| `$WS/fivem-dev-kit/` | this plugin (`$KIT`). Symlinked to `~/.claude/skills/fivem-dev-kit` so Claude Code auto-loads it as `fivem-dev-kit@skills-dir` |

Plugin layout:

```
fivem-dev-kit/
  .claude-plugin/plugin.json      # name fivem-dev-kit
  README.md                       # for Liam: what it is, install, commands, updating data
  DESIGN.md                       # this file
  config.json                     # machine-specific (paths, server, project prefs); config.example.json in git
  bin/fxref  bin/fxlint  bin/fxnew  bin/fxserver   # python3 CLIs (chmod +x, `#!/usr/bin/env python3`), stdlib only
  lib/fxkit/                      # shared python package: config.py (load config, resolve paths), util.py
  data/                           # generated: fxref.sqlite, cache/*.json (gitignored)
  skills/fivem-reference/SKILL.md # how/when to use fxref (natives + docs)
  skills/fivem-scripting/SKILL.md # the rulebook: how to write resources (+ reference/, patterns/, templates/)
  skills/fivem-build/SKILL.md     # user-invocable orchestrated pipeline: spec -> natives -> plan -> implement -> lint -> review -> deploy -> test checklist
  skills/fivem-review/SKILL.md    # review an existing resource
  skills/fivem-server/SKILL.md    # deploy / logs / rcon usage
  agents/fivem-native-scout.md    # model: haiku
  agents/fivem-implementer.md     # model: opus
  agents/fivem-reviewer.md        # model: opus
  hooks/hooks.json + hooks-handlers/post-edit-lint.py   # PostToolUse Write|Edit on lua/js in a resource -> fxlint, non-blocking
  tests/                          # smoke tests runnable with `python3 tests/run.py`
```

All CLIs must work when invoked through the symlink (`~/.claude/skills/fivem-dev-kit/bin/fxref`):
resolve `os.path.realpath(__file__)` to find `lib/` and `config.json`.

`config.json` (loaded by `lib/fxkit/config.py`; env var `FXKIT_CONFIG` overrides the path):

```json
{
  "sources": {
    "nativedb": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/gta5-nativedb-data",
    "fivem": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/fivem",
    "fivem_docs": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/fivem-docs",
    "natives_json_url": "https://runtime.fivem.net/doc/natives.json",
    "natives_cfx_json_url": "https://runtime.fivem.net/doc/natives_cfx.json"
  },
  "server": {
    "root": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/Server",
    "data_dir": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/Server/txData/FiveMBasicServerCFXDefault_A41D86.base",
    "local_resources_dir": "resources/[local]",
    "server_cfg": "server.cfg",
    "log_file": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/Server/txData/default/logs/fxserver.log",
    "game_build": 3751,
    "rcon": { "host": "127.0.0.1", "port": 30120, "password_env": "FXRCON_PASSWORD" }
  },
  "project": {
    "workspace": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/resources",
    "language": "lua",
    "framework": "standalone",
    "ox_lib": false,
    "game": "gta5",
    "author": "MnkyArts"
  }
}
```

## 2. Native data model (fxref)

Merged from four sources into `data/fxref.sqlite`:

1. alloc8or `natives.json` — canonical names (only 1 unnamed), params, return_type, `build` (game build a native was introduced), `old_names`, `unused`, `comment`. Namespaces use alloc8or naming (CAMERA, PATH, APPS, BUILTIN, ...).
2. alloc8or `natives_gen9.json` — same for GTA V Enhanced. 49 hashes are gen9-only, 2 legacy-only. Used for availability flags.
3. FiveM `natives.json` (downloaded to `data/cache/`) — 6416 natives keyed `NS -> hash -> {name?, params[{name,type,description?}], results, description, examples[{lang,code}], hash, jhash, ns, aliases?, manualHash, annotations?, resultsDescription?}`. 1020 entries have NO `name` (unnamed): name is then `_0x<HASH>`. 976 names start with `_` = unofficial name. Namespaces use docs.fivem.net naming (CAM, PATHFIND, APP, SYSTEM, FILES, MOBILE, LOADINGSCREEN, ITEMSET, ...). Descriptions/param descriptions/examples here are curated.
4. CFX natives: parse `$WS/fivem/ext/native-decls/*.md` (front matter `ns: CFX`, `apiset: client|server|shared`, optional `game: gta5|rdr3|ny`, optional `aliases`; body: `## NAME`, a ```c signature block, description, `## Parameters` list, `## Return value`, `## Examples` fenced blocks with lang). Hash = joaat(name) (verified: GET_ENTITY_COORDS -> 0x1647F1CB). Downloaded `natives_cfx.json` is the fallback/cross-check (943 natives: 583 client, 286 server, 74 shared). Exclude decls whose `game` is set and is not `gta5`.

Merge policy (key = (hash, apiset)):
- GTA natives (sources 1–3) have `apiset = client`. CFX natives have their declared apiset.
- `name`: alloc8or name; else FiveM name (strip leading `_`, record `unofficial=1`); else `_0x<HASH>`.
- `aliases`: union of FiveM `aliases`, alloc8or `old_names`, FiveM name if it differs from `name` (minus leading `_`), hash string. Unique, excluding `name`.
- `ns`: FiveM ns if present else alloc8or ns; `ns_alt`: the other one when different. Both searchable.
- `description`: FiveM description if non-empty else alloc8or comment. Keep `comment_alloc8or` separately when both exist and differ.
- `params`: alloc8or params (type,name) enriched with FiveM param descriptions (match by name, then by position). Return type: alloc8or `return_type`, FiveM `results` fallback. `results_description` from FiveM.
- `build` (alloc8or), `unused`, `gen9` availability: `in_legacy`, `in_gen9`, `build_gen9`.
- `examples`: FiveM examples + native-decls examples (lang, code).
- `url`: `https://docs.fivem.net/natives/?_0x<HASH>`.
- `source`: which sources contributed (comma list).

Name forms (all must resolve in `show`/`resolve` and be searchable):
- C name `SET_PED_INTO_VEHICLE`, Lua/JS name `SetPedIntoVehicle`, lowerCamel `setPedIntoVehicle`, hash `0xF75B0D629E1C063D` (case-insensitive, with/without 0x), unnamed `_0x...` / `N_0x...` (Lua form is `N_0x` + lowercase hex).
- Lua/JS name algorithm (from `ext/natives/codegen_out_lua.lua` `printFunctionName`): `name:lower():gsub('0x','n_0x'):gsub('_(%a)', upper):gsub('(%a)(.+)', first upper)`. Leading `_` disappears naturally. C#: same PascalCase name under `API.`.

Signature rules (from `codegen_out_lua.lua`, verify JS in `codegen_out_js.lua`, C# in `codegen_out_cs.lua`):
- A param is a pointer (out param) iff its type ends with `*` and is not `char*`/`const char*` (strings are inputs).
- Lua argument list = all non-pointer params in order. Exception "single pointer native": exactly one pointer param AND it is the last param -> it is also accepted as an OPTIONAL trailing argument (initialized in/out value).
- Lua return list = [native return value if not void] followed by every pointer param in declaration order. So `local ret, out1, out2 = Native(args)`.
- Lua returns `Vector3` as a `vector3` userdata; JS returns `[x, y, z]`. Multiple returns in JS come back as an array.
- Lua `Hash` params accept a string (auto `GetHashKey`), JS/C# need a number. Lua string params: passing `0`/`nil` sends a null string.
- `func` params take a function (callback); `object` params are msgpack-serialized tables.
- `BOOL` return -> Lua boolean; `int` -> integer; `float` -> number; `char*` -> string; `Any*` -> integer (64-bit).

SQLite schema (FTS5 must be used; single file `data/fxref.sqlite`, rebuildable with `fxref build`):

```
natives(id INTEGER PK, hash TEXT, jhash TEXT, name TEXT, lua_name TEXT, ns TEXT, ns_alt TEXT, apiset TEXT,
        unofficial INT, aliases TEXT(json), params TEXT(json), return_type TEXT, results_description TEXT,
        description TEXT, comment_alloc8or TEXT, examples TEXT(json), build TEXT, build_gen9 TEXT,
        in_legacy INT, in_gen9 INT, unused INT, url TEXT, source TEXT, c_signature TEXT, lua_signature TEXT, js_signature TEXT)
natives_fts (FTS5, content=natives): name_tokens, alias_tokens, ns, param_text, description   (prefix + porter/unicode61 tokenizer)
docs(id INTEGER PK, path TEXT UNIQUE, url TEXT, title TEXT, section TEXT, nav_group TEXT, headings TEXT, body TEXT)
docs_fts (FTS5): title, headings, body
meta(key, value)   -- build time, source git shas, counts
```

`name_tokens` = words of the C name split on `_` plus the Lua name; `alias_tokens` likewise for aliases.

## 3. fxref CLI

`fxref` (python3, stdlib only; sqlite3 with FTS5 is available: SQLite 3.53).

```
fxref build [--no-download] [--natives-only|--docs-only]      # (re)build the DB. Downloads FiveM JSONs to data/cache unless --no-download or cached < 7 days
fxref search <query...> [--ns NS] [--side client|server|shared|any] [--game legacy|gen9|any] [--limit N=15] [--json] [--all]
fxref show <name|hash|luaName> [--json]                       # full card; ambiguous (client+server same name) -> show both
fxref resolve <name...> [--json]                              # batch check: for each identifier -> found?, canonical name, apisets, hash, lua_name. Exit 0 always. Used by fxlint.
fxref ns [--json]                                             # namespaces with counts
fxref docs search <query...> [--limit N=10] [--json]
fxref docs show <path|id> [--section "Heading"] [--raw]        # markdown (front matter stripped, Hugo shortcodes simplified)
fxref docs ls [prefix]
fxref stats
fxref update-sources                                          # git pull nativedb, fivem-docs (NOT fivem/ — too big, user does it), re-download JSONs, then build
```

Search behaviour:
- Exact matches first: hash, exact C/Lua/lowerCamel name, alias -> single hit bubble to top and marked `exact`.
- Otherwise FTS5 BM25 with column weights name_tokens 10, alias_tokens 6, ns 3, param_text 2, description 1. Query terms get prefix matching (`term*`). Camel/underscore query is tokenized. Synonym expansion (both directions, OR-ed): vehicle/car/veh, ped/player/character/npc, weapon/gun, coords/position/pos/location, teleport/tp, invincible/godmode/god, health/hp, model/hash, blip/marker, notification/notify, text/draw, freeze/frozen, door/doors, lock/locked, engine/motor, seat, cam/camera, anim/animation, task, network/net/sync, entity/object/prop, plate/numberplate/licenseplate, color/colour, remove/delete, create/spawn. Keep the map in `lib/fxkit/synonyms.py`.
- Results line format (non-JSON), one per hit, compact:
  `SET_VEHICLE_DOORS_LOCKED  [VEHICLE, client, build 323, legacy+gen9]  Lua: SetVehicleDoorsLocked(vehicle, doorLockStatus)  -- first sentence of description`
- `show` card sections: NAME (unofficial marker), hash/jhash, ns, apiset, build (+gen9), aliases, C signature, Lua signature incl. returns (`-> BOOL`), JS signature, C# signature, description (markdown), params with descriptions, return description, examples (all langs), url, sources. Keep under ~80 lines unless `--json`.
- Speed: any command < 200 ms after build. Build < 60 s.

Docs index: page id = path relative to `content/` without `.md` and without trailing `_index` (e.g. `docs/scripting-reference/resource-manifest/resource-manifest`), url = `https://docs.fivem.net/` + id + `/`. `section` = 2nd path component (scripting-manual, scripting-reference, server-manual, ...). Strip front matter; store headings list. Search: title weight 8, headings 4, body 1.

## 4. fxlint

`fxlint <resource_dir|file...> [--json] [--no-verify] [--strict] [--rules R1,R2] [--ignore R1]`

- Determines each file's side from `fxmanifest.lua` (`client_script(s)`, `server_script(s)`, `shared_script(s)`, with `*` globs and `@other/...` deps) and falls back to path heuristics (`client/`, `server/`, `shared/`, `cl_*.lua`, `sv_*.lua`, `*_client.*`, `*_server.*`).
- Lua and JS (and TS lightly). Heuristic analysis (regex + brace/keyword depth tracking); no external tools.
- Native verification: collects PascalCase call identifiers, excludes ones defined in the resource (`function Name(`, `Name = function`, `local Name`), known runtime globals (CreateThread, Wait, SetTimeout, RegisterNetEvent, AddEventHandler, TriggerEvent, TriggerServerEvent, TriggerClientEvent, RegisterCommand, GetHashKey, PlayerPedId, PlayerId, GetPlayerServerId, vector3/4/2, quat, Citizen.*, exports, GlobalState, Entity, Player, LocalPlayer, json, msgpack, promise, lib.*, exports.*, print, source, math/string/table, etc.) and checks the rest via `fxref resolve --json` (subprocess to `$KIT/bin/fxref`). Missing -> C008 (possible hallucinated native). Wrong side -> C007.
- Rule IDs, severity (error/warn/info), one-line message, fix hint. Implement at least:
  - P001 error: loop (`while`/`repeat`/`for` with `true`-ish condition or infinite) without any `Wait(`/`Citizen.Wait(`/`await Delay(` inside → freezes the runtime.
  - P002 warn: `Wait(0..15)` inside a loop → per-frame loop; require justification comment `-- per-frame:` else flag; suggest adaptive sleep, event/statebag/`lib.points`.
  - P003 info: `Wait(n)` 16..99 in loop → consider raising.
  - P004 warn: `CreateThread`/`setTick` inside an event handler or loop body → thread leak risk.
  - P005 warn: expensive natives inside a per-frame loop (`GetPlayers`, `GetGamePool`, `GetActivePlayers`, `GetAllVehicles`, `GetVehiclePedIsIn` on non-local, `GetClosest*`, `json.encode/decode`, `TriggerServerEvent`, `TriggerClientEvent`).
  - P006 warn: `TriggerClientEvent(name, -1, ...)` inside a loop/timer → broadcast storm.
  - P007 info: `PlayerPedId()`/`GetEntityCoords(PlayerPedId())` called several times in one per-frame loop body → cache.
  - S001 warn: server net-event handler never references `source` → not bound to the triggering player.
  - S002 warn: server net-event handler passes an event argument straight into a sensitive call (`SetPlayerRoutingBucket`, `DropPlayer`, `ExecuteCommand`, `GiveWeaponToPed`, `SetEntityCoords`, `CreateVehicle*`, `SetPedArmour`, money/item/bank/cash/give/add/remove/inventory/xp/level named functions, `MySQL`/`exports.oxmysql` queries) without any validation statement in the handler (`if`, `assert`, `tonumber`, `type(`, distance math `#(`, permission/ace check `IsPlayerAceAllowed`).
  - S003 warn: server handler trusts a player id from the event payload instead of `source` (parameter named like `playerId|target|src|serverId` used as first arg of `GetPlayerPed`, `TriggerClientEvent`, `DropPlayer`).
  - S004 info: `RegisterNetEvent` for an event that is only triggered locally in this resource (no `TriggerServerEvent`/`TriggerClientEvent`/`emitNet` with that name anywhere) → needless network exposure.
  - S005 warn: `RegisterCommand(name, fn, false)` on server for admin-ish names (kick|ban|give|money|tp|noclip|god|revive|announce|setjob|admin|weapon|delete) → use restricted=true + ACE.
  - S006 warn: `load(`/`loadstring(`/`os.execute`/`io.popen`/`dofile` anywhere.
  - S007 info: client `TriggerServerEvent` of an event with no matching server handler in this resource (probably fine, but report) and vice versa.
  - S008 warn: server net-event handler with no argument type checks that then uses arguments as table keys/numbers (`args[...]`, arithmetic).
  - S009 warn: `SetEntityCoords`/`SetPedIntoVehicle` server-side using coords/ids coming from the client event payload without a distance check (`#(` or `GetDistanceBetweenCoords` or `Vdist`).
  - C001 info: `Citizen.CreateThread`/`Citizen.Wait`/`Citizen.SetTimeout`/`Citizen.Trace` → modern global forms.
  - C002 info: `GetPlayerPed(-1)` → `PlayerPedId()`.
  - C003 info: file-scope global function/variable (no `local`) in Lua that is not an export/callback → leaks.
  - C004 error: `__resource.lua` present.
  - C005 warn: manifest issues: missing `fx_version`/`game`; `use_experimental_fxv2_oal 'yes'` present → info that vector3 auto-unpacking is disabled (OAL) so every vector must be passed as x, y, z; resource uses `lib.` (ox_lib) but no `@ox_lib/init.lua` in shared_scripts or missing `dependency 'ox_lib'`; `dependencies` for `exports['x']` used (info).
  - C006 warn: `AddEventHandler('x')` on server/client for an event that is triggered from the other side but never `RegisterNetEvent`ed (won't be delivered); `RegisterNetEvent` without any handler.
  - C007 error: native with apiset `client` used in server file or `server` used in client file (via fxref resolve; `shared` ok).
  - C008 warn: unknown PascalCase native-looking call not in DB and not defined locally.
  - C009 error: `TriggerServerEvent` in server file; `TriggerClientEvent` in client file; `source` used in client file.
  - C010 info: JS `on('name')` on server for an event triggered by clients → `onNet`.
  - C011 info: `Wait()` inside `AddEventHandler('onResourceStop'...)` (stop handler must be synchronous).
  - C012 warn: `exports['name']:fn()` on client for server-only exports… skip if not determinable; instead: `exports.` usage with resource not in `dependency` (info).
- Suppression: `-- fxlint-disable-next-line P002` / `-- fxlint-disable P002,S001` (file scope) / JS `// fxlint-disable-next-line`.
- Output: per-file, `path:line: LEVEL RULE message` then a summary; exit 1 if any error (0 otherwise; `--strict` makes warns errors). `--json` → `{files:{path:[{line,rule,level,msg,hint}]}, summary:{errors,warns,infos}}`.
- Must run < 1 s on a 30-file resource. Must not crash on any input: unknown syntax → skip file with an info.

## 5. fxnew

`fxnew <name> [--dir DIR=$project.workspace] [--lang lua|js] [--framework standalone|esx|qb|qbox|ox] [--ox-lib] [--no-client] [--no-server] [--nui] [--author X] [--desc "..."]`

Generates: `fxmanifest.lua` (`fx_version 'cerulean'`, `game 'gta5'`, `author`, `description`, `version '1.0.0'`, `shared_scripts { 'shared/config.lua' }` (+ `'@ox_lib/init.lua'` when ox-lib), `client_scripts { 'client/*.lua' }`, `server_scripts { 'server/*.lua' }`, `dependencies`), `shared/config.lua` (Config table with `Debug = false`), `client/main.lua`, `server/main.lua` (each with a minimal, correct, non-looping skeleton and `onResourceStart`/`onResourceStop` guards), `README.md` (purpose, config, in-game test checklist section), `.fxlintrc.json` (optional rule config), optional `html/` for NUI (index.html, style.css, script.js, `ui_page`, `files`). Framework option adds the framework bootstrap snippet (ESX: `ESX = exports['es_extended']:getSharedObject()`; QB: `QBCore = exports['qb-core']:GetCoreObject()`; qbox: `exports.qbx_core`; ox: `Ox = require '@ox_core.lib.init'`), or standalone. Refuses to overwrite an existing dir unless `--force`.

## 6. fxserver

`fxserver status` (FXServer process running? which port; txAdmin?), `fxserver deploy <resource_dir> [--no-ensure]` (symlink into `$server.data_dir/$local_resources_dir/<name>`; add `ensure <name>` to server.cfg after the last existing `ensure` line if absent; backs up server.cfg to `server.cfg.fxkit.bak` once; never prints the cfg), `fxserver undeploy <name>`, `fxserver list` (deployed local resources), `fxserver logs [--tail N=80] [--errors] [--resource NAME] [--since MIN] [--follow]` (reads `$server.log_file`, strips ANSI, `--errors` keeps lines with `error`, `SCRIPT ERROR`, `warning`, `stack traceback`, `Couldn't`, `failed`, `nil value`, `attempt to`), `fxserver rcon <command...>` (Quake-style OOB UDP: `\xff\xff\xff\xff` + `rcon <password> <command>` to host:port, print response minus header; password from env `$FXRCON_PASSWORD` or `--password`; explain how to set `rcon_password` in server.cfg if missing — verify the exact packet format in `$WS/fivem/code/components/citizen-server-impl/src/GameServer.cpp` / `citizen-server-net`), `fxserver restart <resource>` = rcon `restart <resource>`.

## 7. Skills and agents (behavioural contract)

- Every native used in generated code MUST have been verified with `fxref show`/`fxref resolve` in the same session. Never write a native call from memory alone.
- Subagent models: scout = haiku, implementer = opus (coding quality; Sonnet caused review rounds), reviewer = opus. Never fable for subagents. The main session plans, delegates, reviews.
- Performance rules (resmon target: 0.00–0.02 ms idle, < 0.10 ms active): no busy loops; per-frame loops only for drawing/controls and only while needed (start/stop them via events or state); adaptive `Wait` (250–1000 ms when far, 0 when near); prefer events, state bags, `SetTimeout`, key mappings (`RegisterKeyMapping`) over polling `IsControlJustPressed`; cache `PlayerPedId()` per tick; no `GetPlayers()`/pool scans per frame; use `lib.points`/`lib.zones` when ox_lib is present.
- Security rules: server is authoritative; in every net-event handler capture `local src = source` as the FIRST statement (the runtime resets `source` right after the handler coroutine starts, so it is stale after any `Wait`); validate `src`, types, ranges, distance (`#(coords - GetEntityCoords(GetPlayerPed(src))) < N`), ownership/permissions (ACE `IsPlayerAceAllowed`), rate (per-player cooldown table) for every net event; never trust client-supplied player ids, prices, amounts, entity handles without checks; never expose give/money/item/ban events without checks; use `RegisterNetEvent` only for events that must be reachable from the network; use `RegisterCommand(name, fn, true)` + ACE for admin commands; server-side entity creation (`CreateVehicleServerSetter`, `CreatePed`) for persistent/synced entities; use `NetworkGetEntityFromNetworkId` and check `DoesEntityExist`; client-side rate limits are cosmetic only.
- Runtime facts with limits (from source): net events 50/s per client with burst 200 (flood 75/300), event payload 128 KB/s burst 384 KB per client (`ServerEventPacketHandler.cpp`); state bags 75/s burst 125 (flood 150/175), 128 KB/s burst 256 KB (`StateBagPacketHandler.cpp`). Exceeding these drops the client — so no per-frame event spam or state-bag writes.
- Style: Lua 5.4 (all FXServer builds since June 2025 run 5.4; `lua54 'yes'` is a deprecated no-op — omit it), locals everywhere, `CreateThread`/`Wait` (no `Citizen.`), `RegisterNetEvent(name, handler)` two-arg form, vectors (`vector3`, `#(a - b)`), early returns, small functions, config in `shared/config.lua`, no globals except intentional exports, comments only where non-obvious, English identifiers.

## 8. Verified runtime decisions (2026-09-11, from `skills/fivem-scripting/reference/runtime-facts.md`)

- `lua54 'yes'` is a no-op (Lua 5.3 removed June 2025): do not generate it, do not lint for it.
- `use_experimental_fxv2_oal 'yes'` is faster but disables `vector3` auto-unpacking in native calls: OFF by default; if enabled, pass `v.x, v.y, v.z`.
- `fxmanifest.lua` (not `__resource.lua`) is what enables the modern (`is_cfxv2`) runtime paths; `fx_version 'cerulean'` + `game 'gta5'` is the canonical header. Since `cerulean`, NUI callback URLs are `https://<resource>/<cb>` (use `GetParentResourceName()`), other resources' files via `https://cfx-nui-<resource>/`.
- `source` is only valid until the first `Wait`/`Await` in a handler: always `local src = source` first.
- `sv_stateBagStrictMode true` makes ALL client-side state-bag writes no-ops: generated code must never rely on clients writing state bags; the server writes, clients read.
- Server-side `CreatePed`/`CreateObjectNoOffset`/`CreateVehicleServerSetter` create entities on the server (persist without an owner nearby); server `CreateVehicle` is dispatched to a client — prefer `CreateVehicleServerSetter`.
- Rate limits (per client): net events 50/s burst 200 (flood 75/300, payload 128 KB/s burst 384 KB); state bags 75/s burst 125 (flood 150/175, 128 KB/s burst 256 KB). Exceeding → client dropped.
- Client Lua has no `io`/`os`; use `GetGameTimer()` for timing everywhere.

## 9. `core` framework integration (2026-09-12)

Liam's own framework lives at `$WS/resources/core` (git repo; Lua 5.4, standalone, single Vue/Tailwind CEF).
Plugins are ordinary resources with `dependency 'core'` and `'@core/import.lua'` first in `shared_scripts`;
`$WS/resources/core_example` is the reference plugin. Sources of truth, in order: `core/AGENTS.md` (working
agreement, also linked from `resources/CLAUDE.md`), `core/DESIGN.md` (§0–§33 contract), `core/README.md`
(integrator guide + API cheat sheet), `core/types/core.lua` (LuaLS `---@meta` stubs for every public
function, ~400 functions in ~40 namespaces, `(server)`/`(client)` markers in descriptions, `---@class` option
tables, `---@alias` enums incl. `CoreHook`). The kit must make Claude use those instead of memory.

### 9.1 config.json

```json
"project": { "framework": "core", ... },
"core": {
  "path": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/resources/core",
  "example": "/home/liamrbsn/Dokumente/Entwicklung/FiveM/resources/core_example",
  "types": "types/core.lua",
  "template": "templates/plugin",
  "ui_dir": "ui",
  "check_script": "scripts/check.sh"
}
```
`lib/fxkit/config.py` gains `core_paths()` (dict path/example/types/template/ui/check, all absolute; `None`
when `core` is not configured or the path is missing). Every core feature degrades silently when unset.

### 9.2 `fxref core` — the framework API index

Parse `types/core.lua` (LuaLS): `---@class Name` + following `---@field name? type desc` lines;
`---@alias Name` + `---| '"value"' # desc` lines; function stubs = the contiguous `---` comment block above
`function Core.Ns.name(args) end` (or `Core.Ns.sub.name`): description lines (first line may start with
`(server)`/`(client)`; unmarked = both), `---@param name? type desc`, `---@return type name? desc`. Also
`Core.Ns = {}` / `---@class Core.UI.menu` sub-namespaces. Lib-vs-proxy: namespaces listed in
`LIB_MODULES` of `core/import.lua` (Utils, Math, Validate, Log, Callback, Net, Commands, Keys, Streaming,
Anim, Player, UI, Locale, Audio) run in the caller's VM; everything else is an export-proxy call that must run
in a coroutine after `Core.onReady` (DESIGN §2.2). Mark each function `lib` or `proxy` (sub-namespaces of UI
listed in `SUB_NAMESPACES` — menu, input, alert, progress, textUI, hud, keys, spinner, stats, state, locale — are
proxies).

Tables: `core_api(id, kind function|class|alias|hook, name, namespace, side server|client|shared, access lib|proxy|'',
signature, params json, returns json, description, fields json, values json, design_ref, line, sha)` +
`core_api_fts(name_tokens, namespace, description, param_text)`. Built by `fxref build` (when core is
configured) and by `fxref core build` alone (< 2 s). `fxref stats` shows core counts + git sha.

Commands (same conventions as the natives commands; `--json` everywhere):
- `fxref core search <query...> [--side server|client|any] [--ns NS] [--limit N]` → one line per hit:
  `Core.Money.add(src, account, amount, reason?) -> boolean ok  [Money, server, proxy]  -- Adds a positive amount…`
- `fxref core show <Core.Ns.fn | CoreClass | CoreAlias>` → card: signature, side, lib/proxy + the coroutine/
  onReady rule when proxy, description, params (with class fields expanded inline for `Core*Options` types),
  returns, `design_ref`, `types/core.lua:<line>`. Accepts `Money.add`, `Core.Money.add`, `money.add` (case-insens.).
- `fxref core resolve <names...>` → FOUND/MISSING per name (used by fxlint K013).
- `fxref core ns` → namespaces with counts, side mix, lib/proxy. `fxref core hooks` → the `CoreHook` list.
- `fxref core classes [prefix]` → option/record classes.

### 9.3 fxlint — core convention rules (group K)

Activation: a resource is a *core plugin* when its manifest has `dependency 'core'` or `'@core/import.lua'`;
it is *core itself* when the directory is `config.core.path` (or the manifest name/description matches core).
K rules run only for those; "plugin-only" rules never run inside core.

- K001 warn (plugin): `type(x) == 'function'` / `~= 'function'` — callbacks across the export hop are callable
  tables; use `Core.Utils.isCallable(v)`.
- K002 warn (both, client files only — the guard native is client-only): `NetworkGetEntityFromNetworkId(` or `GetEntityFromStateBagName(` used without a
  `NetworkDoesEntityExistWithNetworkId(` check earlier in the same function body.
- K003 info (plugin): raw `RegisterNetEvent`/`RegisterServerEvent`/`AddEventHandler` for a net event,
  `RegisterCommand`, `TriggerServerEvent`/`TriggerClientEvent`, `RegisterKeyMapping` — prefer `Core.Net.on`,
  `Core.Commands.register`, `Core.Net.emit`, `Core.Keys.register`.
- K004 warn (plugin): a registration INTO core at file scope — `Core.Markers.add`, `Core.TextLabels.add`,
  `Core.Blips.add`, `Core.Interactions.add`, `Core.Interactions.addGlobal/addFor`, `Core.Doors.add`,
  `Core.UI.registerPage` (client) — must be inside `Core.onReady(function() … end)` (replayed after core restarts).
- K005 info (plugin): an `onResourceStop` handler that only removes core registrations — core's registry does it.
- K006 error (both): `backdrop-filter` or `backdrop-blur` in `ui/**/*.{vue,css,js,ts}` — paints black in the CEF;
  use `data-core-blur`.
- K007 warn (plugin): `package.json` or `node_modules/` at the resource root or under `server/` — FXServer's
  Node sandbox/yarn builder problem; UI deps belong to the npm workspace (`ui/package.json.example` is fine).
- K008 info (plugin): `ui_page` or `files { 'ui/**' | 'html/**' }` in a plugin manifest — pages compile into
  core's shell; plugins ship no UI files.
- K009 warn (plugin): code uses `Core.` but the manifest lacks `dependency 'core'` or `'@core/import.lua'`
  is not the first `shared_scripts` entry.
- K010 info (plugin): a proxy-namespace call (`fxref core resolve` says `proxy`) at file scope of the main
  chunk — proxies need a coroutine and readiness; move into `Core.onReady`/a handler.
- K011 warn (plugin): `Core.Locale.t` used but `locales/*.json` missing from `files {}`.
- K012 warn (plugin): direct `SendNUIMessage`/`SendNuiMessage`/`RegisterNUICallback`/`SetNuiFocus` — use `Core.UI`.
- K013 warn (both): `Core.<Ns>.<fn>(` (or `Core.<Ns>.<sub>.<fn>(`) that `fxref core resolve` reports MISSING —
  probable hallucinated API (skip when the DB has no core index; exact-case match; `Core.Player(src):x()`
  handle sugar maps to `Core.Player.x`).
Docs in `docs/fxlint.md`; fixtures `tests/fixtures/core-plugin-bad/` and `core-plugin-good/` (the good one is
a trimmed copy of `core_example`'s shape) + `tests/test_fxlint.py` cases; `fxlint resources/core` and
`resources/core_example` must stay at 0 errors / 0 warnings after the change (K rules included).

### 9.4 fxnew — core plugins

`fxnew <name>` with `project.framework == core` (or `--framework core`) copies `core/templates/plugin` to
`<workspace>/<name>` and rewrites the placeholders exactly like `core/scripts/new-plugin.sh` (`my_plugin` →
name, `MyPluginPage` → `<CamelName>Page`, `MY_PLUGIN` → `<UPPER>`), fills `author`/`description`/`version`,
`--no-ui` deletes `ui/`, `--nui` keeps it; then self-lints (K rules on) and prints the next steps from
`new-plugin.sh` (ensure order, UI rebuild if a page). Refuses to overwrite. `--framework standalone` keeps the
old scaffold.

### 9.5 Skills, agents, workflow

- New skill `skills/fivem-core/SKILL.md` (≤ 220 lines) — the rulebook for (a) writing core plugins and (b)
  changing core itself; mirrors `core/AGENTS.md` (it stays the source of truth; the skill points to it and to
  the DESIGN § numbers), teaches the `fxref core` commands, the plugin template/manifest, the onReady rule, the
  validation order, Net/Callback/Commands/Keys usage, UI pages (compile into core's shell, Tailwind tokens,
  no backdrop-filter, rebuild + `restart core` + `ensure <plugin>`), the verification table (`scripts/check.sh`,
  `lua5.4 tests/*.lua`, `fxlint`, UI build, shell regression via `agent-browser`, `fxserver logs`,
  `fxclient logs`), and the deploy dance for manifest edits (`refresh`, `restart core`, `ensure <plugin>`).
- `fivem-build`: framework detection (config `project.framework` or the target manifest); when core: load
  `fivem-core`, scout also lists the `Core.*` APIs (verified with `fxref core show`), PLAN.md gets a "Core APIs"
  section and a "UI page: yes/no" line, scaffold with `fxnew`, implementer/reviewer have `fivem-core`
  preloaded, deploy step includes the UI rebuild + `restart core` when a page was added, checklist includes
  the core-specific items (interaction shows in range, page opens/closes, cleanup after `restart <plugin>`).
- Agents: implementer and reviewer `skills: [fivem-scripting, fivem-reference, fivem-core]`; the scout's prompt
  gets a "framework APIs" paragraph (`fxref core search/show`, list them separately from natives).
- `reference/frameworks.md`: a `core` section pointing to `fivem-core`; README: a "Working with core" section.
