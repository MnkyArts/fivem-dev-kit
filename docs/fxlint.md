# fxlint

Heuristic Lua/JS/TS linter for FiveM resources. Regex + brace/keyword-depth
tracking, no external tools, no dependencies beyond the Python 3 standard
library. Designed for very few false positives on real-world code (tested
against `spawnmanager` and `baseevents`, the official CitizenFX system
resources) rather than maximum theoretical coverage.

## Usage

```
fxlint <resource_dir|file...> [--json] [--no-verify] [--strict] [--rules R1,R2] [--ignore R1,R2]
```

- `<resource_dir|file...>` -- a resource directory (all `.lua`/`.js`/`.ts` files
  under it, `fxmanifest.lua`/`__resource.lua` themselves excluded from
  per-file rules but still checked for C004/C005), or one or more loose files.
  Loose files search upward (up to 8 parent directories) for an
  `fxmanifest.lua` to use as the resource root for cross-file rules and side
  detection; if none is found, the file's own directory is used.
- `--json` -- machine-readable report instead of text (shape below).
- `--no-verify` -- skip native-database verification (C007/C008), even if
  `fxref` is available.
- `--strict` -- warnings count as errors for the exit code (and are printed
  as `ERROR` instead of `WARN`).
- `--rules R1,R2` -- only run these rule ids.
- `--ignore R1,R2` -- skip these rule ids.
- `.fxlintrc.json` at the root of a single resource directory you pass
  directly (i.e. `fxlint <one-dir>`, not a loose-file or multi-target run) is
  auto-loaded for `"ignore": [...]` / `"rules": [...]` defaults; an explicit
  `--rules`/`--ignore` on the command line always overrides the file.

## Side detection

Each file's side (`client`/`server`/`shared`) comes from `fxmanifest.lua`
first: `client_script`/`client_scripts`, `server_script`/`server_scripts`,
`shared_script`/`shared_scripts`, in both the single-string and
`{ 'a', 'b' }` table forms (matching how `resource_init.lua` actually reads
the manifest -- a trailing `s` on the key is just sugar for the same
metadata). Globs (`client/*.lua`, `**/*.lua`, `**/cl_*.lua`) are expanded
against the resource directory; `@other-resource/file.lua` dependency-script
entries are recognised and skipped (never treated as a local file).

Files the manifest doesn't mention (or when there's no manifest) fall back to
a path heuristic: a top-level `client/`/`server/`/`shared/` directory, or a
`cl_`/`sv_`/`sh_` filename prefix, or a `_client`/`_server`/`_shared`
filename suffix, or (last resort) whichever of "client"/"server" appears in
the path. A file whose side can't be determined at all is still linted;
side-dependent rules (S00x, C007, C009, ...) just don't fire for it.

## Native verification (C007/C008)

fxlint collects call sites that look like natives (`PascalCase(...)` or
`N_0x<hex>(...)`, not preceded by `.`/`:` -- so `Config.Foo()`,
`lib.callback()`, `exports.ox_inventory:AddItem()`, `ESX.GetPlayerFromId()`
etc. are never treated as natives), drops ones defined locally in the
resource and ones the Lua/JS *runtime itself* provides (`CreateThread`,
`Wait`, `TriggerServerEvent`, `RegisterCommand`, `PlayerPedId`, `Entity`,
`exports`, `json`, `math`/`string`/`table`, ...; see
`lib/fxkit/lint/natives.py::RUNTIME_GLOBALS`), and -- if `$KIT/bin/fxref` and
`$KIT/data/fxref.sqlite` both exist -- resolves everything that's left in a
**single** `fxref resolve --json <names...>` subprocess call for the whole
run. If fxref isn't built yet, verification is skipped and one line is
printed: `natives: verification skipped (fxref database not built)`; C007/C008
simply don't fire. This never crashes fxlint either way.

## Suppressing a rule

```lua
-- fxlint-disable-next-line P002
Wait(0)

-- fxlint-disable P002,S001
-- (anywhere in the file -- disables those rules for the whole file)
```

```js
// fxlint-disable-next-line P002
await Delay(0);
```

`fxlint-disable`/`fxlint-disable-next-line` with no rule list disables
*everything* (file-scope or next-line respectively).

## Output

Text (default), one finding per line plus a `fix:` hint line, then a summary:

```
client/main.lua:14: WARN P002 Wait(0) inside a loop with no adaptive branch -- this is a per-frame loop
    fix: use an adaptive Wait (0 near / 250-1000 far), switch to an event/state bag/lib.points, or add a '-- per-frame:' justification comment if this really must run every tick
summary: 0 error(s), 1 warning(s), 0 info(s)
```

`--json`:

```json
{
  "files": {
    "client/main.lua": [
      {"line": 14, "rule": "P002", "level": "warn", "msg": "...", "hint": "..."}
    ]
  },
  "summary": {"errors": 0, "warns": 1, "infos": 0},
  "notes": []
}
```

`notes` carries tool-level messages that aren't tied to one file/line (the
native-verification skip note above, mainly) -- present but usually empty.

## Exit codes

- `0` -- no errors (warnings/infos are fine).
- `1` -- at least one error-level finding (or, with `--strict`, at least one
  warning).
- `2` -- a target path doesn't exist (usage error, not a lint result).

fxlint never crashes on bad input: a file that can't be parsed (or a rule
that throws while analysing it) is skipped with an info-level `PARSE`
finding (`could not analyse <file>: <error>`) instead of aborting the run.

## Rule catalogue

"Loop" below means a Lua `while`/`for`/`repeat` or a JS `while`/`for`, and
"handler" means the callback passed to `RegisterNetEvent`/`RegisterServerEvent`/
`AddEventHandler`/`RegisterCommand` (Lua) or `on`/`onNet`/`AddEventHandler`
(JS) -- fxlint only recognises the inline-anonymous-function form
(`AddEventHandler('x', function(...) ... end)`); a handler defined as a named
function and registered by reference is not tracked as a handler body.

### Performance (P0xx)

| ID | Level | Catches | Why | Fix |
|---|---|---|---|---|
| P001 | error | A `while`/`repeat` loop whose condition is `true`/`1` (`until false`/`0`) with no `Wait`/`Citizen.Wait`/`await Delay` anywhere in its body, and no `break`/`return` that can exit it. | With nothing to yield on, this blocks the single-threaded scripting runtime forever -- the resource (and on the server, potentially the whole game loop) hangs. | Add a `Wait(...)` every iteration, or a `break`/`return` if the loop is meant to terminate. `for` loops are never flagged (they're bounded by construction). |
| P002 | warn | `Wait(0..15)` / `await Delay(0..15)` directly inside a loop, when that loop isn't judged *adaptive* and isn't justified. | A tight per-frame loop with nothing gating it (`GetPlayers()` overhead, drawing every tick even off-screen, etc.) is the single most common FiveM performance mistake. | Use an adaptive wait (0 while something is actually happening nearby, 250-1000ms otherwise), move to an event/state-bag/`lib.points`/`lib.zones` trigger instead of polling, or add a `-- per-frame:` comment (Lua)/`// per-frame:` (JS) within 2 lines above the loop or on the `Wait`/`Delay` line itself if this genuinely must run every tick. |
| P003 | info | Same shape as P002 but the wait is `16..99`. | Not wrong, but tight enough to be worth a second look. | Raise towards 100-1000ms unless sub-100ms responsiveness is actually needed. |
| P004 | warn | `CreateThread(...)`/`setTick(...)` called directly inside a loop body, or anywhere inside an event handler body (including through nested closures, but a loop only counts if the call isn't itself inside a further nested closure -- see "adaptive/direct" note below). | Spawns a new thread/tick handler every iteration or every time the event fires -- a leak that compounds over a session. | Create the thread/tick once (e.g. at resource start, or guarded so it only runs once), not per-iteration/per-event. |
| P005 | warn | `GetPlayers`/`GetGamePool`/`GetActivePlayers`/`GetAllVehicles`/`GetVehiclePedIsIn`/`GetClosest*`/`json.encode`/`json.decode`/`TriggerServerEvent`/`TriggerClientEvent` called inside a loop that contains a `Wait`/`Delay` of `0..15` anywhere (regardless of whether that loop is "adaptive" -- even an adaptive loop still spends some frames at the low wait). | These all scan pools or serialize data; doing that every tick of a tight loop is measurably expensive (this is exactly the kind of call FiveM's `resmon` flags). | Cache the result, move the call outside the loop, or raise the interval so it runs far less often. |
| P006 | warn | `TriggerClientEvent(name, -1, ...)` (Lua) / `emitNet(name, -1, ...)` (server JS) directly inside a loop or inside a `SetTimeout`/`setInterval`/`setTick` callback. | Broadcasting to every connected client repeatedly is a flood risk (see the per-client net-event rate limits in `docs/fxserver.md`/DESIGN.md section 7) and wastes bandwidth. | Broadcast once on an actual state change, not on a timer/loop; or target specific players instead of `-1`. |
| P007 | info | `PlayerPedId()` called 2+ times inside one per-frame loop (a loop containing a `Wait`/`Delay` of `0..15`). | Each call is a native round-trip; the ped handle doesn't change mid-iteration. | Cache it once per iteration: `local ped = PlayerPedId()`. |

Loop/handler scoping detail: P004's loop check and P002/P003/P005/P007's "is
this call inside a per-frame loop" check are *direct* -- they stop at the
boundary of any nested function/closure defined inside the loop (except the
callback literal passed at the exact call site itself, e.g.
`CreateThread(function() ... end)`, which obviously doesn't count as "a
different closure"). A callback stored for later, unrelated execution
(`table.insert(callbacks, function() CreateThread(x) end)`) is correctly
*not* attributed to the loop it's textually inside, since its call frequency
isn't tied to the loop's iteration count. P004's *handler* check is the
opposite -- it walks through nested closures, since a handler's body
fundamentally still runs once per event firing regardless of how it's
internally structured.

"Adaptive" (P002/P003 exemption): a loop is adaptive when it contains 2+
`Wait`/`Delay` calls with different literal arguments *and* an `else`/`elseif`
appears between the first and last of those calls -- i.e. the canonical
`if nearby then Wait(0) else Wait(1000) end` shape. `while true do Wait(500)
... end` is fine outright (500 is outside the 0-15 warn range). A bounded
polling loop like `while not IsScreenFadedOut() do Wait(0) end` is *not*
adaptive by this definition (only one wait value) and is deliberately still
flagged per DESIGN.md's "loops guarded by `while isDrawing do` are per-frame
unless adaptive" rule, even though it's a common, generally-accepted idiom
(`spawnmanager.lua` itself does this in four places).

### Security (S0xx)

All of these apply to a **server net-event handler**: a handler in a
`server`-side file whose event name was registered via
`RegisterNetEvent`/`RegisterServerEvent` (Lua or JS) or `onNet` (JS)
somewhere in the resource -- either the fused `RegisterNetEvent(name,
function...)` form, or a separate `RegisterNetEvent(name)` earlier plus a
plain `AddEventHandler(name, function...)` elsewhere (both forms are used in
real Cfx.re code, e.g. `baseevents/server.lua`).

| ID | Level | Catches | Why | Fix |
|---|---|---|---|---|
| S001 | warn | The handler body never references `source`. | A net-event handler that doesn't look at who sent it usually means it isn't actually validating the caller. | Read `source` (see S010 below for *when*) and use it for anything security-relevant. |
| S002 | warn | A call to a sensitive function (`SetPlayerRoutingBucket`, `DropPlayer`, `ExecuteCommand`, `GiveWeaponToPed`, `SetEntityCoords`, `SetPedArmour`, `CreateVehicle*`, anything money/item/bank/cash/give/inventory/xp/level-named, `MySQL.*`/`exports.oxmysql`) that references one of the handler's own (non-`source`) parameters, with no `if`/`assert(`/`tonumber(`/`type(`/`#(`/`IsPlayerAceAllowed(` anywhere in the handler body. | A raw client-supplied number/string flowing straight into a money/item/teleport/kick-style call with zero validation is the classic FiveM exploit shape. | Check type, range, ownership and permission before acting on event data. |
| S003 | warn/info | A parameter named like `playerId`/`target`/`targetId`/`src`/`serverId` (case-insensitive) used as the player id in `GetPlayerPed(...)`/`DropPlayer(...)` (1st arg) or `TriggerClientEvent(name, ...)` (2nd arg), instead of `source`. Legitimate cross-player handlers (cuff, revive, give-to-player) are expected to do exactly this *after validating it* -- so the parameter's validation status anywhere in the handler body gates the level: **both** (a) a type-check (`type(param)`/`tonumber(param)`) **and** (b) a guard (a `#(`/`GetDistanceBetweenCoords`/`Vdist` distance check reading the param or its `GetPlayerPed(param)` handle; a permission/role check -- `IsPlayerAceAllowed(`, a call matching `(Is\|Has\|Can\|Check)...(Police\|Admin\|Job\|Permission\|Allowed\|Ace\|Role\|Duty\|Group)`, or a `Jobs.`/`Permissions.`/`ACL.`-prefixed call; or `GetPlayerPed(param) ~= 0`/`DoesEntityExist(` on its ped handle) present -> **no finding at all**. Only **one** of (a)/(b) -> **info** (partially validated, worth a glance). **Neither** -> **warn** (the original behaviour). | The client can put any id it wants in the payload; only `source` (the actual sender) is trustworthy without an explicit check -- but a properly validated (type-checked + permission/distance-guarded) use of a payload id is normal and correct, not a bug, so it shouldn't be flagged the same way as an unchecked one. | Use `source` for "the caller"; if acting on a *different* player id from the payload, both type-check it and guard it (permission/role check and/or a distance check against the fetched ped) before using it. |
| S004 | info | `RegisterNetEvent`/`RegisterServerEvent`/`onNet` for a name that's never passed to `TriggerServerEvent`/`TriggerClientEvent`/`emitNet` anywhere in this resource. | Registering an event as network-reachable when nothing ever triggers it over the network is needless attack surface (or just dead code). | If it's only ever used locally, use a plain `AddEventHandler`/`TriggerEvent` instead; otherwise this is probably fine (harmless if another *resource* triggers it, which fxlint can't see). |
| S005 | warn | `RegisterCommand(name, fn, false)` on the server where `name` looks admin-ish (kick/ban/give/money/tp/noclip/god/revive/announce/setjob/admin/weapon/delete, substring match). | `restricted=false` means *any* connected player can run it from their client console. | Register with `restricted=true` and grant it via an ACE permission (`add_ace`/`add_principal` in server.cfg), not `false`. |
| S006 | warn | `load(`/`loadstring(`/`os.execute(`/`io.popen(`/`dofile(` anywhere. | Dynamic code execution / shell access from a scripting resource is almost always either a bad idea or a backdoor. | Don't. |
| S007 | info | `TriggerServerEvent`(client)/`TriggerClientEvent`(server) for a name with no matching handler anywhere in *this* resource. | Usually a typo or a leftover from refactoring -- but genuinely fine if another resource owns the handler (fxlint only sees one resource at a time). | Double-check the event name, or confirm another resource actually registers a handler for it. |
| S008 | warn | A non-`source` parameter used as a table index (`arg[...]`) or in arithmetic (`arg + 1`, etc.), with no `type(`/`tonumber(`/`assert(` anywhere in the handler. | Indexing/doing math on an unchecked value can error the whole handler (a table `nil`/non-number crash) or be abused if it's used as a key into something sensitive. | `tonumber(arg)`/`type(arg) == '...'`/`assert(...)` before using it as a number or index. |
| S009 | warn | `SetEntityCoords(...)`/`SetPedIntoVehicle(...)` referencing a non-`source` parameter, with no `#( )`/`GetDistanceBetweenCoords(`/`Vdist(`/`Vdist2(` anywhere in the handler. | Teleporting/seating a player at client-supplied coordinates with no sanity check enables teleport-anywhere exploits. | Check the target is within a sane distance of something server-known before acting on it. |
| S010 | warn | The handler body references bare `source` *after* a `Wait(`/`Citizen.Wait(`/`Citizen.Await(` call earlier in the same handler. Lua only. | `source` is only valid until the handler's coroutine first yields -- the runtime resets it right after, so reading it again post-`Wait` may be a stale/wrong value (see DESIGN.md section 8, `runtime-facts.md`). | Capture it immediately: `local src = source` as the handler's very first statement, then use `src` from then on -- never re-read `source` later in the same handler. |

### Conventions / correctness (C0xx)

| ID | Level | Catches | Why | Fix |
|---|---|---|---|---|
| C001 | info | `Citizen.CreateThread`/`Citizen.Wait`/`Citizen.SetTimeout`/`Citizen.Trace`. | These are still valid, but every modern example (and `scheduler.lua` itself) uses the bare global aliases. | `CreateThread`/`Wait`/`SetTimeout`/`print` (for `Trace`) instead. |
| C002 | info | `GetPlayerPed(-1)`. | `PlayerPedId()` is the direct, documented way to get the local player's ped. | Use `PlayerPedId()`. |
| C003 | warn | A file-scope `function Name(...)` or `Name = ...`/`Name = function...` in Lua with no `local`, where `Name` isn't referenced as an `exports('name', Name)` argument or passed as a bare callback to `AddEventHandler`/`RegisterNetEvent`/`RegisterCommand`/`RegisterKeyMapping`/`SetTick`/`on`/`onNet` anywhere in the resource. Table-constructor assignments (`Config = {...}`, `Config = Config or {}`) and framework-bootstrap calls (`ESX = exports[...]:getSharedObject()`, `Ox = require '@ox_core...'`) are recognised idioms and never flagged -- those are the standard way config/framework namespaces cross file boundaries in FiveM (all scripts on one side of one resource share a single Lua global table). Lua only; JS's scoping model is different enough that this isn't applied there. | An unexported, uncalled-elsewhere global is either dead code or an accidental leak (missing `local`) that could collide with another resource's same-named global. | Add `local` (or `local function`), unless this genuinely is an intentional export/callback -- in which case this is a safe warning to suppress. |
| C004 | error | `__resource.lua` present in the resource directory. | Legacy pre-`fxmanifest.lua` manifest format; FXServer's modern (`is_cfxv2`) code paths need `fxmanifest.lua`. | Migrate to `fxmanifest.lua` and delete `__resource.lua`. |
| C005 | warn/info | fxmanifest.lua issues: missing `fx_version` (warn), missing `game` (warn), `use_experimental_fxv2_oal` present (info -- see below), scripts call `lib.<name>(...)` but there's no `@ox_lib/init.lua` in `shared_scripts` (warn). `lua54` is deliberately **not** checked either way -- it's a no-op since Lua 5.3 was removed (June 2025); see DESIGN.md section 8. | A resource with no `fx_version`/`game` won't load at all; missing ox_lib wiring means `lib.*` calls will error at runtime. `use_experimental_fxv2_oal` is real and useful but changes vector-argument behaviour (disables `vector3` auto-unpacking), so it's flagged as a heads-up, not an omission to fix. | Add the missing manifest keys; add `'@ox_lib/init.lua'` to `shared_scripts` and `dependency 'ox_lib'` if `lib.*` is used; if OAL is intentional, pass vector components individually (`SetEntityCoords(ped, v.x, v.y, v.z)`, not `SetEntityCoords(ped, v)`). |
| C006 | warn | (a) `AddEventHandler(name, ...)` whose name is triggered from the *other* side over the network (seen via `TriggerServerEvent`/`TriggerClientEvent`/`emitNet` on that side) but was never `RegisterNetEvent`/`RegisterServerEvent`'ed anywhere -- it won't actually be delivered. (b) `RegisterNetEvent(name)`/`RegisterServerEvent(name)` (no inline callback) with no `AddEventHandler` for that name anywhere on the same side. | (a) is a silent no-op bug (looks correct, never fires). (b) is either dead registration or a missing handler. | (a) Add the matching `RegisterNetEvent`/`RegisterServerEvent` call. (b) Add the `AddEventHandler`, or remove the unused registration. |
| C007 | error | A resolved native (via `fxref resolve`) whose apiset doesn't include this file's side (a client-only native used server-side, or vice versa; `shared` natives are always fine). Needs `fxref` built (see "Native verification" above). | Calling a client native server-side (or the reverse) is a runtime failure, not a style nit. | Call it from the correct side, or use a net event to reach the other side. |
| C008 | warn | A `PascalCase(...)`/`N_0x<hex>(...)` call that looks like a native but wasn't found in the native database. Needs `fxref` built. | Usually a typo, a hallucinated native name, or a deprecated/game-specific (e.g. RDR3-only) native not in this build's database -- worth a second look either way. | Double-check the spelling (`fxref search <name>`), or define it locally if it's actually a helper function you wrote. |
| C009 | error | `TriggerServerEvent(...)` in a **server** file (it only exists client-side), `TriggerClientEvent(...)` in a **client** file (it only exists server-side), or bare `source` referenced in a **client** file. Applies to both Lua and JS (JS defines the same global names). | Calling the wrong side's function is a hard runtime error (the global doesn't exist there); `source` on the client isn't the same "who sent this" concept the server has and is almost always a mistake. | Server -> client is `TriggerClientEvent`; client -> server is `TriggerServerEvent`; same-side is `TriggerEvent`/`emit`. Remove/rethink client-side `source` usage. |
| C010 | info | JS-only: server-side `on(name, ...)` for an event a client triggers via `TriggerServerEvent`/`emitNet` (confirmed by cross-file evidence, not guessed). | `on()` handles purely local events; a networked one needs `onNet()` to be marked net-safe the same way Lua's `RegisterNetEvent` does. | Use `onNet(name, ...)` instead of `on(name, ...)`. |
| C011 | info | `Wait(`/`Citizen.Wait(`/`await Delay(` inside a handler whose event name contains `ResourceStop` (`onResourceStop`/`onClientResourceStop`/`onServerResourceStop`). | The resource may already be torn down by the time an async wait resumes; stop handlers are expected to clean up synchronously. | Do cleanup synchronously; remove the wait. |
| C012 | info | `exports.<name>...`/`exports['<name>']...` used where `<name>` isn't declared via `dependency`/`dependencies` in `fxmanifest.lua`. (This is the DESIGN.md-specified fallback behaviour for C012 -- the more elaborate "cross-side server-only export used from client" check isn't reliably determinable heuristically and was intentionally not attempted; the id is reserved for that.) | An undeclared dependency means no defined start order and a confusing runtime error if the other resource isn't running, instead of FXServer's normal missing-dependency message. | Add `dependency '<name>'`. |

## Deliberate scope limits (not bugs)

- Only the inline-anonymous-function handler form is tracked as a "handler
  body" (`RegisterNetEvent('x', function(...) ... end)`); a handler defined
  as a named function and registered by reference (`AddEventHandler('x',
  myHandler)`) isn't recognised as one, so S001-S010/C006/C010/C011 won't see
  it. This matches the overwhelming majority of real FiveM code.
- Call arguments are read from a single source line; a call whose arguments
  span multiple lines may not have its literal string/number arguments
  picked up by rules that need them (event names, `Wait` intervals, etc.).
  Structural detection (is this call inside a loop/handler) is unaffected.
- Cross-file rules (S004/S007/C006/C010, and the C003 export/callback
  exemption) only see the resource being linted -- a name that looks unused
  or a handler that looks missing may genuinely be provided by *another*
  resource. These are reported at `info`/`warn`, not `error`, for exactly
  this reason.
