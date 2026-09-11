-- fivem-devtools :: server
--
-- Protocol and architecture: $KIT/docs/fxclient.md. Summary: bin/fxclient
-- (running on this same Linux box) appends commands to queue/commands.json;
-- this resource polls that file on a single Wait()-driven thread, dispatches
-- work to the allowed dev player over TriggerClientEvent, and receives
-- results either via a net event (info/devlog/clientexec/error-reporting)
-- or via our own HTTP handler (screenshot + profiler JSON uploads, both
-- delivered by the client side -- the game client itself for screenshots,
-- fxclient-agent.ps1 for profiler JSON). Every result -- ok or error -- ends
-- up in out/<id>.json for bin/fxclient to read back.

local resourceName = GetCurrentResourceName()

-- ---------------------------------------------------------------------
-- resource-file JSON helpers
-- ---------------------------------------------------------------------

local function readJsonFile(fileName)
    local text = LoadResourceFile(resourceName, fileName)
    if not text or text == '' then
        return nil
    end
    local ok, data = pcall(json.decode, text)
    if not ok then
        return nil
    end
    return data
end

local function writeJsonFile(fileName, data)
    local ok, text = pcall(json.encode, data)
    if not ok then
        return false
    end
    return SaveResourceFile(resourceName, fileName, text, #text)
end

-- ---------------------------------------------------------------------
-- state: lastId (highest processed queue command id), persisted so a
-- resource restart never replays already-handled commands.
-- ---------------------------------------------------------------------

local lastId = 0
do
    local state = readJsonFile('out/state.json')
    if type(state) == 'table' and type(state.lastId) == 'number' then
        lastId = state.lastId
    end
end

local function saveState()
    writeJsonFile('out/state.json', { lastId = lastId })
end

-- ---------------------------------------------------------------------
-- pure helpers -- no natives, no globals besides stdlib. Exercised by the
-- plain-Lua unit test harness at tests/fixtures/lua_multipart_test.lua via
-- the FXKIT_TEST export hook at the bottom of this file.
-- ---------------------------------------------------------------------

-- identifier must be the exact "type:value" string GetPlayerIdentifierByType
-- returns (fxref: GET_PLAYER_IDENTIFIER_BY_TYPE) -- same shape as the
-- entries in Config.AllowedIdentifiers.
local function identifierAllowed(identifier)
    if type(identifier) ~= 'string' then
        return false
    end
    for _, allowed in ipairs(Config.AllowedIdentifiers) do
        if identifier == allowed then
            return true
        end
    end
    return false
end

-- Returns the subset of `commands` with id > sinceId, sorted ascending.
local function selectCommandsToRun(commands, sinceId)
    local out = {}
    for _, cmd in ipairs(commands or {}) do
        if type(cmd) == 'table' and type(cmd.id) == 'number' and cmd.id > sinceId then
            out[#out + 1] = cmd
        end
    end
    table.sort(out, function(a, b) return a.id < b.id end)
    return out
end

-- Case-insensitive lookup in an HTTP headers table (SetHttpHandler doesn't
-- document header-name casing, so don't assume one).
local function getHeader(headers, name)
    if type(headers) ~= 'table' or type(name) ~= 'string' then
        return nil
    end
    local lowerName = string.lower(name)
    for k, v in pairs(headers) do
        if type(k) == 'string' and string.lower(k) == lowerName then
            return v
        end
    end
    return nil
end

-- 'multipart/form-data; boundary=----xyz' or with a quoted boundary.
local function parseBoundary(contentType)
    if type(contentType) ~= 'string' then
        return nil
    end
    return string.match(contentType, 'boundary="([^"]+)"') or string.match(contentType, 'boundary=([^;%s]+)')
end

-- Extracts the first file part's bytes from a multipart/form-data body.
-- `boundary` must NOT include the leading '--'. Lua strings are raw byte
-- arrays, so this is binary-safe as long as every search uses `plain` (4th
-- arg `true`) string.find -- never a pattern that could match boundary
-- bytes as magic characters (see $KIT/DESIGN.md "quality bar").
--
-- Returns (data: string, info: {filename, contentType}) on success, or
-- (nil, errorMessage: string) on failure.
local function parseMultipart(body, boundary)
    if type(body) ~= 'string' or type(boundary) ~= 'string' or boundary == '' then
        return nil, 'invalid arguments'
    end

    local delim = '--' .. boundary
    local _, delimEnd = string.find(body, delim, 1, true)
    if not delimEnd then
        return nil, 'boundary not found'
    end

    local headerStart = delimEnd + 1
    if string.sub(body, headerStart, headerStart + 1) == '\r\n' then
        headerStart = headerStart + 2
    end

    local headerEnd = string.find(body, '\r\n\r\n', headerStart, true)
    if not headerEnd then
        return nil, 'part headers not terminated'
    end

    local headers = string.sub(body, headerStart, headerEnd - 1)
    local dataStart = headerEnd + 4

    local nextBoundaryStart = string.find(body, '\r\n--' .. boundary, dataStart, true)
    if not nextBoundaryStart then
        return nil, 'closing boundary not found'
    end

    local data = string.sub(body, dataStart, nextBoundaryStart - 1)
    return data, {
        filename = string.match(headers, 'filename="([^"]*)"'),
        contentType = string.match(headers, '[Cc]ontent%-[Tt]ype:%s*([^\r\n]+)'),
    }
end

-- File extension to save an uploaded screenshot under.
local function guessExt(filename, contentType)
    if type(filename) == 'string' then
        local ext = string.match(filename, '%.([%a][%a%d]*)$')
        if ext then
            return string.lower(ext)
        end
    end
    if contentType == 'image/jpeg' then
        return 'jpg'
    end
    return 'png'
end

-- ---------------------------------------------------------------------
-- players / auth
-- ---------------------------------------------------------------------

-- GetPlayers() is a Lua-runtime convenience, not a native -- iterate with
-- the verified GetNumPlayerIndices/GetPlayerFromIndex pair instead so every
-- call here is fxref-checked.
local function forEachPlayer(fn)
    local n = GetNumPlayerIndices()
    for i = 0, n - 1 do
        local playerId = tonumber(GetPlayerFromIndex(i))
        if playerId then
            fn(playerId)
        end
    end
end

local function isAllowedPlayer(src)
    if Config.AcePermission and IsPlayerAceAllowed(src, Config.AcePermission) then
        return true
    end
    for _, allowed in ipairs(Config.AllowedIdentifiers) do
        local idType = string.match(allowed, '^([^:]+):')
        if idType and identifierAllowed(GetPlayerIdentifierByType(src, idType)) then
            return true
        end
    end
    return false
end

-- The first connected, allowed player -- the "dev player" every dispatched
-- command targets.
local function findDevTarget()
    local found = nil
    forEachPlayer(function(playerId)
        if not found and isAllowedPlayer(playerId) then
            found = playerId
        end
    end)
    return found
end

-- 'a.b.c.d:port' or bare 'a.b.c.d' -> 'a.b.c.d'.
local function addressOf(endpoint)
    if type(endpoint) ~= 'string' then
        return nil
    end
    return string.match(endpoint, '^(.+):%d+$') or endpoint
end

-- Only an allowed, currently-connected player's own address (or localhost,
-- for `devtools` console / same-box curl testing) may POST to our upload
-- endpoints.
-- 'a.b.c.d:port', '[::ffff:a.b.c.d]:port', '::ffff:a.b.c.d' -> 'a.b.c.d'
local function normalizeAddress(address)
    local addr = addressOf(address)
    if type(addr) ~= 'string' then
        return nil
    end
    addr = string.match(addr, '^%[(.+)%]$') or addr
    addr = string.match(addr, '^::ffff:(%d+%.%d+%.%d+%.%d+)$') or addr
    return addr
end

local function isPrivateAddress(addr)
    local a, b = string.match(addr, '^(%d+)%.(%d+)%.%d+%.%d+$')
    a, b = tonumber(a), tonumber(b)
    if not a or not b then
        return false
    end
    return a == 10
        or (a == 172 and b >= 16 and b <= 31)
        or (a == 192 and b == 168)
        or (a == 169 and b == 254)
end

local function isAllowedAddress(address)
    local addr = normalizeAddress(address)
    if not addr then
        return false
    end
    if addr == '127.0.0.1' or addr == '::1' then
        return true
    end
    for _, allowed in ipairs(Config.AllowedUploadAddresses or {}) do
        if allowed == addr then
            return true
        end
    end
    if Config.AllowPrivateLanUploads and isPrivateAddress(addr) then
        return true
    end
    local allowed = false
    forEachPlayer(function(playerId)
        if not allowed and isAllowedPlayer(playerId) and normalizeAddress(GetPlayerEndpoint(playerId)) == addr then
            allowed = true
        end
    end)
    return allowed
end

-- Per-player rate limit for fivem-devtools' own net events (independent of
-- FXServer's own 50/s event limit -- see $KIT/DESIGN.md §7).
local eventCounts = {}

local function rateLimited(src)
    local now = GetGameTimer()
    local entry = eventCounts[src]
    if not entry or (now - entry.windowStart) >= 1000 then
        eventCounts[src] = { windowStart = now, count = 1 }
        return false
    end
    entry.count = entry.count + 1
    return entry.count > Config.MaxEventsPerSecond
end

-- ---------------------------------------------------------------------
-- command results (out/<id>.json)
-- ---------------------------------------------------------------------

local function resultFileName(id)
    return ('out/%d.json'):format(id)
end

local function writeCommandResult(id, cmd, status, message, extra)
    local result = { id = id, cmd = cmd, status = status, message = message }
    if type(extra) == 'table' then
        for k, v in pairs(extra) do
            result[k] = v
        end
    end
    writeJsonFile(resultFileName(id), result)
end

-- ---------------------------------------------------------------------
-- HTTP handler
-- ---------------------------------------------------------------------

local function respondPlain(response, code, text)
    response.writeHead(code, { ['Content-Type'] = 'text/plain; charset=utf-8' })
    response.send(text)
end

local function respondJson(response, code, data)
    local ok, text = pcall(json.encode, data)
    response.writeHead(code, { ['Content-Type'] = 'application/json' })
    response.send(ok and text or '{}')
end

local function handleScreenshotUpload(id, request, response, body)
    if not id then
        respondPlain(response, 400, 'missing or invalid id')
        return
    end
    local boundary = parseBoundary(getHeader(request.headers, 'content-type'))
    if not boundary then
        writeCommandResult(id, 'screenshot', 'error', 'upload had no multipart boundary in Content-Type')
        respondPlain(response, 400, 'missing multipart boundary')
        return
    end
    local data, info = parseMultipart(body, boundary)
    if not data then
        writeCommandResult(id, 'screenshot', 'error', 'multipart parse failed: ' .. tostring(info))
        respondPlain(response, 400, 'bad multipart body')
        return
    end
    local artifact = ('out/shot-%d.%s'):format(id, guessExt(info.filename, info.contentType))
    if not SaveResourceFile(resourceName, artifact, data, #data) then
        writeCommandResult(id, 'screenshot', 'error', 'SaveResourceFile failed for ' .. artifact)
        respondPlain(response, 500, 'save failed')
        return
    end
    writeCommandResult(id, 'screenshot', 'ok', 'uploaded', { artifact = artifact })
    respondPlain(response, 200, 'ok')
end

local function handleProfileUpload(id, response, body)
    if not id then
        respondPlain(response, 400, 'missing or invalid id')
        return
    end
    if type(body) ~= 'string' or body == '' then
        writeCommandResult(id, 'profile', 'error', 'empty upload body')
        respondPlain(response, 400, 'empty body')
        return
    end
    local artifact = ('out/profile-%d.json'):format(id)
    if not SaveResourceFile(resourceName, artifact, body, #body) then
        writeCommandResult(id, 'profile', 'error', 'SaveResourceFile failed for ' .. artifact)
        respondPlain(response, 500, 'save failed')
        return
    end
    writeCommandResult(id, 'profile', 'ok', 'uploaded', { artifact = artifact })
    respondPlain(response, 200, 'ok')
end

local function handleClientLogUpload(response, body)
    if type(body) == 'string' and body ~= '' then
        local tail = readJsonFile('out/client-log-tail.json')
        local text = (type(tail) == 'table' and type(tail.text) == 'string') and tail.text or ''
        text = text .. body
        if #text > Config.MaxLogBytes then
            text = string.sub(text, #text - Config.MaxLogBytes + 1)
        end
        writeJsonFile('out/client-log-tail.json', { text = text })
        SaveResourceFile(resourceName, 'out/client.log', text, #text)
        writeJsonFile('out/agent-status.json', { lastSeen = os.time(), bytesReceived = #body })
    end
    respondPlain(response, 200, 'ok')
end

local function httpRouter(request, response)
    local path = request.path or ''
    local basePath, query = string.match(path, '^([^?]*)%??(.*)$')
    basePath = basePath or path
    query = query or ''

    if request.method == 'GET' and basePath == '/ping' then
        respondJson(response, 200, { ok = true, resource = resourceName })
        return
    end

    if request.method == 'GET' and basePath == '/agent' then
        local script = LoadResourceFile(resourceName, 'agent/fxclient-agent.ps1')
        if not script then
            respondPlain(response, 404, 'agent script missing from this resource')
            return
        end
        respondPlain(response, 200, script)
        return
    end

    if not isAllowedAddress(request.address) then
        respondPlain(response, 403, 'forbidden')
        return
    end

    if request.method == 'POST' and basePath == '/upload/screenshot' then
        local id = tonumber(string.match(query, 'id=(%d+)'))
        request.setDataHandler(function(body)
            handleScreenshotUpload(id, request, response, body)
        end, 'binary')
        return
    end

    if request.method == 'POST' and basePath == '/upload/profile' then
        local id = tonumber(string.match(query, 'id=(%d+)'))
        request.setDataHandler(function(body)
            handleProfileUpload(id, response, body)
        end, 'binary')
        return
    end

    if request.method == 'POST' and basePath == '/upload/clientlog' then
        request.setDataHandler(function(body)
            handleClientLogUpload(response, body)
        end, 'binary')
        return
    end

    respondPlain(response, 404, 'not found')
end

-- ---------------------------------------------------------------------
-- command execution (dispatched from the queue poll loop, see bottom)
-- ---------------------------------------------------------------------

local function runScreenshot(cmd)
    local args = cmd.args or {}
    local target = findDevTarget()
    if not target then
        writeCommandResult(cmd.id, 'screenshot', 'error', 'no dev player online (no connected player matches Config.AllowedIdentifiers)')
        return
    end
    writeCommandResult(cmd.id, 'screenshot', 'pending', 'dispatched to client')
    TriggerClientEvent('fivem-devtools:client:screenshot', target, cmd.id, {
        resmon = args.resmon == true,
        encoding = (args.encoding == 'jpg') and 'jpg' or 'png',
    })
end

local function runProfile(cmd)
    local args = cmd.args or {}
    local target = findDevTarget()
    if not target then
        writeCommandResult(cmd.id, 'profile', 'error', 'no dev player online (no connected player matches Config.AllowedIdentifiers)')
        return
    end
    local frames = math.floor(tonumber(args.frames) or 300)
    if frames < 1 then
        frames = 300
    end
    writeCommandResult(cmd.id, 'profile', 'pending', 'dispatched to client -- the JSON is uploaded by fxclient-agent.ps1, not this resource; make sure it is running')
    TriggerClientEvent('fivem-devtools:client:profile', target, cmd.id, {
        resource = (type(args.resource) == 'string' and args.resource ~= '') and args.resource or nil,
        frames = frames,
    })
end

local function runInfo(cmd)
    local args = cmd.args or {}
    local target = findDevTarget()
    if not target then
        writeCommandResult(cmd.id, 'info', 'error', 'no dev player online (no connected player matches Config.AllowedIdentifiers)')
        return
    end
    writeCommandResult(cmd.id, 'info', 'pending', 'dispatched to client')
    TriggerClientEvent('fivem-devtools:client:info', target, cmd.id, {
        resources = type(args.resources) == 'table' and args.resources or nil,
    })
end

local function runClientExec(cmd)
    local args = cmd.args or {}
    if type(args.command) ~= 'string' or args.command == '' then
        writeCommandResult(cmd.id, 'clientexec', 'error', 'missing args.command')
        return
    end
    local target = findDevTarget()
    if not target then
        writeCommandResult(cmd.id, 'clientexec', 'error', 'no dev player online (no connected player matches Config.AllowedIdentifiers)')
        return
    end
    writeCommandResult(cmd.id, 'clientexec', 'pending', 'dispatched to client')
    TriggerClientEvent('fivem-devtools:client:exec', target, cmd.id, args.command)
end

local function runServerExec(cmd)
    local args = cmd.args or {}
    if type(args.command) ~= 'string' or args.command == '' then
        writeCommandResult(cmd.id, 'serverexec', 'error', 'missing args.command')
        return
    end
    -- Requires `add_ace resource.fivem-devtools command.<cmd> allow` in
    -- server.cfg for anything ACE-restricted -- see ExecuteCommand.md (its
    -- own text says `add_acl`, which is very likely a docs typo for
    -- `add_ace`, the directive used everywhere else including this one) and
    -- docs/fxclient.md.
    local selfTarget = string.find(args.command, resourceName, 1, true) ~= nil
    if selfTarget then
        -- the command will stop this resource before it could report back
        writeCommandResult(cmd.id, 'serverexec', 'ok', 'executing (targets fivem-devtools itself; no further result)')
    end
    local ok, err = pcall(ExecuteCommand, args.command)
    if selfTarget then
        return
    end
    if ok then
        writeCommandResult(cmd.id, 'serverexec', 'ok', 'executed')
    else
        writeCommandResult(cmd.id, 'serverexec', 'error', 'ExecuteCommand failed: ' .. tostring(err))
    end
end

local commandHandlers = {
    screenshot = runScreenshot,
    profile = runProfile,
    info = runInfo,
    clientexec = runClientExec,
    serverexec = runServerExec,
}

local function processCommand(cmd)
    local handler = commandHandlers[cmd.cmd]
    if not handler then
        writeCommandResult(cmd.id, tostring(cmd.cmd), 'error', 'unknown command')
        return
    end
    local ok, err = pcall(handler, cmd)
    if not ok then
        writeCommandResult(cmd.id, cmd.cmd, 'error', 'internal error: ' .. tostring(err))
    end
end

-- Appends a command to queue/commands.json, exactly like bin/fxclient does,
-- so `devtools ...` (server console) and the CLI share one code path and
-- one id sequence. Picked up by the poll loop below within PollIntervalMs.
local function enqueueLocalCommand(cmdName, args)
    local queue = readJsonFile('queue/commands.json')
    if type(queue) ~= 'table' then
        queue = { next_id = 1, commands = {} }
    end
    if type(queue.commands) ~= 'table' then
        queue.commands = {}
    end
    if type(queue.next_id) ~= 'number' then
        queue.next_id = 1
    end
    local id = queue.next_id
    queue.next_id = id + 1
    queue.commands[#queue.commands + 1] = { id = id, cmd = cmdName, args = args or {}, ts = os.time() }
    writeJsonFile('queue/commands.json', queue)
    return id
end

-- ---------------------------------------------------------------------
-- net events (client -> server)
-- ---------------------------------------------------------------------

RegisterNetEvent('fivem-devtools:server:done', function(id, ok, msg)
    local src = source -- capture immediately: stale after any Wait/Await
    if not isAllowedPlayer(src) or rateLimited(src) then
        return
    end
    if type(id) ~= 'number' then
        return
    end
    -- Only apply if the command is still 'pending': for `screenshot` the
    -- HTTP upload landing is the authoritative success signal and normally
    -- arrives first, making a later ok=true `done` a harmless no-op here;
    -- for `clientexec` (no upload of its own) this is the only signal.
    local result = readJsonFile(resultFileName(id))
    if type(result) ~= 'table' or result.status ~= 'pending' then
        return
    end
    result.status = ok and 'ok' or 'error'
    result.message = type(msg) == 'string' and msg or (ok and 'ok' or 'client reported failure')
    writeJsonFile(resultFileName(id), result)
end)

RegisterNetEvent('fivem-devtools:server:info', function(id, data)
    local src = source
    if not isAllowedPlayer(src) or rateLimited(src) then
        return
    end
    if type(id) ~= 'number' or type(data) ~= 'table' then
        return
    end
    writeCommandResult(id, 'info', 'ok', 'ok', { data = data })
end)

RegisterNetEvent('fivem-devtools:server:log', function(level, text)
    local src = source
    if not isAllowedPlayer(src) or rateLimited(src) then
        return
    end
    if type(text) ~= 'string' then
        return
    end
    local name = GetPlayerName(src) or ('id ' .. tostring(src))
    local lvl = (type(level) == 'string' and level ~= '') and level or 'info'
    print(('[client:%s] [%s] %s'):format(name, lvl, text))
end)

-- ---------------------------------------------------------------------
-- HTTP handler registration
-- ---------------------------------------------------------------------

SetHttpHandler(httpRouter)

-- ---------------------------------------------------------------------
-- manual console command: `devtools screenshot|profile|info`
-- ---------------------------------------------------------------------

local function consolePrint(fmt, ...)
    print(('[fivem-devtools] ' .. fmt):format(...))
end

RegisterCommand('devtools', function(src, args)
    if src ~= 0 then
        return -- server-console-only, by design (see docs/fxclient.md)
    end
    local sub = args[1]
    if sub == 'screenshot' then
        enqueueLocalCommand('screenshot', {})
        consolePrint('screenshot enqueued -- see out/<id>.json (or run `fxclient screenshot`)')
    elseif sub == 'profile' then
        local resource = args[2]
        local frames = tonumber(args[3]) or 300
        enqueueLocalCommand('profile', { resource = resource, frames = frames })
        consolePrint('profile enqueued for %s (%d frames)', tostring(resource), frames)
    elseif sub == 'info' then
        enqueueLocalCommand('info', {})
        consolePrint('info enqueued -- see out/<id>.json')
    else
        consolePrint('usage: devtools screenshot | devtools profile <resource> [frames] | devtools info')
    end
end, true)

-- ---------------------------------------------------------------------
-- queue poll loop -- the ONLY thread in this resource. Single Wait() per
-- iteration, never per-frame (see $KIT/DESIGN.md §7/§8).
-- ---------------------------------------------------------------------

CreateThread(function()
    while true do
        local queue = readJsonFile('queue/commands.json')
        if type(queue) == 'table' and type(queue.commands) == 'table' then
            local pending = selectCommandsToRun(queue.commands, lastId)
            if #pending > 0 then
                for _, cmd in ipairs(pending) do
                    -- At-most-once: persist the id BEFORE executing. A command
                    -- like `restart fivem-devtools` kills this thread mid-way;
                    -- if lastId were saved afterwards, the restarted resource
                    -- would re-read the queue and re-run it forever.
                    lastId = cmd.id
                    saveState()
                    processCommand(cmd)
                end
            end
        end
        Wait(Config.PollIntervalMs)
    end
end)

-- ---------------------------------------------------------------------
-- Test hook: exposes the pure-logic locals above to the plain-Lua unit
-- test harness (tests/fixtures/lua_multipart_test.lua, driven by
-- tests/test_fxclient.py). FXServer discards a resource script's top-level
-- return value, so under the real runtime (where FXKIT_TEST is never set)
-- this is a complete no-op.
-- ---------------------------------------------------------------------

if FXKIT_TEST then
    return {
        identifierAllowed = identifierAllowed,
        selectCommandsToRun = selectCommandsToRun,
        getHeader = getHeader,
        parseBoundary = parseBoundary,
        parseMultipart = parseMultipart,
        guessExt = guessExt,
        addressOf = addressOf,
        normalizeAddress = normalizeAddress,
        isPrivateAddress = isPrivateAddress,
    }
end
