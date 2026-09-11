# fxclient

`fxclient` is fivem-dev-kit's **client-side observability** CLI. It lets
Claude Code -- running on the Linux dev box, alongside the FXServer -- see
and act on what's happening on the developer's Windows gaming PC: take
screenshots, CPU-profile a resource, read the client's script-error log, get
fps/coords/resource state, and run console commands on the client or server.
All of it works without Liam doing anything beyond playing.

This document covers what each piece does, exact setup, the security model,
the command reference, how Claude should use it in a dev loop, and known
limitations. It is the authoritative source for all of this -- `bin/fxclient
--help`, the `fivem-devtools` resource's own `README.md`, and
`client-agent/fxclient-agent.ps1`'s header comment are all short pointers
back here.

## 1. The pieces

| Piece | Runs on | What it does |
|---|---|---|
| `resources-dev/fivem-devtools/` | FXServer (Linux dev box) | The FiveM resource. Polls a command queue, dispatches work to the dev player, runs an HTTP handler for uploads, forwards client debug prints to the server console. |
| `client-agent/fxclient-agent.ps1` | Windows gaming PC | A symlink to `resources-dev/fivem-devtools/agent/fxclient-agent.ps1` (see below for why it lives there). Tails the client's script-error log and uploads new profiler JSON dumps to the server, forever, on an interval. |
| `bin/fxclient` (`lib/fxkit/client/`) | Linux dev box | The CLI: enqueues commands, waits for and formats results. This is what Claude actually runs. |
| `tests/test_fxclient.py` + `tests/fixtures/` | Linux dev box | Plain-python3 tests: queue round-trip, the profiler-trace analyzer against a synthetic fixture, a Python mirror of the multipart parser, client-log filtering, and (if `lua`/`luac` are on PATH) a pure-Lua syntax check and unit-test harness for the resource's own Lua. |

### Why the PowerShell agent lives inside the resource

The architecture asked for `agent/fxclient-agent.ps1` to be shippable as
**both** a file inside the FiveM resource (so the server can serve it over
HTTP at `GET /agent` for the one-liner install) **and** a file at
`client-agent/fxclient-agent.ps1` for a human to find directly in the repo.
`LoadResourceFile` is `apiset: shared` (works without a `files{}` manifest
entry when called *server-side* -- see `LoadResourceFile.md`, and §3 below),
so the server reads it straight off disk; there is exactly one canonical
copy, at `resources-dev/fivem-devtools/agent/fxclient-agent.ps1`, and
`client-agent/fxclient-agent.ps1` is a **relative symlink** to it
(`../resources-dev/fivem-devtools/agent/fxclient-agent.ps1`) so both paths
always serve byte-identical content with nothing to keep in sync by hand.

## 2. Architecture: how a command flows

```
 Claude Code                 FXServer (fivem-devtools)         Windows gaming PC
 -----------                 --------------------------         ------------------
 bin/fxclient screenshot
   |
   | append {id, cmd, args}
   v
 queue/commands.json  <----- polled every 250ms (Wait(Config.PollIntervalMs),
   |                          one thread, one LoadResourceFile read)
   | (same files on disk --                |
   |  CLI and resource share               | id > lastId? -> dispatch
   |  the same filesystem)                 v
   |                          TriggerClientEvent('fivem-devtools:client:screenshot', ...)
   |                                        |
   |                                        v                    client/main.lua reacts:
   |                                                              ExecuteCommand('resmon 1')?
   |                                                              Wait(1500)
   |                                                              screenshot-basic ->
   |                                                              POST multipart/form-data
   |                          <-------------------------------------  to /upload/screenshot?id=N
   |                          multipart parsed (byte-safe,
   |                          string.find(..., true)),
   |                          SaveResourceFile('out/shot-N.png')
   |                          out/<id>.json = {status:'ok', artifact:...}
   v
 polls out/<id>.json every        <-- shares this same file system
 500ms until status != 'pending'
   |
   v
 prints the absolute PNG path (last stdout line) -- Claude opens it with its image reader
```

`profile` and `logs` take a different upload path for the same reason
`screenshot` doesn't: **the resource itself cannot reach the client's own
filesystem**, and the profiler can only write to the client machine's own
disk (`citizen:/...`), not to a server resource file. So for those two,
`fxclient-agent.ps1` -- a small, independent, always-on process on the
Windows box -- is the thing that actually uploads the bytes:

```
 client/main.lua:                          fxclient-agent.ps1 (Windows, separate
   ExecuteCommand('profiler resource ...')  process, polls every -IntervalMs):
   Wait until ProfilerIsRecording()==false    - tails logs\CitizenFX_log_*.log,
   ExecuteCommand('profiler saveJSON            POSTs new bytes to
     devprofile-<id>.json')                     /upload/clientlog
                                               - watches citizen\devprofile-*.json,
   -> writes citizen\devprofile-<id>.json        POSTs each to
      (a file on the WINDOWS filesystem)          /upload/profile?id=<id>,
                                                    renames it *.uploaded on success
```

`info` and `clientexec`/`serverexec` need no upload at all -- `info`'s
payload is small enough to go back over a net event
(`fivem-devtools:server:info`), and `serverexec` never leaves the server.

## 3. Source facts (read and cited, as required)

**Profiler console commands and JSON format** --
`fivem/code/components/citizen-scripting-core/src/Profiler.cpp`:

- `profiler record start|<frames>|stop` (lines 495-527, `recordCmd`):
  records **every** resource. `arg == "stop"` stops it; `arg == "start"`
  records forever; otherwise `arg` is parsed as an integer frame count via
  `StartRecording(std::stoi(arg))` (no resource filter -- the 1-argument
  overload of `StartRecording`, whose `resource` parameter defaults to
  `""`).
- **There is a separate, resource-scoped command**, `profiler resource
  <resourceName> [frames]` / `profiler resource stop` (lines 529-574,
  `resourceStopCmd` for the 1-arg `"stop"` case and `resourceCmd` for the
  2-arg `(resource, frames)` case): `profiler->StartRecording(frames,
  resource)`. Argument order is **resource name first, frame count
  second** (`profiler resource my-resource 300`); omitting the frame count
  records indefinitely (`frames = -1`) until `profiler resource stop`.
  fivem-devtools always uses this form when a resource name is given
  (`profiler resource %s %d`), and falls back to `profiler record %d` only
  when none is given (`client/main.lua`, `fivem-devtools:client:profile`
  handler).
- Either form auto-stops itself once `frames` frames have ticked
  (`ProfilerComponent::BeginTick` decrements `m_frames` to 0 and calls
  `StopRecording()`, around line 796) -- `client/main.lua` also polls
  `ProfilerIsRecording()` as a bound (`frames/60*1000 + 1500` ms max),
  never as the primary stop mechanism.
- `profiler saveJSON <filename>` (lines 634-652, `saveJSONCmd`): converts
  the in-memory recording to Chrome-trace-event JSON
  (`ConvertToJSON(ConvertToStorage(profiler))`, `json.dump(..., -1, ' ',
  false, ...)` -- compact, no pretty-printing) and writes it via a VFS
  stream to `citizen:/<filename>` **on the client**
  (`#ifndef IS_FXSERVER outFn = "citizen:/" + outFn;`, line ~581) -- i.e.
  `%LOCALAPPDATA%\FiveM\FiveM.app\citizen\<filename>`. This does **not**
  require the recording to have stopped first (unlike `dump`/`view`, which
  explicitly refuse "Cannot dump/view: profiler is active" -- `saveJSON`
  has no such guard), but fivem-devtools always waits for it to stop
  anyway so the capture is complete.
- `ConvertToJSON` (lines 138-365) produces `{"traceEvents": [...]}`.
  Every event carries `cat`, `name`, `ph`, `ts` (microseconds), `pid`
  (always `TRACE_PROCESS_MAIN = 1`), `tid`. Three fixed `"M"` (metadata)
  events plus one `"TracingStartedInBrowser"` `"I"` event are emitted once;
  then, per recorded event: `BEGIN_TICK` -> `"BeginFrame"` (`ph:"I"`,
  `tid: TRACE_THREAD_MAIN = 1`, `Profiler.h:18`) marks a frame boundary;
  `END_TICK` -> `"ActivateLayerTree"` + `"DrawFrame"` + a `"Screenshot"`
  (`ph:"O"`) triplet; `ENTER_RESOURCE`/`EXIT_RESOURCE` and
  `ENTER_SCOPE`/`EXIT_SCOPE` become `ph:"B"`/`ph:"E"` spans on
  `tid: TRACE_THREAD_BROWSER = 2` (`Profiler.h:19`). An
  `ENTER_RESOURCE`/`EXIT_RESOURCE` pair's `name` is
  `"<cause> (<resourceName>)"` (`fmt::sprintf("%s (%s)", event.why,
  event.where)`, lines ~318-320 and ~344-346) -- **this is the only place
  a resource's identity appears**; plain `ENTER_SCOPE`/`EXIT_SCOPE` spans
  just carry the bare scope name. `lib/fxkit/client/trace.py`'s analyzer is
  built directly around this: it treats any `"X (Y)"`-shaped span name as a
  resource span (`resource = Y`), attributes every other span to whichever
  resource span most closely encloses it on the same `tid`'s stack, and
  computes "self time" the standard flame-graph way (a span's own duration
  minus its direct children's durations). `tests/fixtures/profile-sample.json`
  is a synthetic-but-format-faithful capture built from exactly this shape
  (2 resources, 50 frames, one deliberate 200us spike frame) -- see its
  generation logic mirrored in `tests/test_fxclient.py`'s
  `_expected_stats`/formulas for the exact numbers it's checked against.
  One deliberate simplification versus a real multi-runtime capture: the
  fixture only uses `tid` 1 and 2 (every real capture does too, **unless**
  the extended per-script "IScriptProfiler" bridge is also active --
  `Profiler.cpp` lines 872-904, `SetupScriptConnection` -- which assigns
  each profiled resource its *own* additional `tid` for source-line-level
  detail; fivem-devtools' analyzer only reads the always-present coarse
  layer, so it works either way, it just won't show that extra
  per-line detail).
- `PROFILER_IS_RECORDING` (native, `ext/native-decls/ProfilerIsRecording.md`,
  registered `Profiler.cpp:946-950`) returns whether a recording is active
  -- `apiset: shared`, usable client-side, verified with `fxref show
  ProfilerIsRecording`.

**Client script-error log** --
`fivem/code/client/launcher/Console.Logging.cpp`:

- File name pattern, line 106: `MakeRelativeCitPath(fmt::sprintf(L"logs/CitizenFX_log_%s.log", dateStamp))`
  where `dateStamp` is `YYYY-MM-DDTHHMMSS` (zero-padded, line 103) --
  i.e. `%LOCALAPPDATA%\FiveM\FiveM.app\logs\CitizenFX_log_2026-09-11T193000.log`.
  The filename is fixed for the whole game session (`initTickCount->initTime`
  is captured once at process start), so "a new newest file" only ever
  means a game restart -- exactly the signal `fxclient-agent.ps1` uses to
  reset its read offset.
- Line format, line 115: `fmt::fprintf(logFile, "[%10lld] [%14s] %20s/ %s\r\n",
  tickDelta, processName, threadName, message)`.
- Lines 195-230 (`InitLogging`): on launch, log files older than 7 days are
  deleted. Not something fxclient needs to handle, but it's why "the
  newest file" is always the right one to tail.

**Multipart / HTTP handler** -- `ext/native-decls/SetHttpHandler.md`:
`request` exposes `address`, `method`, `path`, `headers` (a
`Record<string,string>` -- casing isn't documented, so both `server/main.lua`'s
`getHeader` and the Python mirror in `lib/fxkit/client/multipart.py` do a
case-insensitive lookup), `setDataHandler(fn[, 'binary'])`,
`setCancelHandler(fn)`; `'binary'` "has no effect in Lua" (Lua strings are
already raw bytes). Verified against the actual HTTP server implementation
(`code/components/net-http-server/src/Http1Server.cpp`, ~lines 498-526 and
582-604): `setDataHandler`'s callback fires **exactly once**, with the
**entire** already-assembled request body (the server only invokes it once
`readQueue.size() >= contentLength`, for both fixed-length and
chunked-transfer bodies) -- so there is no streaming/chunk-accumulation
logic to write; `server/main.lua`'s upload handlers process the whole body
synchronously as soon as they're called.

`ExecuteCommand.md`'s own text says: *"you may need to use `add_acl
resource.<your_resource_name> command.<command_name> allow`"* -- almost
certainly a docs typo for `add_ace` (the directive used **everywhere else**
in FiveM, including every other line in this document and in
`$KIT/DESIGN.md`'s own `fxserver` contract). fivem-devtools' docs and setup
output use `add_ace` throughout.

**Other natives verified with `fxref show`/`fxref resolve`** (native, apiset,
hash): `SaveResourceFile` (server), `LoadResourceFile` (shared),
`GetPlayerIdentifierByType` (server), `IsPlayerAceAllowed` (server),
`GetResourceState`/`GetNumResources`/`GetResourceByFindIndex` (all shared),
`RegisterCommand` (shared), `GetCurrentServerEndpoint` (client, returns
`"ip:port"` or `NULL`), `GetPlayerEndpoint` (server, `"ip:port"`),
`GetGameBuildNumber` (shared), `GetFrameTime`/`GetEntityCoords`/
`GetEntityHeading`/`GetVehiclePedIsIn`/`GetEntityModel`/
`GetDisplayNameFromVehicleModel`/`GetEntityHealth`/`PlayerPedId`/
`GetGameTimer` (all client, or client+server with the client row used
here), `GetPlayerName`/`GetPlayerFromIndex`/`GetNumPlayerIndices`
(server), `GetCurrentResourceName`/`ExecuteCommand` (shared).
27 distinct natives are actually called in the shipped Lua; `fxlint
resources-dev/fivem-devtools` independently confirms all of them resolve
(0 C007/C008 findings) -- see §9.

**screenshot-basic** -- cloned to
`/home/liamrbsn/Dokumente/Entwicklung/FiveM/resources/screenshot-basic`
(`git clone --depth 1 https://github.com/citizenfx/screenshot-basic.git`).
Its `fxmanifest.lua` declares `dependency 'yarn'` and `dependency
'webpack'` and builds `dist/{client,server}.js` + `dist/ui.html` from
source on first `ensure`/start via those two system resources. **Verified
present**: `Server/alpine/opt/cfx-server/citizen/system_resources/{yarn,webpack}/`
both exist in this FXServer install, so screenshot-basic will build
correctly the first time it's started -- no extra setup needed beyond the
clone. API used here (from its `README.md`): client-side
`exports['screenshot-basic']:requestScreenshotUpload(url, field, {encoding,
quality}, cb)` POSTs `multipart/form-data` to `url` and calls `cb(result)`
with the raw HTTP response body once. (It also offers a simpler
*server*-driven `requestClientScreenshot(player, {fileName, ...}, cb)` that
uploads to a built-in server handler with no custom HTTP code needed at
all -- fivem-devtools doesn't use it because it can't also toggle `resmon`
on the client first, which the `screenshot --resmon` flag needs.)

## 4. Setup

Run `fxclient setup`. It **never** edits `server.cfg` or creates the
`[local]` symlinks itself -- it only reports what's missing and prints the
exact commands, so every change to the real dev server's configuration is
something Liam runs (and sees) himself:

```
$ fxclient setup
fivem-devtools setup

[ok]      screenshot-basic present: /home/liamrbsn/.../resources/screenshot-basic
[missing] fivem-devtools not deployed yet -- kit copy: /home/liamrbsn/.../fivem-dev-kit/resources-dev/fivem-devtools

This kit never creates the [local] symlinks or edits server.cfg for you --
run these yourself (fxserver is on hand to do the symlink + `ensure` line):
  fxserver deploy /home/liamrbsn/.../resources/screenshot-basic
  fxserver deploy /home/liamrbsn/.../fivem-dev-kit/resources-dev/fivem-devtools

Then add these two ACE lines to server.cfg by hand (fxserver deploy only
adds `ensure` lines, never ACE grants):
  ensure screenshot-basic
  ensure fivem-devtools
  add_ace resource.fivem-devtools command allow
  add_ace group.admin fivem-devtools.use allow

Detected LAN IP: 192.168.2.104   server port: 30120

On the gaming PC (PowerShell), fetch and run the agent:
  irm http://192.168.2.104:30120/fivem-devtools/agent -OutFile $env:TEMP\fxclient-agent.ps1
  powershell -ExecutionPolicy Bypass -File $env:TEMP\fxclient-agent.ps1 -Server 192.168.2.104:30120
```

Steps, in order:

1. `git clone --depth 1 https://github.com/citizenfx/screenshot-basic.git` into
   `$WS/resources/` (already done for this machine).
2. `fxserver deploy` both resource directories (symlinks them into
   `[local]` and adds their `ensure` lines to `server.cfg` automatically).
3. Add the two `add_ace` lines above to `server.cfg` by hand.
4. `refresh` then `ensure screenshot-basic` / `ensure fivem-devtools` on the
   server console (first start of screenshot-basic takes a few seconds --
   it's compiling its `dist/` via `yarn`/`webpack`).
5. On the gaming PC, run the two PowerShell lines `fxclient setup` printed
   (fetches and starts `fxclient-agent.ps1` with this machine's LAN IP
   filled in). Leave it running for the whole play session -- it's what
   uploads client logs and profiler captures.
6. `fxclient status` to confirm: resource deployed, screenshot-basic
   present, and (once the agent has sent its first upload) an "agent last
   seen" time.

LAN IP detection tries `ip route get 1.1.1.1` (a routing-table lookup --
sends no packets) then a UDP "connect" trick as a fallback; if neither
works, `fxclient setup` says so and prints `<LAN-IP>` as a placeholder to
fill in by hand.

## 5. Security model

**Upload endpoints** (`/upload/*`) accept requests from localhost, from any currently connected allowed
player's address, from IPs listed in `Config.AllowedUploadAddresses`, and (default on, `Config.AllowPrivateLanUploads`)
from any RFC1918/link-local address. The last rule exists because `fxclient-agent.ps1` on the gaming PC uploads
the client log before and between play sessions, when no player is connected; on a dev LAN that is the intended
trust boundary. Set `AllowPrivateLanUploads = false` and list the gaming PC's IP explicitly if you want it tighter.

**Dev server only. Never deploy this to anything a real player could
reach.** There is no "safe for production" mode.

- Every command -- queue-driven or the server-console `devtools ...` --
  only ever targets a **currently connected** player matching
  `Config.AllowedIdentifiers` (exact `"type:value"` strings, as
  `GetPlayerIdentifierByType` returns them) or holding
  `Config.AcePermission`. There is no "run on everyone" path.
- Every net event handler in `server/main.lua` captures `local src =
  source` as its first statement and checks `isAllowedPlayer(src)` before
  doing anything else, per `$KIT/DESIGN.md` §7.
- A per-player rate limit (`Config.MaxEventsPerSecond`, default 20/s) caps
  fivem-devtools' own net events, independent of and in addition to
  FXServer's built-in 50/s limit.
- Upload endpoints (`POST /upload/*`) only accept requests whose
  `request.address` matches a currently-connected allowed player's own
  `GetPlayerEndpoint` (port stripped), or `127.0.0.1`/`::1` -- everything
  else gets `403`. `GET /ping` and `GET /agent` are unauthenticated by
  design (there's nothing sensitive to leak: `/agent` just serves the
  public agent script).
- `serverexec` runs `ExecuteCommand` with whatever string the CLI is
  given, on the real server console. Treat `fxclient exec --server` like
  you'd treat server console access, because that's exactly what it is.
  ACE-restricted commands need `add_ace resource.fivem-devtools
  command.<name> allow` in `server.cfg` (see `ExecuteCommand.md`'s remark,
  §3 above, for the `add_acl`/`add_ace` naming nuance).
- `queue/commands.json` and `out/` are plain files on the dev box's
  filesystem, readable/writable by anything with shell access to it --
  there's no additional access control on *them*; the security boundary is
  entirely "who can reach the FXServer's HTTP port and who is a connected,
  allowed player", matching how the rest of a dev server already works.

## 6. Command reference

All commands read `config.json` the same way every other fxkit CLI does
(`FXKIT_CONFIG` env var, else `$KIT/config.json`). All waits poll `out/<id>.json`
every 500ms with a `--timeout`, and fail with a specific, actionable message
(never a bare "timed out") -- e.g. `no result for command 7 after 20s
(.../out/7.json never appeared) -- is the fivem-devtools resource deployed,
ensured, and is a dev player online? try fxclient status.`.

### `fxclient setup`

See §4.

### `fxclient screenshot [--resmon] [--jpg] [--timeout 20]`

Enqueues `screenshot`, waits for `out/<id>.json` to reach `status: "ok"`,
then prints the **absolute PNG (or JPG) path as the last line of stdout** --
Claude opens it directly with its image reader. `--resmon` has the client
run `resmon 1`, wait 1.5s (let the overlay settle), capture, then `resmon
0`. Errors go to stderr and exit 1 (e.g. `screenshot failed: no dev player
online (no connected player matches Config.AllowedIdentifiers)`).

```
$ fxclient screenshot --resmon
/home/liamrbsn/.../resources-dev/fivem-devtools/out/shot-14.png
```

### `fxclient profile <resource> [--frames 300] [--timeout 60] [--json]`

Enqueues `profile` (uses `profiler resource <resource> <frames>` client-side
-- §3), waits for the trace JSON to land at `out/profile-<id>.json`
(uploaded by `fxclient-agent.ps1`, **not** by this resource -- a timeout
here almost always means the agent isn't running), analyzes it with
`lib/fxkit/client/trace.py`, and prints a table plus a verdict for the
requested resource. `--json` prints the full analysis (`frame_count`,
`frame_period_ms`, per-resource `{frames,total_ms,avg_ms,p95_ms,max_ms,share_pct}`,
`top_scopes`) instead.

```
$ fxclient profile fivem-devtools --frames 300
frames captured: 300   avg frame period: 16.667 ms/frame (~60 fps)

resource                    frames  total ms   avg ms   p95 ms   max ms   share
------------------------------------------------------------------------------
fivem-devtools                  300     0.311   0.0010   0.0012   0.0015   0.01%  *
chat                             98     0.045   0.0005   0.0006   0.0007   0.00%

top scopes for fivem-devtools, by self time:
   1. queue:poll                      self   0.3110 ms  (300 calls)

verdict (fivem-devtools): OK -- 0.0010 ms/frame avg is within the idle target (0.00-0.02 ms)
```

(Numbers above are illustrative -- see `tests/fixtures/profile-sample.json`
for the actual fixture used by the tests.)

### `fxclient logs [--tail N=80] [--errors] [--resource NAME]`

Reads `out/client.log` (the tail buffer `fxclient-agent.ps1` keeps
uploaded, truncated server-side to `Config.MaxLogBytes`). `--errors` keeps
only lines containing `SCRIPT ERROR`, `error`, `warning`, `attempt to`,
`nil value`, `stack traceback`, `Failed`, or `Error loading`. `--resource
NAME` is a **best-effort substring match** (§8 -- the client log has no
`fxserver.log`-style `[script:name]` tag).

### `fxclient info [--json] [--timeout 15]`

Enqueues `info`; the client collects fps (`1/GetFrameTime()`), coords +
heading, the vehicle (if any: model + display name), ped health, resource
states (a given list, or up to `Config.MaxInfoResources` resources via
`GetNumResources`/`GetResourceByFindIndex`/`GetResourceState`), and
`GetGameBuildNumber()`, and reports it back over a net event (no upload
needed -- it's small). Text output groups resource states, listing
non-`started` ones by name (the interesting/anomalous ones) and just
counting `started` ones:

```
$ fxclient info
fps: 61   gameBuild: 3095
coords: 215.34, -810.22, 30.75   heading: 178.4
ped health: 200
vehicle: none
resources reported: 47 (of 47 total)
  started: 45
  stopped: chat, old-test-resource
```

### `fxclient exec (--client CMD | --server CMD) [--timeout 20]`

Runs one console command on the dev player's client, or on the server
console. Prints `<status>: <message>` and exits 0 on `ok`, 1 otherwise.

```
$ fxclient exec --server "ensure my-resource"
ok: executed
```

### `fxclient status [--json]`

Deployment state (resource + screenshot-basic), queue length/next id, the
last command and its result, and the agent's last-seen time (from
`out/agent-status.json`, updated on every clientlog upload).

```
$ fxclient status
fivem-devtools deployed: yes (/home/liamrbsn/.../resources/[local]/fivem-devtools)
screenshot-basic present: yes
queue: 3 command(s) kept, next id 15
last command: #14 screenshot
  status: ok  message: uploaded
agent last seen: 4s ago
```

## 7. How Claude should use this in a dev loop

- **After deploying/restarting a resource**: `fxclient screenshot` to see
  what the developer sees, and `fxclient logs --errors --resource <name>
  --tail 50` to catch anything that broke on load.
- **While the developer exercises a feature**: `fxclient profile <name>
  --frames 300` (roughly 5 seconds of gameplay at 60fps) captures exactly
  that window; ask the developer to do the thing, then run it. Compare
  the verdict against the resmon targets (idle 0.00-0.02ms, active
  <0.10ms avg) from `$KIT/DESIGN.md` §7.
- **After any test the developer reports as "done" or "broken"**:
  `fxclient logs --errors` first -- script errors are the fastest signal,
  cheaper than asking the developer to describe what they saw.
- **To sanity-check state** (is the player where you expect, in the right
  vehicle, is a resource actually started): `fxclient info --json`.
- **To iterate without asking the developer to type anything**:
  `fxclient exec --client "..."` / `--server "..."` for one-off console
  commands (e.g. `--server "restart my-resource"`).
- Always `fxclient status` first in a new session, or after a while of
  silence -- it's the cheapest way to notice "the agent isn't running" or
  "the resource isn't deployed" before spending a `--timeout` waiting on a
  command that can never complete.

## 8. Limitations

- **resmon-quality numbers only come from the profiler or a `resmon 1`
  screenshot**, never from `fxclient info` -- there's no native that
  returns a resource's per-frame ms directly; `profiler resource <name>`
  (§3, §6) is the real measurement.
- **Restricted `ExecuteCommand`s need an ACE grant** (§5) -- if
  `serverexec`/`clientexec` reports success but nothing happened, check
  for `add_ace resource.fivem-devtools command.<name> allow` in
  `server.cfg`.
- **Profiles are uploaded by `fxclient-agent.ps1`, not this resource** --
  this resource can only *start* the recording (`ExecuteCommand`) and
  *watch* whether it started (`ProfilerIsRecording()`, logged back over
  `fivem-devtools:server:log` if it didn't); the agent has to be running
  on the gaming PC or `fxclient profile` will always time out.
- **`fxclient logs --resource NAME` is a heuristic**, not a guaranteed
  filter -- the client log has no structured per-resource tag the way
  `fxserver.log` does; it's a plain substring match.
- **`queue/commands.json` has exactly one intended writer at a time**
  (the CLI, or the server console's `devtools ...` command, which appends
  to the very same file) -- both use a plain read-modify-write, no file
  locking. For a single-developer local dev tool the odds of a genuine
  collision are effectively nil; it's called out here rather than solved
  because solving it would add real complexity for a risk that doesn't
  really exist in this tool's actual usage pattern.
- **The queue file is pruned to the last 200 commands** on every enqueue
  (`lib/fxkit/client/queue.py`'s `MAX_KEPT_COMMANDS`) so the server's every
  -250ms `LoadResourceFile` read never has to parse an ever-growing file --
  this wasn't in the original spec text, but was necessary to actually
  honor its own "keep the poll cheap" requirement over a long dev session.
- **Screenshots and client execs can silently never complete** if
  `screenshot-basic`'s upload callback is never invoked (e.g. the client
  can't reach the server at all) -- the client-side thread just waits
  forever; it isn't a per-frame loop and costs nothing while idle, but it
  means "the callback never fires" and "it's still in flight" look
  identical from the CLI's side until `--timeout` gives up.

## 9. Troubleshooting

> **Verified 2026-09-11 on Liam's setup:** `ExecuteCommand('profiler ...')` issued by the devtools resource IS
> blocked by the client's production mode — the client log shows `Command profiler is disabled in production
> mode. See https://aka.cfx.re/prod-console`. `fxclient profile` (and `--resmon`) therefore require the FiveM
> client to be started with `+set moo 31337` (add it to the FiveM shortcut target on the gaming PC).
> Screenshots, `info`, `logs` and `exec --server` work without it.

**`fxclient <cmd>` times out with "no result ... never appeared"**: run
`fxclient status` -- is the resource deployed? Is a dev player actually
online with an identifier in `Config.AllowedIdentifiers`?

**`profile` specifically times out but `screenshot`/`info` work fine**:
`fxclient-agent.ps1` probably isn't running on the gaming PC (check its
`[HH:MM:SS] status: ...` heartbeat line, printed every ~30s) -- see the
`irm .../agent` + `powershell -File ...` lines from `fxclient setup`.

**The client log shows "Command profiler is disabled in production mode"
or "Access denied for command ..."**: the client's *production-build*
console command whitelist is blocking `profiler`/`resmon`/`netgraph`/etc.
Verified in source: `IsNonProduction()`
(`code/components/conhost-v2/src/ConsoleHostGui.cpp:1024-1040`) gates on a
`moo` convar (`moo.GetValue() == 31337`) unless the client's update channel
isn't `"production"`; `ProductionWhitelist.h`'s command list is granted to
principal `system.extConsole` only when `IsNonProduction()` (line
1195-1216); a command failing that overall privilege check prints either
the specific *"is disabled in production mode"* message (when NOT
non-production -- `ConsoleHostGui.cpp:1206`) or the generic *"Access denied
for command %s."* (`code/client/citicore/console/Console.Commands.cpp:118`,
whenever `AccessDeniedEvent` isn't suppressed). **Fix**: add `+set moo
31337` to the FiveM shortcut target on the gaming PC. `fxclient
info`/`status`/`profile` all proactively scan the uploaded client log for
both messages and print a warning with this exact fix if either shows up
-- see `lib/fxkit/client/logs.py`'s `find_production_gate_warning`. Note
that `EXECUTE_COMMAND`'s native handler
(`citizen-scripting-core/src/ResourceScriptFunctions.cpp:103-120`) runs
under principal `resource.<name>` (here, `resource.fivem-devtools`), a
*different* principal than the F8 console's `system.extConsole` -- so this
gate is verified to exist and to matter for **interactive** console input,
but whether it also applies to fivem-devtools' own `ExecuteCommand(...)`
calls specifically was not verified against a running game (see "what
could not be verified" in the implementation notes); if `profiler`/`resmon`
commands issued by this resource are silently no-ops in testing, `+set moo
31337` is the fix to try first regardless.

**`screenshot` reports "upload did not confirm"**: check
`fxclient logs --tail 20` for a script error around screenshot-basic, and
confirm `ensure screenshot-basic` actually finished building (`dist/` --
first start only, needs `yarn`/`webpack`).

**Never share `server.cfg`'s contents.** It holds `sv_licenseKey`. Nothing
in fxclient ever reads or prints it.
