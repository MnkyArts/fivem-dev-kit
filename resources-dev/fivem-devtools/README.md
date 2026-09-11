# fivem-devtools

Client-side observability agent for fivem-dev-kit. Lets Claude Code, running
on the same Linux box as the FXServer, take screenshots of the game, CPU-
profile a resource, read the client's script-error log, get fps/coords/
resource-state, and run console commands on the client or server -- all
without the developer doing anything beyond playing. Full protocol,
security model, setup steps and command reference: `$KIT/docs/fxclient.md`.
Driven by `bin/fxclient` (see `lib/fxkit/client/`); the Windows-side upload
half is `client-agent/fxclient-agent.ps1`.

**Dev server only.** See "Security" below before you even think about
deploying this anywhere a real player could reach it.

## Configuration

Edit `shared/config.lua`:

| Key | Default | What it does |
|---|---|---|
| `AllowedIdentifiers` | `{ 'fivem:414243' }` | The only players who can use fivem-devtools (exact `"type:value"` strings, as returned by `GetPlayerIdentifierByType`). |
| `AcePermission` | `'fivem-devtools.use'` | ACE object accepted as an alternative to being on the identifier list (`add_ace group.admin fivem-devtools.use allow`). |
| `PollIntervalMs` | `250` | How often the server checks `queue/commands.json` for new work. |
| `MaxLogBytes` | `524288` | `out/client.log` is truncated to this many bytes (oldest data dropped first). |
| `MaxInfoResources` | `200` | Cap on how many resources one `info` command reports `GetResourceState` for. |
| `MaxEventsPerSecond` | `20` | Per-player rate limit on fivem-devtools' own net events. |

## Structure

```
fivem-devtools/
  fxmanifest.lua
  shared/config.lua
  server/main.lua       -- queue poll loop, HTTP handler, net events, `devtools` command
  client/main.lua        -- reacts to server-dispatched net events only, nothing unprompted
  agent/fxclient-agent.ps1  -- canonical copy; $KIT/client-agent/fxclient-agent.ps1 symlinks here
  queue/commands.json    -- written by bin/fxclient / `devtools ...`, gitignored
  out/                    -- results + uploaded artifacts, gitignored
```

## Security

- Every command (queue-driven or `devtools ...` console) only ever targets a
  *currently connected* player matching `Config.AllowedIdentifiers` or
  holding `Config.AcePermission` -- there is no "run on everyone" path.
- Every net event handler captures `local src = source` first and checks
  `isAllowedPlayer(src)` before doing anything.
- Upload endpoints (`/upload/*`) only accept requests from that same
  player's own `GetPlayerEndpoint` address, or localhost; everything else
  gets `403`.
- `serverexec` runs `ExecuteCommand` with whatever string the CLI gives it --
  treat `fxclient exec --server` like server console access, because that's
  what it is.
- Do not `ensure` this on anything but your local dev server. It has no
  concept of "safe for a real player base".

## In-game test checklist

- [ ] `refresh` then `ensure screenshot-basic`, `ensure fivem-devtools` on the server console -- no errors in the console or `fxserver.log` (first start builds screenshot-basic's `dist/` via the `yarn`/`webpack` system resources -- can take a few seconds).
- [ ] `fxlint resources-dev/fivem-devtools` -- 0 errors before you deploy.
- [ ] `devtools info` from the server console (with the dev player connected) -- `out/<id>.json` appears with sane fps/coords.
- [ ] `fxclient status` reports the resource deployed and screenshot-basic present.
- [ ] Start `fxclient-agent.ps1` on the gaming PC, then `fxclient logs --tail 5` -- confirm `out/agent-status.json`'s `lastSeen` is recent.
- [ ] `fxclient screenshot` -- a PNG appears at the printed path.
- [ ] `fxclient profile <a-resource-you-are-testing> --frames 120` while exercising that resource in-game -- a table with plausible ms/frame numbers comes back.
- [ ] Restart the resource (`restart fivem-devtools`) while a command is mid-flight -- no crash, `lastId` in `out/state.json` prevents replay.
