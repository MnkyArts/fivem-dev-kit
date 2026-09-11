Config = {}

-- Player identifiers allowed to use fivem-devtools, in the exact
-- "type:value" form GetPlayerIdentifierByType returns (fxref: GET_PLAYER_IDENTIFIER_BY_TYPE).
-- 'fivem:414243' is Liam's Cfx.re account identifier.
Config.AllowedIdentifiers = {
    'fivem:414243',
}

-- ACE object players can alternatively be granted to use fivem-devtools,
-- e.g. `add_ace group.admin fivem-devtools.use allow` in server.cfg
-- (checked with IsPlayerAceAllowed -- fxref: IS_PLAYER_ACE_ALLOWED).
Config.AcePermission = 'fivem-devtools.use'

-- How often the server thread checks queue/commands.json for new work (ms).
-- One LoadResourceFile read of a small JSON file per tick of this loop --
-- see docs/fxclient.md for the cost discussion.
Config.PollIntervalMs = 250

-- out/client.log is truncated to this many bytes (oldest data dropped first)
-- every time new client-log text is appended.
Config.MaxLogBytes = 512 * 1024

-- Hard cap on how many resources an `info` command reports GetResourceState
-- for, so a server with an unusually large resource count can't make a
-- single info command expensive.
Config.MaxInfoResources = 200

-- Per-player rate limit for fivem-devtools' own net events (devlog, done,
-- info), independent of and in addition to FXServer's own event/s limits
-- (see $KIT/DESIGN.md §7).
Config.MaxEventsPerSecond = 20

-- Upload endpoints (/upload/*) accept requests from: localhost, any currently
-- connected allowed player's address, any address listed here (exact IPs),
-- and -- when AllowPrivateLanUploads is true -- any RFC1918 / link-local
-- address (10.x, 172.16-31.x, 192.168.x, 169.254.x). The gaming PC runs the
-- client-log/profile uploader (fxclient-agent.ps1) before and between play
-- sessions, so it must be trusted even while no player is connected.
-- Dev server only: never expose this resource to a public server.
Config.AllowPrivateLanUploads = true
Config.AllowedUploadAddresses = {}
