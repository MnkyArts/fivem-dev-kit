---
name: fivem-client
description: Screenshot, CPU-profile, or read script errors from the developer's actual running FiveM game client via fxclient, or run a console command on the client/server without rcon. Use when the user wants a screenshot, resmon/performance numbers, client-side errors, player/client info, or to execute a console command on the client.
---

# fivem-client — client-side observability

`fxclient` is on PATH while this plugin is enabled; absolute fallback: `${CLAUDE_PLUGIN_ROOT}/bin/fxclient`. It
talks to the developer's actual running game client through the `fivem-devtools` dev-server resource plus a
PowerShell agent on the gaming PC. Full reference: `docs/fxclient.md`.

## One-time setup

Run `fxclient setup` — it never edits `server.cfg` or creates symlinks itself, only reports what's missing and
prints the exact commands to run (docs §4):

1. `fxserver deploy` both `screenshot-basic` and `resources-dev/fivem-devtools/` (symlinks + `ensure` lines).
2. Add two ACE lines to `server.cfg` by hand (deploy never adds ACE grants):
   `add_ace resource.fivem-devtools command allow` and `add_ace group.admin fivem-devtools.use allow`.
3. `refresh` then `ensure screenshot-basic` / `ensure fivem-devtools` on the server console.
4. On the gaming PC (PowerShell): run the `irm .../agent -OutFile ...` + `powershell -File ...` one-liner
   `fxclient setup` printed for this machine's LAN IP. Leave it running for the whole play session — it's what
   uploads client logs and profiler captures.
5. `fxclient status` to confirm the resource is deployed and the agent has checked in.

`fxclient profile` and `--resmon` need the FiveM client started with `+set moo 31337` (add it to the FiveM
shortcut target on the gaming PC): the client refuses `profiler`/`resmon` in production mode even when a
resource issues them (verified: "Command profiler is disabled in production mode"). Screenshots, `info`,
`logs` and `exec` work without it; `fxclient profile` prints the fix itself when it sees that log line.

## Commands

- `fxclient setup` — report what's deployed/missing and print the rest of the setup steps.
- `fxclient screenshot [--resmon] [--jpg] [--timeout N]` (default timeout 20) — capture from the dev player;
  prints the absolute PNG/JPG path as the last stdout line. `--resmon` shows the resmon overlay for 1.5s first.
- `fxclient profile <resource> [--frames N] [--timeout N] [--json]` (default frames 300, timeout 60) —
  CPU-profile one resource (`profiler resource <name> <frames>`), then print a per-resource table + verdict
  against the resmon targets (idle 0.00-0.02ms, active <0.10ms).
- `fxclient logs [--tail N] [--errors] [--resource NAME]` (default tail 80) — the client's CitizenFX_log tail
  uploaded by the PowerShell agent. `--resource` is a best-effort substring match, not a structured filter.
- `fxclient info [--json] [--timeout N]` (default timeout 15) — fps/coords/heading/vehicle/ped-health/
  resource-state snapshot.
- `fxclient exec (--client CMD | --server CMD) [--timeout N]` (default timeout 20) — run one console command on
  the dev player's client, or on the server console.
- `fxclient status [--json]` — deployment state, queue length, last command's result, agent last-seen time. Run
  this first in a new session, or after a while of silence.

## The dev loop

- **After deploying/restarting a resource**: `fxclient screenshot` to see what the developer sees, and
  `fxclient logs --errors --resource <name> --tail 50` to catch load-time breakage. Open the PNG with the Read
  tool to actually look at it — don't just report the path.
- **While the developer exercises a feature**: `fxclient profile <name> --frames 300` (~5s of gameplay at
  60fps) captures exactly that window. Ask them to do the thing, then run it.
- **After any "done" or "broken" report**: `fxclient logs --errors` first — script errors are the fastest,
  cheapest signal, faster than asking what they saw.
- **To sanity-check state**: `fxclient info --json` — is the player where you expect, in the right vehicle, is
  a resource actually started.
- **To iterate without asking the developer to type anything**: `fxclient exec --client "..."` /
  `--server "..."` for one-off console commands.

## Security

**Dev server only — never deploy `fivem-devtools` to anything a real player could reach; there is no "safe for
production" mode.** Every command only ever targets a currently-connected player matching
`Config.AllowedIdentifiers` or holding `Config.AcePermission` — there is no "run on everyone" path. Treat
`fxclient exec --server` like server console access, because that's exactly what it is. Restricted commands
still need their own `add_ace resource.fivem-devtools command.<name> allow` in `server.cfg`.

## Expected failures

- `no dev player online (no connected player matches Config.AllowedIdentifiers)` — nobody who qualifies is
  connected; ask the developer to join.
- `no result for command N after ...s ... is the fivem-devtools resource deployed, ensured, and is a dev
  player online? try fxclient status.` — start with `fxclient status`.
- `profile` times out but `screenshot`/`info` work fine — `fxclient-agent.ps1` almost certainly isn't running
  on the gaming PC; it's the only thing that uploads profiler captures.
