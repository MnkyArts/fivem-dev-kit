---
name: fivem-server
description: Deploy, restart, or undeploy a FiveM resource on the local dev server, check whether FXServer is running, read server logs, or send rcon commands. Use for deploy/restart/undeploy requests, is the server up, reading errors after a test, or rcon.
---

# fivem-server — dev server operations

`fxserver` is on PATH while this plugin is enabled; absolute fallback: `${CLAUDE_PLUGIN_ROOT}/bin/fxserver`. All
paths come from `config.json`'s `server` block.

## Commands

- `fxserver status [--json]` — is FXServer running, which port, is txAdmin present.
- `fxserver deploy <resource_dir> [--no-ensure]` — symlink the resource into `[local]`, add an `ensure <name>`
  line to `server.cfg` (idempotent; the cfg is backed up once to `server.cfg.fxkit.bak` the first time this ever
  touches it).
- `fxserver undeploy <name>` — removes the symlink only; never edits `server.cfg`.
- `fxserver list [--json]` — what's currently deployed.
- `fxserver logs [--tail N] [--errors] [--all-errors] [--resource NAME] [--since MIN] [--follow] [--dedupe|--no-dedupe]`
  — read the log (see "Reading logs" below).
- `fxserver rcon <command...>` / `fxserver restart <resource>` — send a console command over rcon
  (`restart <resource>` is shorthand for `rcon "restart <resource>"`).

## txAdmin

This server is started and supervised by **txAdmin** via `Server/run.sh`. Never start `FXServer` directly and
never suggest stopping/restarting the txAdmin process itself — `fxserver restart <resource>` (rcon) is the
correct way to restart one resource.

## rcon password

Resolved from `--password`, else the environment variable named by `config.json`'s `server.rcon.password_env`
(default `FXRCON_PASSWORD`). If neither is set, `fxserver` refuses and explains rather than sending a garbage
password — it will **not** write `rcon_password` into `server.cfg` for you. If rcon fails with a missing
password, tell the user to add a `rcon_password "..."` line to `server.cfg` themselves and export that env var;
don't ask them to paste the value to you.

## Never print server.cfg

It contains the license key. Never read/cat/print it, even partially, and never echo `sv_licenseKey`. `deploy`
only ever reports the one `ensure <name>` line it added — trust that report instead of dumping the file to
verify it.

## Reading logs

Start narrow: `fxserver logs --errors --resource <name> --tail 200`. `--errors` already excludes Cfx's
server-list heartbeat noise by default (pass `--all-errors` if you deliberately need it back). Common meanings
(rulebook §13): `attempt to call a nil value` = a native that doesn't exist, or an export used before its
resource started; `attempt to index a nil value` = an unvalidated payload field; `attempt to compare nil with
number` = a missing type check; `was not safe for net` = the event needs `RegisterNetEvent`; `Reliable network
event overflow` = the engine rate limits (rulebook §4) were exceeded. Reach for `--follow` only while actively
watching a live repro, not as a default.

## Client-side errors

`fxserver.log` only ever shows what happened on the server. For client script errors, screenshots, fps/coords,
or resmon/profiling numbers, use the `fivem-client` skill instead (`fxclient logs --errors`,
`fxclient screenshot`, `fxclient profile <name>`).
