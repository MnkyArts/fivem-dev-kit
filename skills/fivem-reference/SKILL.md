---
name: fivem-reference
description: Search and read the local FiveM/Cfx.re native database and docs.fivem.net mirror via fxref. Use for any question about a native or FiveM API, how do I do X in FiveM, before writing any native call, when the user pastes a native or hash name, or to check apiset/build/gen9 availability or docs pages.
---

# fxref — native + docs reference

`fxref` is on the Bash PATH while this plugin is enabled, so every command below is just `fxref ...`. Absolute
fallback if PATH isn't set up: `${CLAUDE_PLUGIN_ROOT}/bin/fxref`.

## When to use this

Before writing **any** native call, when the user asks how to do something in FiveM, when they paste a native
name or hash, or when you need a docs.fivem.net page (state bags, OneSync, manifest keys, ...). Never write a
native from memory — always look it up in this session first.

## Commands

- `fxref search <query...> [--ns NS] [--side client|server|shared|any] [--game legacy|gen9|any] [--limit N] [--all] [--json]`
  — find candidates by description/name.
- `fxref show <name|hash|luaName> [--json]` — the full card for one native (see below).
- `fxref resolve <name...> [--json]` — batch existence/identity check; always exits 0, so grep the output for
  `MISSING` or check `--json`'s `found` field. Use this to verify a whole list of natives at once.
- `fxref ns [--json]` — namespaces with counts.
- `fxref docs search <query...> [--limit N] [--json]` — search docs.fivem.net pages.
- `fxref docs show <path|id> [--section "Heading"] [--raw]` — read a docs page (or one heading of it).
- `fxref docs ls [prefix]` — list docs page ids under a prefix.
- `fxref stats [--json]` — row counts + each source repo's git SHA at last build.
- `fxref update-sources` — git-pulls the nativedb + fivem-docs checkouts, re-downloads FiveM's JSONs, rebuilds.

## Reading a `show` card

- Title: `(unofficial name)` after the name means it's a community `_name` from FiveM's docs JSON, not an
  official alloc8or name.
- `apiset`: `client`, `server`, or `shared`. A `client` native only works in a client-side file; `server` only
  server-side; `shared` works in both. The **same C name can exist as two separate rows** with different
  signatures (e.g. `SetEntityCoords` as a client GTA native vs. a CFX server RPC) — `show`/`resolve` print every
  matching row, each labelled by apiset.
- `build:` the legacy/gen9 game build the native was introduced in (or `legacy`/`gen9`/`legacy+gen9`
  availability when no build number is known).
- `Lua:` signature already applies FiveM's own codegen rules — out-params are dropped from the argument list and
  appended to the return list, so read it as-is: `local ret, out1 = Native(args)`. Don't re-derive this from the
  `C:` signature yourself.
- `aliases`: old/alternate names — useful when a pattern or an old snippet uses a different name for the same
  native.

## Search tips

- Filter by side early: `--side client` or `--side server` cuts noise fast once you know which side owns the
  feature.
- Try at least **two phrasings** before concluding nothing fits — search is synonym-expanded (vehicle/car/veh,
  ped/player/npc, coords/position, lock/locked, ...) but a very specific query can still miss; e.g. try both
  `search lock vehicle doors` and `search vehicle door lock`.
- If you already know (or suspect) the exact name, `fxref show <name>` directly is faster and more precise than
  `search`.

## The MISSING rule

If `fxref resolve`/`show` reports a name as not found, **it does not exist** — with one exception: FiveM's Lua
*runtime* provides some helpers that are not natives and were never going to be in this database (`GetPlayers`,
`GetPlayerIdentifiers`, `GetPlayerTokens`, `RegisterNUICallback`, `exports(...)`/`exports['x']:y()`,
`PerformHttpRequestAwait`). If a MISSING name isn't one of those, don't write it — search for the real name
instead, or tell the user it doesn't exist.

## If the database is missing

Read commands print `fxref: database not built — run: fxref build` and exit `2`. Run `fxref build` (a few
seconds; downloads FiveM's JSONs unless already cached) and retry.

## Data freshness

`fxref stats` shows each source's git SHA and row counts as of the last build — check it if native data seems
stale. `fxref update-sources` pulls the `gta5-nativedb-data` and `fivem-docs` checkouts and re-downloads FiveM's
JSONs, then rebuilds; it deliberately does **not** touch the (large) `fivem/` checkout — refresh that one
yourself with a manual `git -C <fivem path> pull` when CFX native-decls need updating.
