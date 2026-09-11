# fxserver

Local dev-server helper: deploy/undeploy resources by symlink, check status,
read the log, and send rcon commands. All paths come from `config.json`'s
`server` section (`lib/fxkit/config.py::server_paths()`); override the whole
config with `FXKIT_CONFIG=<path>` (this is how the test suite points at a
throwaway fake server tree instead of the real one).

`server.cfg` holds the license key -- fxserver **never** prints its
contents. `deploy` only ever reports the specific `ensure <name>` line it
added, nothing else in the file.

## Usage

```
fxserver status [--json]
fxserver deploy <resource_dir> [--no-ensure]
fxserver undeploy <name>
fxserver list [--json]
fxserver logs [--tail N] [--errors] [--resource NAME] [--since MIN] [--follow] [--json]
fxserver rcon <command...> [--password PASS]
fxserver restart <resource> [--password PASS]
```

### status

Reports whether an `FXServer` process is running (`pgrep -f FXServer`,
falling back to scanning `ps -eo pid,args` if `pgrep` isn't available), the
TCP port from server.cfg's `endpoint_add_tcp`/`endpoint_add_udp` line and
whether it's actually reachable on `127.0.0.1`, and whether txAdmin appears
to be present (the log contains a `script:monitor` line -- txAdmin runs as
the `monitor` resource).

### deploy

```
fxserver deploy <resource_dir> [--no-ensure]
```

1. Refuses (exit 1) if `<resource_dir>` has no `fxmanifest.lua`/`__resource.lua`
   -- never deploys a non-resource directory.
2. Symlinks `<local_resources>/<name>` (name = the resource directory's own
   basename) to the **absolute** resource path. If that name already exists:
   - as a symlink pointing somewhere else, it's replaced (re-linked);
   - as a symlink already pointing at the right place, nothing happens;
   - as a **real directory or file**, deploy refuses and exits 1 -- it will
     never delete something that isn't a symlink it manages.
3. Unless `--no-ensure`, inserts `ensure <name>` into `server.cfg`
   immediately after the last existing `ensure`/`start` line (any resource),
   or at the end of the file if there are none, *unless* a line for this
   exact name (`ensure <name>` or `start <name>`) is already present. The
   write is atomic (written to a `.fxkit.tmp` file, then `os.replace`d over
   `server.cfg`). The very first time `deploy` ever modifies a given
   `server.cfg`, it's copied to `server.cfg.fxkit.bak` first -- that backup
   is never overwritten again by later deploys.
4. Prints a short summary of what happened (linked/re-linked/already-linked,
   ensure-added/already-present) -- never the file contents.

### undeploy

```
fxserver undeploy <name>
```

Removes `<local_resources>/<name>` if (and only if) it's a symlink; refuses
to touch a real directory. Does **not** remove the `ensure`/`start` line
from server.cfg -- that's left for you to remove by hand (auto-removing it
risks silently orphaning an intentionally-kept entry, e.g. one you added
yourself outside fxserver).

### list

Lists everything currently in `<local_resources>`: symlinks (with their
target, and whether the target is currently broken/missing) and any real
directories found there too (flagged as such, since a stray real directory
in `[local]` is usually worth noticing).

### logs

```
fxserver logs [--tail N=80] [--errors] [--all-errors] [--resource NAME] [--since MIN]
              [--follow] [--dedupe|--no-dedupe] [--json]
```

Reads `server.log_file`. ANSI escape codes are always stripped and txAdmin's
box-drawing banner lines (containing `║`/`╔`/`╗`/`╚`/`╝`/`═`/`╠`/`╣`) are
always dropped, before any other filter runs.

- `--errors`: keep only lines that look like a real script/resource problem,
  in priority order: `SCRIPT ERROR`, `[script:`, `stack traceback`,
  `attempt to`, `nil value`, `not safe for net`, `Couldn't find resource`,
  `Failed to`, then the generic `error`/`warning` as a catch-all. **Before**
  that keyword match, Cfx's periodic server-list heartbeat noise is dropped
  by default -- lines matching `Server list query returned an error` or
  `server request failed for endpoint https://.../{info,dynamic,players}.json`.
  On the real dev server this heartbeat repeats every few seconds
  and would otherwise dominate `--errors` output (it's a "can't reach Cfx's
  master server list" connectivity message, not a script/resource problem).
- `--all-errors`: with `--errors`, put that heartbeat noise back instead of
  excluding it (still gated by the same keyword list -- it matches via the
  generic `error` keyword).
- `--resource NAME`: keep only lines matching `[script:NAME]` (allowing for
  the log's column-padding, e.g. `[      script:myresource]`) or the word
  sequence `resource NAME` (e.g. `Started resource myresource`).
- `--since MIN`: keep only lines timestamped within the last MIN minutes.
  **Needs per-line timestamps.** The real server log observed in this
  environment (`txData/default/logs/fxserver.log`) has *no* per-line
  timestamps at all (only inside the txAdmin startup banner, which is
  dropped anyway) -- when no timestamped lines are found in a sample of the
  log, `--since` is silently ignored except for a one-line note
  (`logs: --since ignored (this log has no per-line timestamps)`) printed to
  stderr in text mode / into `"notes"` in `--json` mode.
- `--dedupe`/`--no-dedupe` (default: **on**): collapse runs of identical
  consecutive lines (after every other filter, before `--tail`) into one
  line with a `(xN)` suffix -- e.g. three identical heartbeat lines in a row
  become one line ending `... (x3)`. Pass `--no-dedupe` to see every raw
  line individually.
- `--tail N` (default 80): keep only the last N lines. Applied **last**,
  after every other filter including dedupe.
- `--follow`: after printing the initial (filtered) output, polls the log
  file every 0.5s for newly-appended lines (tolerating log rotation/
  truncation by rewinding to the start if the file got smaller), applying
  the same `--errors`/`--all-errors`/`--resource`/`--dedupe` handling to each
  new batch, until Ctrl-C. Dedupe only collapses runs within one 0.5s batch,
  not across batches. `--tail` is ignored while following (there's nothing
  to tail against yet).

### rcon

```
fxserver rcon <command...> [--password PASS]
fxserver restart <resource> [--password PASS]   # == rcon "restart <resource>"
```

Password resolution: `--password`, else the environment variable named by
`config.json`'s `server.rcon.password_env` (default `FXRCON_PASSWORD`). If
neither is set, fxserver refuses with an explanation instead of sending an
empty/garbage password -- it does **not** write `rcon_password` into
server.cfg for you; add a strong `rcon_password "..."` line yourself.

#### Wire format (verified against the FiveM server source)

FXServer's rcon is the classic Quake-style out-of-band UDP protocol: a
4-byte `0xFFFFFFFF` prefix marks a packet as out-of-band (checked as a
`== -1` 32-bit int read), followed by a **key** (up to the first space or
newline) that selects a handler, then that handler's own data.

- **Request**: `\xFF\xFF\xFF\xFF` + `"rcon "` + `<password>` + `" "` + `<command>`,
  sent as a single UDP datagram to the configured host:port.
  - The `rcon` key dispatch and the 4-byte-prefix / out-of-band framing:
    `fivem/code/components/citizen-server-impl/include/decorators/WithOutOfBand.h`
    (the `receivedDataLength >= 4 && *reinterpret_cast<const int*>(receivedData) == -1`
    check, and the key/data split at the first space/newline after those 4 bytes).
  - The password/command split (`dataView.find_first_of(" \n")`, password =
    everything before that, command = everything from that space onward,
    i.e. *including* the leading space) and password checks ("must set
    rcon_password" / "Invalid password." responses):
    `fivem/code/components/citizen-server-impl/include/outofbandhandlers/RconOutOfBand.h`
    lines 30-49.
- **Response**: `\xFF\xFF\xFF\xFF` + `"print "` + `<console output>`.
  - The `"print " + printString` response construction:
    `RconOutOfBand.h` line 67.
  - The `\xFF\xFF\xFF\xFF` response prefix itself (`prefix ? "\xFF\xFF\xFF\xFF" : ""`):
    `fivem/code/components/citizen-server-impl/src/GameServerNet.ENet.cpp` line 512.
  - `rcon_password` is a plain `ConVar_ReadOnly` string convar, set via
    server.cfg (or the live console) like any other: `GameServer.cpp` line 116.

This is fully verified against source (not a guess) -- `fxserver rcon` sends
exactly `\xFF\xFF\xFF\xFF` + `f"rcon {password} {command}"`, and strips the
`\xFF\xFF\xFF\xFF` prefix and a leading `"print "` (or bare `"print"` +
newline) from the response before printing it. `docs/fxlint.md`/DESIGN.md's
note about a possible `\xFF\xFF\xFF\xFFprint\n...` response shape turned out
to be close but not exact -- it's `"print "` (a space, not a newline)
immediately followed by the console output.

Notes:

- rcon is rate-limited server-side (`fx::RateLimiterDefaults{0.2, 5.0}` in
  `RconOutOfBand.h` -- roughly one sustained request per 5s, with a burst
  allowance of 5) -- don't script rapid-fire rcon calls.
- `fxserver rcon`/`restart` use a 3-second UDP receive timeout and report a
  clear error (not a hang) if nothing responds.
- `tests/test_fxserver.py` only exercises the packet builder/parser
  (`build_rcon_packet`/`parse_rcon_response` in `lib/fxkit/server.py`) --
  no real network traffic, and it is never pointed at the real dev server.

## Testing safely

Every test in `tests/test_fxserver.py` builds its own throwaway fake server
tree (`server.cfg`, a `resources/[local]/` directory, a fake log file) under
a temp directory and points `FXKIT_CONFIG` at a generated config.json for
it -- the real server at `$WS/Server/` is never read or written by the test
suite. `status`/`rcon` do touch real, global OS state by nature (`pgrep`
scans *all* processes; rcon opens a UDP socket) -- those checks are written
to tolerate a real FXServer happening to be running on the machine (they
assert types/shapes, not specific values) and to never target a real rcon
port with a guessed password.
