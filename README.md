# fivem-dev-kit

A Claude Code plugin that turns Claude into a FiveM (Cfx.re / GTA V) resource developer: it looks up natives
from a merged, locally indexed native database instead of guessing, searches docs.fivem.net, writes resources
that follow a hard set of performance and security rules, lints them, deploys them to the local dev server, and
reads the server log. You test in-game — Claude does everything up to that point.

## Requirements

- `python3` >= 3.10 (stdlib only — no pip installs).
- SQLite with the FTS5 extension (bundled with Python's `sqlite3` on any reasonably modern build; check with
  `python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE t USING fts5(x)')"`).
- Three source checkouts, plus a workspace directory, referenced from `config.json`:
  - `gta5-nativedb-data` (alloc8or's native DB)
  - `fivem` (FiveM engine source — CFX native-decls, codegen rules)
  - `fivem-docs` (docs.fivem.net source)
  - `resources/` — where new resources get created/deployed from
- Claude Code 2.1.268+.

## Install

The kit is its own local marketplace (`.claude-plugin/marketplace.json`, source `./`). Install it at user
scope like any other plugin:

```
claude plugin marketplace add /path/to/fivem-dev-kit     # registers the "fivem-local" marketplace
claude plugin install fivem-dev-kit@fivem-local          # user scope: available in every project
```

Claude Code copies the plugin into `~/.claude/plugins/cache/fivem-local/fivem-dev-kit/<version>/`. To keep
that copy in sync with this checkout (live edits, one shared `data/` DB, one `config.json`), replace the copy
with a symlink once:

```
rm -rf ~/.claude/plugins/cache/fivem-local/fivem-dev-kit/0.1.0
ln -s /path/to/fivem-dev-kit ~/.claude/plugins/cache/fivem-local/fivem-dev-kit/0.1.0
```

(`claude plugin update fivem-dev-kit` would recreate the copy — redo the symlink afterwards, or bump the version
in both `plugin.json` and `marketplace.json` and reinstall.) Confirm it loaded:

```
claude plugin list                                   # fivem-dev-kit@fivem-local, scope user, enabled
claude plugin validate /path/to/fivem-dev-kit
claude plugin details fivem-dev-kit@fivem-local      # 6 skills, 3 agents, 1 hook
```

Alternative without a marketplace: `ln -s /path/to/fivem-dev-kit ~/.claude/skills/fivem-dev-kit` loads it as
`fivem-dev-kit@skills-dir` (do not use both at once — the skills would load twice). Editing `SKILL.md` files
takes effect immediately; editing `agents/`/`hooks/` needs `/reload-plugins` or a restart.

## First run

```
fxref build
```

Builds `data/fxref.sqlite` from the three source checkouts (a few seconds; downloads two small FiveM JSON files
into `data/cache/` unless already cached). Nothing else works usefully until this has run once.

## Updating data

```
fxref update-sources          # git-pulls gta5-nativedb-data + fivem-docs, re-downloads the FiveM JSONs, rebuilds
git -C /path/to/fivem pull    # the fivem/ checkout is large -- pull it yourself when you need fresh CFX decls
fxref build                   # after pulling fivem/ yourself, or after any other manual change to a checkout
```

## The five CLIs

All five live in `bin/` and are on the Bash PATH while the plugin is enabled — invoke them as `fxref`/`fxlint`/
`fxnew`/`fxserver`/`fxclient`. Full reference for each: `docs/{fxref,fxlint,fxnew,fxserver,fxclient}.md`.

**`fxref`** — native + docs search.
```
fxref search lock vehicle doors --side client
fxref show SetVehicleDoorsLocked
fxref resolve SetVehicleDoorsLocked GetEntityCoords NotARealNative
```

**`fxlint`** — heuristic Lua/JS/TS linter (performance P0xx, security S0xx, conventions C0xx).
```
fxlint resources/my-shop
fxlint resources/my-shop --json --strict
fxlint client/main.lua --ignore P003
```

**`fxnew`** — scaffold a new resource (every generated resource lints clean by construction).
```
fxnew my-garage
fxnew my-shop --framework qb --ox-lib
fxnew my-menu --nui --author "Jane Doe" --desc "A simple radial menu"
```

**`fxserver`** — local dev-server deploy/logs/rcon.
```
fxserver deploy resources/my-shop
fxserver logs --errors --resource my-shop --tail 200
fxserver rcon "say hello from claude"
```

**`fxclient`** — client-side observability (screenshots, profiling, logs, exec) via the `fivem-devtools`
dev-server resource and a PowerShell agent on the gaming PC.
```
fxclient setup
fxclient screenshot --resmon
fxclient profile my-shop --frames 300
```

## Skills (when Claude reaches for them)

| Skill | Triggers on |
|---|---|
| `fivem-reference` | Any question about a native/FiveM API, before writing a native call, a pasted native name. |
| `fivem-build` (`/fivem-build <what to build>`) | "build/create/add/implement a FiveM resource/script/feature". Runs the full plan -> scout -> implement -> lint -> review -> deploy -> test-checklist pipeline. |
| `fivem-review` (`/fivem-review <resource path>`) | "review/audit/check this resource" before shipping. |
| `fivem-server` | Deploy/restart/undeploy, "is the server up", reading errors, rcon. |
| `fivem-client` | Screenshots, client-side performance/profiling (resmon numbers), client script errors, client info, or running a console command on the client/server without rcon. |

(`fivem-scripting`, owned by a separate workstream, is the underlying rulebook these skills orchestrate against —
loops/Wait rules, event/security patterns, state bags, framework adapters, review checklist.)

## Agents + model tiers

Fixed by role, never overridden, never `fable`:

| Agent | Model | Job |
|---|---|---|
| `fivem-native-scout` | haiku | Turn a feature spec into a verified (fxref-checked) native list + docs pages. Never writes code. |
| `fivem-implementer` | sonnet | Implement a given plan; verifies every native first; self-lints with `fxlint`. |
| `fivem-reviewer` | opus | Review a resource/diff like a cheater and like `resmon`; ranked findings, no rewrites. |

The main session (not a subagent) always plans, delegates, and verifies — it never writes a native from memory,
and it re-checks every subagent's report (re-runs `fxlint`, spot-checks natives) before trusting it.

## The hook

`hooks/hooks.json` runs `hooks-handlers/post-edit-lint.py` after every `Write`/`Edit`/`MultiEdit`. It only acts
on `.lua`/`.js`/`.ts` files that sit inside a real resource (an `fxmanifest.lua` in the same directory or up to
3 parents up) and are outside the kit itself and the FiveM source checkouts. When it finds errors/warnings it
adds a short `fxlint: N error(s), M warning(s) in <file>: ...` note to Claude's context; otherwise it stays
silent. It never blocks a tool call, never raises, and always exits 0.

## The workflow

```
/fivem-build add a lockpicking minigame for unlocking cars without keys
```

Claude restates the spec, spawns the scout for verified natives, writes a plan, scaffolds with `fxnew`, spawns
the implementer, lints and spawns the reviewer, fixes findings, deploys with `fxserver`, and prints an in-game
test checklist — then stops. You test in-game and report back (what happened, or paste an error); Claude reads
`fxserver logs --errors --resource <name>` and iterates.

## config.json

Not in git (see `.gitignore`) — copy `config.example.json` to `config.json` and fill in real paths. Keys:

| Key | Meaning |
|---|---|
| `sources.nativedb` / `fivem` / `fivem_docs` | Paths to the three source checkouts. |
| `sources.natives_json_url` / `natives_cfx_json_url` | Where `fxref build`/`update-sources` download FiveM's native JSONs from. |
| `server.root` | The txAdmin/FXServer install root. |
| `server.data_dir` | The txAdmin server-data profile dir (`server.cfg` + `resources/` live under here). |
| `server.local_resources_dir` | Where deployed resources get symlinked (relative to `data_dir`), typically `resources/[local]`. |
| `server.log_file` | Path to `fxserver.log` for `fxserver logs`. |
| `server.game_build` | The game build this server runs (informational). |
| `server.rcon.host` / `port` / `password_env` | rcon target + which env var holds the password. |
| `project.workspace` | Default parent directory for `fxnew`. |
| `project.language` / `framework` / `ox_lib` / `game` / `author` | Defaults for `fxnew` and the rulebook. |

## Client-side tooling

`fxclient` lets Claude see and act on the developer's actual running game client — screenshots, CPU profiling,
the client's script-error log, an fps/coords/resource-state snapshot, and one-off console commands — without
Liam doing anything beyond playing. Full reference: `docs/fxclient.md`.

**Pieces**

| Piece | Runs on | What it does |
|---|---|---|
| `resources-dev/fivem-devtools/` | FXServer (dev box) | Polls a command queue, dispatches work to the dev player, runs the upload HTTP handler. |
| `client-agent/fxclient-agent.ps1` | Windows gaming PC | Tails the client's script-error log and uploads profiler JSON dumps, continuously. |
| `bin/fxclient` (`lib/fxkit/client/`) | Linux dev box | The CLI Claude actually runs: enqueues commands, waits for and formats results. |

**One-time setup** (`fxclient setup` prints the exact commands for this machine; nothing here happens
automatically):

1. `fxserver deploy` both `screenshot-basic` and `resources-dev/fivem-devtools/` (symlinks + `ensure` lines).
2. Add two ACE lines to `server.cfg` by hand: `add_ace resource.fivem-devtools command allow` and
   `add_ace group.admin fivem-devtools.use allow`.
3. `refresh` then `ensure screenshot-basic` / `ensure fivem-devtools` on the server console.
4. On the gaming PC (PowerShell): run the two `irm .../agent -OutFile ...` / `powershell -File ...` lines
   `fxclient setup` prints — leave it running for the whole play session.
5. `fxclient status` to confirm the resource is deployed and the agent has checked in.
6. If `profiler`/`resmon` commands are silently ignored, add `+set moo 31337` to the FiveM shortcut target —
   FXServer blocks those commands in production mode otherwise.

**Commands**

```
fxclient screenshot --resmon
fxclient profile my-shop --frames 300
fxclient logs --errors --resource my-shop
fxclient info --json
fxclient exec --server "restart my-shop"
fxclient status
```

**Limitations** (full list: `docs/fxclient.md` §8): resmon-quality numbers only come from `profile`/
`screenshot --resmon`, never from `info`; restricted `ExecuteCommand`s still need their own `add_ace` grant;
`profile` needs the PowerShell agent running on the gaming PC (a timeout almost always means it isn't);
`logs --resource` is a best-effort substring match, not a structured filter; **dev server only** — never deploy
`fivem-devtools` to a server a real player can reach.

## Troubleshooting

- **`fxref: database not built`**: run `fxref build`.
- **Plugin doesn't show up / commands missing**: `claude plugin validate /path/to/fivem-dev-kit`, then
  `claude plugin list` and check for `fivem-dev-kit@skills-dir`. Confirm `~/.claude/skills/fivem-dev-kit` is a
  symlink pointing at this directory, then `/reload-plugins` (or restart).
  Also try `claude plugin details fivem-dev-kit@skills-dir` for its full inventory.
- **`fxref`/`fxlint`/`fxnew`/`fxserver` not found on PATH**: the plugin puts `bin/` on the Bash tool's PATH only
  while it's enabled — use the absolute path (`${CLAUDE_PLUGIN_ROOT}/bin/fxref` from inside a skill/agent, or
  the real filesystem path from a terminal) as a fallback, and check the four files in `bin/` are executable
  (`chmod +x`).
- **A resource fails `fxlint` on natives that should exist**: make sure `fxref build` has run at least once —
  native verification (C007/C008) is silently skipped otherwise.

## Safety notes

- `server.cfg` holds the license key. Nothing in this kit ever prints it — `fxserver deploy` only ever reports
  the single `ensure <name>` line it added, never the file's contents.
- `fxserver deploy` **does** edit `server.cfg` (it inserts that `ensure` line) and creates a one-time backup,
  `server.cfg.fxkit.bak`, the first time it ever touches a given cfg — that backup is never overwritten again.
- `resources-dev/fivem-devtools/` (client-tooling workstream) is dev-server-only scaffolding for talking to a
  running game client — it must never be deployed to, or `ensure`d on, a production server.
