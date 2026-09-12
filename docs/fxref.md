# fxref

`fxref` is the native-database + docs search CLI of fivem-dev-kit. It merges four
data sources into one local SQLite database (`data/fxref.sqlite`) and gives you
fast (<200ms), scriptable lookup of GTA/CFX natives and docs.fivem.net pages —
so generated code can verify every native it calls instead of hallucinating one.

Run it as `bin/fxref <command> ...` (or `fxref ...` if the plugin dir is on
your PATH / symlinked into `~/.claude/skills/`). Every read command supports
`--json` for machine consumption. If the database hasn't been built yet, every
read command prints `fxref: database not built — run: fxref build` to stderr
and exits `2`.

## Data model, in one paragraph

A "native" row is keyed by `(hash, apiset)`. GTA natives (from alloc8or's
`natives.json` + `natives_gen9.json` + FiveM's `natives.json`) are merged by
their 64-bit game hash into a single `apiset='client'` row. CFX natives (from
`fivem/ext/native-decls/*.md`, with `natives_cfx.json` as a fallback for any
CFX native missing a `.md` file) keep their own declared apiset
(`client`/`server`/`shared`) and use a 32-bit joaat(name) hash. **The same C
name can legitimately produce two separate rows** — e.g. `SetEntityCoords`
exists both as a client GTA native (hash `0x06843DA7060A026B`) and as a CFX
server RPC native (hash `0xDF70B41B`) with a *different* parameter list.
`show` and `resolve` always report every matching row, clearly labelled by
`apiset`.

## Commands

### `fxref build [--no-download] [--force-download] [--natives-only | --docs-only] [--json]`

(Re)builds `data/fxref.sqlite` from scratch (natives + docs tables are always
fully replaced; `--natives-only`/`--docs-only` rebuild just one half and keep
the other table's existing contents untouched). Downloads FiveM's
`natives.json` and `natives_cfx.json` into `data/cache/` unless the cache is
younger than 7 days (`--force-download` re-downloads anyway; `--no-download`
never touches the network and uses whatever is cached, erroring only if
there's no cache at all). If a download fails, it falls back to the cache
with a warning on stderr instead of failing the build.

Takes well under a second on this machine (target: <60s). Prints a summary:

```
fxref build complete in 0.7s
  natives: 7701 rows (client 7343, server 284, shared 74)
    GTA (alloc8or legacy+gen9 + FiveM json): 6789
    CFX (native-decls + natives_cfx.json fallback): 912 (client 554, server 284, shared 74)
    unnamed: 13   unofficial-named: 9
    decls files: 823 (kept 792, excluded-by-game 31, unparsed 0); json-fallback used 120
  docs: 342 pages
```

### `fxref search <query...> [--ns NS] [--side client|server|shared|any] [--game legacy|gen9|any] [--limit N=15] [--all] [--json]`

Full-text search over native names, aliases, namespace, param names/types and
description. Query words are:

- split on camelCase/snake_case/hyphens/dots (`SetVehicleDoorsLocked`,
  `set_vehicle_doors_locked` and `set-vehicle-doors-locked` all tokenize the
  same way),
- prefix-matched (`lock` also matches `locked`),
- synonym-expanded both ways (see `lib/fxkit/synonyms.py` — e.g.
  `vehicle`/`car`/`veh`, `ped`/`player`/`character`/`npc`, `coords`/`position`,
  `invincible`/`godmode`/`god`, `door`/`doors`, `lock`/`locked`, ...).

A query that's exactly an identifier (a name, hash, or alias in any form) is
matched exactly first and marked `(exact)`; it's always first in the results.
Everything else is ranked by BM25 (name 10x, aliases 6x, namespace 3x, params
2x, description 1x weight) and then re-ranked to prefer names that contain
*all* of the query's concepts with the fewest extra words — so
`search lock vehicle doors` puts `SET_VEHICLE_DOORS_LOCKED` above
`SET_VEHICLE_DOORS_LOCKED_FOR_ALL_TEAMS`. Ties break by name, so results are
deterministic. `--limit` defaults to 15; `--all` removes the limit.

```
$ fxref search lock vehicle doors --limit 3
SET_VEHICLE_DOORS_LOCKED  [VEHICLE, client, build 323, legacy+gen9]  Lua: SetVehicleDoorsLocked(vehicle, doorLockStatus)  -- Locks the doors of a specified vehicle...
SET_VEHICLE_DOORS_LOCKED  [CFX, server]  Lua: SetVehicleDoorsLocked(vehicle, doorLockStatus)  -- Locks the doors of a specified vehicle...
SET_VEHICLE_INDIVIDUAL_DOORS_LOCKED  [VEHICLE, client, build 323, legacy+gen9]  Lua: SetVehicleIndividualDoorsLocked(vehicle, doorId, doorLockStatus)  -- doorId: see SET_VEHICLE_DOOR_SHUT
```

Each line is `NAME [ns, apiset, build N, legacy+gen9]  Lua: <signature>  -- <first sentence of description>`.
`--side` filters by apiset (`shared` rows always match any `--side`).
`--game legacy|gen9` filters GTA natives by build availability (CFX-only
natives, which don't have this concept, are never excluded by `--game`).
`--ns` matches either the primary or alternate namespace, case-insensitively.

### `fxref show <name|hash|luaName> [--json]`

Prints the full card for a native. Accepts **any** name form: the C name
(`SET_PED_INTO_VEHICLE`), the Lua/JS name (`SetPedIntoVehicle`), lowerCamel
(`setPedIntoVehicle`), a hash with or without `0x` and in either case
(`0xF75B0D629E1C063D`, `f75b0d629e1c063d`), an alias, or an unnamed native's
`N_0x...` form. If more than one row matches (client + server, or a hash that
happens to equal another native's jhash), **every** matching row is printed,
each clearly labelled.

```
$ fxref show GetShapeTestResult
=== GET_SHAPE_TEST_RESULT ===
hash: 0x3D87450E15D98694   jhash: 0xF3C2875A
ns: SHAPETEST
apiset: client
build: build 323 (legacy), build 811 (gen9)
aliases: 0x3D87450E15D98694, _GET_RAYCAST_RESULT

C:   int GET_SHAPE_TEST_RESULT(int shapeTestHandle, BOOL* hit, Vector3* endCoords, Vector3* surfaceNormal, Entity* entityHit)
Lua: GetShapeTestResult(shapeTestHandle) -> integer retval, boolean hit, vector3 endCoords, vector3 surfaceNormal, integer entityHit
JS:  GetShapeTestResult(shapeTestHandle): [number, boolean, [x, y, z], [x, y, z], number]
C#:  int API.GetShapeTestResult(int shapeTestHandle, ref bool hit, ref Vector3 endCoords, ref Vector3 surfaceNormal, ref int entityHit)

Returns the result of a shape test. ...

Parameters:
  int shapeTestHandle -- A shape test handle.
  BOOL* hit (out) -- Whether or not the shape test hit any collisions.
  ...

Returns: `0` if the handle is invalid, `1` if the shape test is still pending, ...

url: https://docs.fivem.net/natives/?_0x3D87450E15D98694
source: alloc8or-legacy,alloc8or-gen9,fivem-json
```

**How to read a card:**
- Title line: `(unofficial name)` after the name means it came from a FiveM
  community name (`_SOMETHING`) rather than alloc8or, with the leading `_`
  stripped.
- `hash` is the row's own identity (what's in the `(hash, apiset)` key);
  `jhash` (when different) is the joaat(name) hash — the same value a CFX
  RPC counterpart of this native, if any, would use as its own `hash`.
- `build:` legacy/gen9 build numbers the native was introduced in, or
  `legacy`/`gen9`/`legacy+gen9` availability when a build number isn't known.
- The four signatures (`C`, `Lua`, `JS`, `C#`) follow FiveM's own codegen
  rules exactly (`ext/natives/codegen_out_{lua,js,cs}.lua`):
  - A parameter is an **out param** iff its type ends in `*` and isn't
    `char*`/`const char*` (strings are always inputs).
  - **Lua/JS**: out params are dropped from the argument list and instead
    appended to the return list, in declaration order, after the native's own
    return value (if any) — `local ret, out1, out2 = Native(args)`. The one
    exception: if a native has *exactly one* out param and it's the *last*
    parameter, it's also accepted as an **optional trailing input** (shown
    with a trailing `?` in the arg list, e.g.
    `GetEntityPlayerIsFreeAimingAt(player, entity?) -> boolean retval, integer entity`) —
    that's how you seed an initial value for it.
  - **Lua** return types: `BOOL`→`boolean`, `int`→`integer`, `float`→`number`,
    `char*`→`string`, `Vector3`→`vector3`, `Any*`→`integer`. When there's only
    one thing to return and it's the native's own (unnamed) return value, the
    label is omitted (`-> vector3`, not `-> vector3 retval`); as soon as
    there's more than one, the native's own return value is labelled
    `retval` and every out param is labelled with its real name.
  - **JS**: same argument rules; the return is the bare type when there's
    only one return value, or a positional `[type1, type2, ...]` array when
    there's more than one. `Vector3` becomes `[x, y, z]`.
  - **C#**: every parameter stays in its original position; out params
    become `ref Type name` (never dropped/reordered). Hash-typed params
    render as `uint`.
- `Parameters:` lists every parameter in **C declaration order** (including
  out ones, marked `(out)`), with descriptions from FiveM's docs JSON when
  available.
- `source:` which of `alloc8or-legacy`, `alloc8or-gen9`, `fivem-json`,
  `native-decls`, `natives_cfx.json` contributed this row.
- Output is capped at ~80 lines in text mode; pass `--json` for the full,
  untruncated record (aliases/params/examples come back as real JSON arrays,
  not strings).

### `fxref resolve <name...> [--json]`

Batch existence/identity check — what `fxlint` uses to verify every native a
generated script calls is real. Accepts the same name forms as `show`.
**Always exits 0**, even when everything is missing (missing natives are
reported in the output, not via exit code — check `--json`'s `found` field,
or grep for `MISSING` in text mode). Fast: 200 names resolve in well under
300ms (single read-only DB connection, indexed lookups).

```
$ fxref resolve SetVehicleDoorsLocked GetEntityCoords NotARealNative
FOUND name=SET_VEHICLE_DOORS_LOCKED lua=SetVehicleDoorsLocked hash=0xB664292EAECF7FA6 apiset=client+server ns=VEHICLE
FOUND name=GET_ENTITY_COORDS lua=GetEntityCoords hash=0x3FEF770D40960D5A apiset=client+server ns=ENTITY
MISSING NotARealNative
```

With `--json`, each input becomes `{input, found, matches: [{name, lua_name,
hash, apiset, ns}, ...]}` — `matches` can have 0, 1, or more entries (2 for a
native that exists on both sides, like the examples above); the text form
above only shows one representative hash/ns per line, so use `--json` if you
need every match's own hash.

### `fxref ns [--json]`

Namespaces with native counts (`ns  count`, tab-separated; `--json` gives
`[{"ns": ..., "count": ...}, ...]`). Useful for `fxlint`/scripting to sanity
check a namespace exists before filtering `search --ns` by it.

### `fxref core <subcommand>` — the `core` framework API index

`core` is Liam's own FiveM framework (`resources/core`). `fxref core` indexes
its LuaLS definition file (`core/types/core.lua`) so generated plugin code can
verify a `Core.*` call the same way it verifies a native, instead of guessing
a signature. Everything here is inert when `config.json` has no `core` block:
each command prints a one-line hint on stderr and exits `2`.

The index carries four kinds of row in `core_api`:

| kind | what | count today |
|---|---|---|
| `function` | every `function Core.Ns.fn(...) end` stub, plus the directly callable namespaces (`Core.UI.progress(opts)`, `Core.Player(src)`) | 423 |
| `class` | `---@class Core*` option/record tables (`CoreInteractionOptions`, `CoreVehicleProps`, …) | 46 |
| `alias` | `---@alias Core*` enums (`CoreMoneyAccount`, `CoreHook`, …) | 17 |
| `hook` | one row per `CoreHook` value, with its side and handler arguments | 26 |

Each function row records its **side** (`server`/`client`/`shared`, from the
`(server)`/`(client)` marker in the stub's description) and its **access**:

- `lib` — compiled into the calling resource's own VM by `@core/import.lua`
  (no export hop, callable at file scope). Computed from `LIB_MODULES` in
  `core/import.lua` *and* the functions the matching `core/lib/<dir>/*.lua`
  file really defines, because `import.lua` puts the proxy behind everything a
  lib namespace does not implement in-VM (server `Core.Player.getInfo` is a
  proxy even though `Player` is a lib namespace; `Core.UI` only ships `on`/`off`).
- `proxy` — an `exports.core:call(...)` hop: it must run **in a coroutine**
  (thread, event handler, command) and **after `Core.onReady`**.

#### `fxref core build [--json]`

Rebuilds only `core_api` (≈ 0.1 s). `fxref build` also does this whenever core
is configured, so this is for "I just edited `types/core.lua`".

```
$ fxref core build
fxref core build complete in 0.03s  (core@28f48ab)
  functions: 423 (lib 109, proxy 314) in 45 namespaces
  classes: 46   aliases: 17   hooks: 26
```

#### `fxref core show <Core.Ns.fn | CoreClass | CoreAlias | hook> [--json]`

Accepts `Core.Money.add`, `Money.add`, `money.add` (case-insensitive), the
`Core.Player(src):getInfo()` handle sugar, a class/alias name, and a hook name.

```
$ fxref core show Core.Money.add
=== Core.Money.add ===
Core.Money.add(src, account, amount, reason?) -> boolean ok
side: server   access: proxy
note: proxy call -- it hops through core's `call` export, so it must run in a coroutine (thread, event handler, command) and after Core.onReady

(server) Adds a positive amount; false when it would pass `Config.Money.MaxAmount`.

Parameters:
  src      integer
  account  CoreMoneyAccount
             CoreMoneyAccount = 'cash' | 'bank' | string
  amount   integer -- > 0
  reason?  string -- shows up in the audit log and the `moneyChanged` hook

Returns:
  boolean ok

design: DESIGN §4.3
source: types/core.lua:2294
```

`Core*` option tables and enum aliases used as a parameter/field type are
expanded one level inline (above: the `CoreMoneyAccount` values; for
`Core.Interactions.add(opts)` the whole `CoreInteractionOptions` field list).

#### `fxref core search <query...> [--side server|client|any] [--ns NS] [--kind function|class|alias|hook] [--limit N=15] [--all] [--json]`

```
$ fxref core search interaction add --side client --limit 3
Core.Interactions.add(opts) -> string|nil id  [Interactions, client, proxy]  -- Registers an interaction.
CoreInteractionContext { id, coords, entity, distance, data }  [class, shared]  -- The context passed to interaction callbacks …
```

Format: `signature  [namespace, side, access]  -- first sentence`. Exact name
matches bubble to the top and are tagged `(exact)`.

#### `fxref core resolve <names...> [--json]`

Batch FOUND/MISSING check — this is what `fxlint`'s K013 shells out to (one
subprocess for the whole run). Always exits 0.

```
$ fxref core resolve Core.Money.add Money.remove Core.Nope.x
FOUND Core.Money.add  kind=function side=server access=proxy
FOUND Core.Money.remove  kind=function side=server access=proxy
MISSING Core.Nope.x
```

`--json` adds `case_exact`: a name that only matches case-insensitively
(`Core.money.add`) comes back `found: true, case_exact: false`, because Lua
itself is case-sensitive.

#### `fxref core ns [--json]` · `fxref core hooks [--json]` · `fxref core classes [prefix] [--json]`

```
$ fxref core ns
Money           6  [server:6]  [proxy:6]
UI             37  [client:20 server:2 shared:15]  [lib:2 proxy:35]  subs: hud, input, keys, locale, menu, progress, spinner, stats, state, textUI

$ fxref core hooks
ready                [shared] ()                           core started on this side — server: () / client: ()
playerDropped        [server] (src, charId)                (server) (src, charId), fired before the session is removed

$ fxref core classes CoreInter
CoreInteractionContext       class   5 fields  required: id, coords, entity, distance, data
CoreInteractionOptions       class  15 fields  required: data
```

### `fxref docs search <query...> [--limit N=10] [--all] [--json]`

Search docs.fivem.net pages (title 8x, headings 4x, body 1x weight). Same
camelCase/snake_case tokenization as native search, prefix-matched, no
synonym expansion.

```
$ fxref docs search state bags --limit 3
docs/scripting-manual/networking/state-bags  [scripting-manual]  State Bags  — ... known as '[state] [bags]'. ## Use ...
docs/scripting-reference/onesync  [scripting-reference]  OneSync  — ... you should use [state] [bags] if you need to trigger ...
docs/developers/legacy-vs-enhanced  [developers]  What's Changed in FiveM for GTAV Enhanced  — ... [State] [Bags] & Replication ...
```

Format: `id  [section]  title  — snippet` (snippet from FTS5 `snippet()`,
matched terms bracketed).

### `fxref docs show <path|id> [--section "Heading"] [--raw] [--json]`

Prints a page's markdown (front matter already stripped, Hugo shortcodes
simplified at build time — `{{% ... %}}` wrappers are removed but their inner
markdown is kept, `{{< ... >}}` tags are dropped except `{{< youtube ... >}}`
which becomes a watch URL). `--section "Heading Text"` prints only that
heading's block (matched case-insensitively; nested sub-headings are
included, the next same-or-higher-level heading is the cutoff). `--raw`
prints just the body with no added title/URL header. `id` is the page's path
relative to `content/`, without `.md` and without a trailing `_index`, e.g.
`docs/scripting-manual/networking/state-bags`.

### `fxref docs ls [prefix]`

Lists `id — title` for every page whose id starts with `prefix` (or every
page, if omitted).

### `fxref stats [--json]`

Prints the same summary `build` printed, read back from the `meta` table
(so it works without rebuilding) — build time, elapsed seconds, row counts,
and the git SHA of each source repo at build time. When `core` is configured
it also prints the core API counts and `core@<sha>`
(`git -C <core> rev-parse --short HEAD`, read-only):

```
core: 423 functions (lib 109, proxy 314) in 45 namespaces, 46 classes, 17 aliases, 26 hooks
  core@28f48ab  /home/liamrbsn/Dokumente/Entwicklung/FiveM/resources/core
```

### `fxref update-sources`

Runs `git -C <nativedb> pull --ff-only` and `git -C <fivem_docs> pull
--ff-only` (never touches the `fivem/` checkout — that one's big and the user
updates it themselves), force-redownloads both FiveM JSONs, rebuilds, and
prints the natives/docs row-count delta (`natives: 7701 -> 7705 (+4)`).

## Rebuilding / updating

- After changing local checkouts of `gta5-nativedb-data` or `fivem-docs`
  yourself: `fxref build`.
- To pull the latest data source commits and re-download the FiveM JSONs in
  one step: `fxref update-sources`.
- `fxref build --natives-only` / `--docs-only` rebuild just one half
  (useful when only one source changed) without touching the other table.
- After editing `core/types/core.lua`: `fxref core build` (≈ 0.1 s, only the
  `core_api` table). A full `fxref build` refreshes it too.
- The database is fully disposable and gitignored (`data/`) — delete
  `data/fxref.sqlite` and re-run `fxref build` any time.

## Performance & robustness notes

- Read commands open the database **read-only** via `file:...?mode=ro` and
  typically finish in 50-70ms end to end (well under the 200ms target),
  almost entirely Python/sqlite3 startup — actual query time is microseconds
  thanks to indexes on `hash`, `name`, `lua_name`, `ns`, and the
  `native_names(name_form)` lookup table (every C/Lua/lowerCamel name form,
  hash, and alias resolves through one indexed table).
- `build` uses one write transaction, `executemany` for bulk inserts, and a
  single FTS5 `... VALUES ('rebuild')` at the end rather than incremental
  per-row index updates.
- Every read command exits `2` (not built) or `1` (real error, e.g. `show`
  finding nothing) — never crashes on bad input; `resolve` is the one
  exception that always exits 0 so `fxlint` can rely on it unconditionally.
- All output is UTF-8/unicode-safe (verified by rendering every one of the
  7701 native cards, 342 doc pages and 512 `core_api` rows without error).
- The `core` commands never write to the core checkout: they read
  `types/core.lua`, `import.lua` and `lib/**/*.lua`, and shell out to
  `git -C <core> rev-parse --short HEAD` for the sha. Nothing else.
