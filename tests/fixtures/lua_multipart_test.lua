-- Pure-Lua unit test harness for the fivem-devtools resource's testable
-- pure functions (multipart parsing, queue command-id filtering, etc).
-- Runs under a plain system Lua (no FXServer, no natives available), which
-- is exactly why server/main.lua only exposes functions that don't call any
-- native at all (see the FXKIT_TEST export block at the bottom of that
-- file) -- everything exercised here is pure string/table logic.
--
-- Usage: lua lua_multipart_test.lua <path-to-fivem-devtools-resource-dir>
-- Driven by tests/test_fxclient.py. Exit code 0 = all PASS, 1 = any FAIL.

local resourceDir = arg[1]
if not resourceDir then
    print('usage: lua lua_multipart_test.lua <resource-dir>')
    os.exit(2)
end

local passCount, failCount = 0, 0

local function check(name, cond)
    if cond then
        passCount = passCount + 1
        print('PASS ' .. name)
    else
        failCount = failCount + 1
        print('FAIL ' .. name)
    end
end

-- ---------------------------------------------------------------------
-- minimal native/runtime shim -- only what server/main.lua calls at FILE
-- SCOPE (i.e. immediately, as the chunk runs) needs a stub. Everything
-- else lives inside function bodies this harness never calls (CreateThread
-- and friends deliberately do NOT invoke the function they're given).
-- ---------------------------------------------------------------------

function GetCurrentResourceName()
    return 'fivem-devtools'
end

function LoadResourceFile(_, _)
    return nil
end

function RegisterNetEvent(_, _) end
function SetHttpHandler(_) end
function RegisterCommand(_, _, _) end
function CreateThread(_) end -- must NOT invoke fn -- it's `while true do ... end`

json = {
    encode = function(_) return '{}' end,
    decode = function(_) return nil end,
}

-- ---------------------------------------------------------------------
-- load the real shared/config.lua, then the real server/main.lua
-- ---------------------------------------------------------------------

local configChunk, configErr = loadfile(resourceDir .. '/shared/config.lua')
if not configChunk then
    print('FAIL could not load shared/config.lua: ' .. tostring(configErr))
    os.exit(1)
end
configChunk()

if type(Config) ~= 'table' or type(Config.AllowedIdentifiers) ~= 'table' then
    print('FAIL shared/config.lua did not populate Config.AllowedIdentifiers')
    os.exit(1)
end

FXKIT_TEST = true
local serverChunk, serverErr = loadfile(resourceDir .. '/server/main.lua')
if not serverChunk then
    print('FAIL could not load server/main.lua: ' .. tostring(serverErr))
    os.exit(1)
end

local mod = serverChunk()
if type(mod) ~= 'table' then
    print('FAIL server/main.lua did not return its FXKIT_TEST export table')
    os.exit(1)
end

-- ---------------------------------------------------------------------
-- selectCommandsToRun
-- ---------------------------------------------------------------------

do
    local commands = { { id = 1, cmd = 'a' }, { id = 3, cmd = 'c' }, { id = 2, cmd = 'b' } }

    local pending = mod.selectCommandsToRun(commands, 1)
    check('selectCommandsToRun: filters id > sinceId and sorts ascending',
        #pending == 2 and pending[1].id == 2 and pending[2].id == 3)

    check('selectCommandsToRun: empty when sinceId >= max id', #mod.selectCommandsToRun(commands, 5) == 0)
    check('selectCommandsToRun: everything when sinceId is 0', #mod.selectCommandsToRun(commands, 0) == 3)
    check('selectCommandsToRun: tolerates a non-table entry',
        #mod.selectCommandsToRun({ 'garbage', { id = 1 } }, 0) == 1)
end

-- ---------------------------------------------------------------------
-- identifierAllowed (real Config.AllowedIdentifiers from shared/config.lua)
-- ---------------------------------------------------------------------

do
    check('identifierAllowed: true for a configured identifier', mod.identifierAllowed('fivem:414243') == true)
    check('identifierAllowed: false for an unconfigured identifier', mod.identifierAllowed('steam:deadbeef') == false)
    check('identifierAllowed: false for nil', mod.identifierAllowed(nil) == false)
end

-- ---------------------------------------------------------------------
-- getHeader / parseBoundary
-- ---------------------------------------------------------------------

do
    local headers = { ['Content-Type'] = 'multipart/form-data; boundary=abc123', ['X-Foo'] = 'bar' }
    check('getHeader: case-insensitive match', mod.getHeader(headers, 'content-type') == headers['Content-Type'])
    check('getHeader: missing header -> nil', mod.getHeader(headers, 'nope') == nil)

    check('parseBoundary: unquoted', mod.parseBoundary('multipart/form-data; boundary=abc123') == 'abc123')
    check('parseBoundary: quoted with a space', mod.parseBoundary('multipart/form-data; boundary="abc 123"') == 'abc 123')
    check('parseBoundary: no boundary -> nil', mod.parseBoundary('text/plain') == nil)
end

-- ---------------------------------------------------------------------
-- guessExt
-- ---------------------------------------------------------------------

do
    check('guessExt: from filename extension', mod.guessExt('shot.jpg', nil) == 'jpg')
    check('guessExt: filename extension is lowercased', mod.guessExt('SHOT.PNG', nil) == 'png')
    check('guessExt: falls back to image/jpeg content-type', mod.guessExt(nil, 'image/jpeg') == 'jpg')
    check('guessExt: defaults to png', mod.guessExt(nil, nil) == 'png')
end

-- ---------------------------------------------------------------------
-- addressOf
-- ---------------------------------------------------------------------

do
    check('addressOf: strips the port', mod.addressOf('127.0.0.1:30120') == '127.0.0.1')
    check('addressOf: bare address unchanged', mod.addressOf('127.0.0.1') == '127.0.0.1')
    check('addressOf: nil -> nil', mod.addressOf(nil) == nil)
end

-- ---------------------------------------------------------------------
-- parseMultipart -- the important one: byte-safety, headers, error paths
-- ---------------------------------------------------------------------

do
    local boundary = 'TestBoundary123'
    local fileBytes = 'BINARY\0\1\2\xFFDATA'
    local body = table.concat({
        '--', boundary, '\r\n',
        'Content-Disposition: form-data; name="file"; filename="shot.png"', '\r\n',
        'Content-Type: image/png', '\r\n',
        '\r\n',
        fileBytes,
        '\r\n',
        '--', boundary, '--\r\n',
    })

    local data, info = mod.parseMultipart(body, boundary)
    check('parseMultipart: extracts the exact byte-for-byte payload (incl. NUL and 0xFF)', data == fileBytes)
    check('parseMultipart: extracted length matches the source', data ~= nil and #data == #fileBytes)
    check('parseMultipart: filename parsed from headers', info ~= nil and info.filename == 'shot.png')
    check('parseMultipart: content-type parsed from headers', info ~= nil and info.contentType == 'image/png')

    local missData, missErr = mod.parseMultipart(body, 'NotTheBoundary')
    check('parseMultipart: unknown boundary fails cleanly', missData == nil and missErr == 'boundary not found')

    local truncated = '--' .. boundary .. '\r\nContent-Type: image/png\r\n\r\nnoclosingboundary'
    local truncData, truncErr = mod.parseMultipart(truncated, boundary)
    check('parseMultipart: missing closing boundary fails cleanly',
        truncData == nil and truncErr == 'closing boundary not found')

    -- Multiple parts: only the first is extracted -- matches this
    -- resource's actual use (screenshot/profile uploads are always exactly
    -- one file part).
    local multiPart = table.concat({
        '--', boundary, '\r\n',
        'Content-Disposition: form-data; name="a"', '\r\n',
        '\r\n',
        'first-part-data',
        '\r\n--', boundary, '\r\n',
        'Content-Disposition: form-data; name="b"', '\r\n',
        '\r\n',
        'second-part-data',
        '\r\n--', boundary, '--\r\n',
    })
    local firstData = mod.parseMultipart(multiPart, boundary)
    check('parseMultipart: multi-part body yields the first part only', firstData == 'first-part-data')
end

print()
print(passCount .. ' passed, ' .. failCount .. ' failed')
os.exit(failCount > 0 and 1 or 0)
