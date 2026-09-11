--[[
    Pattern: minimal client<->server callback system (standalone)

    Purpose:
        Lets a client ask the server to run something and get a return value
        back, and (symmetrically) lets the server ask a specific client for a
        value back -- without hand-rolling a request/response event pair for
        every single call site.

    Side: shared (this ONE file is loaded as a shared_script; it branches
        internally on IsDuplicityVersion() so the server half and client half
        live next to each other and agree on the wire event names for free).

    Usage:
        -- server/anywhere.lua
        RegisterCallback('myres:getBankBalance', function(src, accountId)
            return 1337 -- do your real lookup here
        end)

        -- client/anywhere.lua
        CreateThread(function()
            local balance = TriggerCallback('myres:getBankBalance', 'acc1')
            if balance == nil then
                print('callback timed out or errored')
            end
        end)

        -- reverse direction (server asks one client for something):
        -- client/anywhere.lua
        RegisterClientCallback('myres:confirmPrompt', function(promptText)
            return true
        end)
        -- server/anywhere.lua
        CreateThread(function()
            local confirmed = TriggerClientCallback(targetSrc, 'myres:confirmPrompt', 'Accept?')
        end)

    Dependencies: none.

    Notes:
        - TriggerCallback/TriggerClientCallback are promise-based, not
          polling: each call does `local p = promise.new()`, stores it by
          requestId, fires the request event, then suspends the calling
          coroutine on `Citizen.Await(p)` -- zero cost while waiting, no
          per-frame Wait. A `SetTimeout(CALLBACK_TIMEOUT_MS, ...)` resolves
          that same promise to nil if nothing arrives in time; the matching
          response event resolves it for real otherwise. Whichever fires
          first wins -- both paths guard on the pending-table entry still
          being set before they resolve, so the loser is a no-op. Returns nil
          on timeout and nil on the handler erroring (check the console/log
          for the actual error either way).
        - `promise`/`promise.new()`/`p:resolve(value)` are the bundled
          lua-promises implementation, exposed as the global `promise` table
          -- Source: fivem/data/shared/citizen/scripting/lua/deferred.lua:6
          (`_G.promise = M`), :127 (`M.new`), :119 (`:resolve`). `Citizen.Await`
          has no bare `Await` global alias (unlike Wait/CreateThread/
          SetTimeout), so it's the one legitimate use of the `Citizen.` prefix
          in this file -- Source: fivem/data/shared/citizen/scripting/lua/
          scheduler.lua:85-100 (runtime-facts §1); it must run inside a
          coroutine (CreateThread/a command/an event handler), same as Wait.
          This exact promise.new() + Citizen.Await(p) + SetTimeout shape is
          how FiveM's own PerformHttpRequestAwait is implemented internally
          -- Source: fivem/data/shared/citizen/scripting/lua/scheduler.lua:402-408.
        - ox_lib equivalent: the `lib` global exposes a callback module --
          `register(name, fn)` server-side, `await(name, ...)` client-side,
          hung off `lib` as its `callback` field -- see reference/frameworks.md.
          Prefer that over this file if ox_lib is already a dependency.
        - RegisterCallback/TriggerCallback/RegisterClientCallback/
          TriggerClientCallback are this file's only intentional globals (the
          public API other files in the resource are meant to call); every
          other identifier here is local.

    Verified with fxref on 2026-09-11: IsDuplicityVersion (shared).
    CreateThread/Wait/SetTimeout/RegisterNetEvent/TriggerServerEvent/
    TriggerClientEvent/promise/Citizen.Await are runtime globals/scheduler.lua
    constructs, not natives, so fxref doesn't carry them -- see the Notes
    above for exact source lines.
]]

local CALLBACK_TIMEOUT_MS = 5000

if IsDuplicityVersion() then
    -- ============================== SERVER ==============================
    local callbacks = {}          -- name -> function(src, ...) -> ...
    local waitingOnClient = {}    -- requestId -> { src = playerSrc, promise = promise }
    local nextRequestId = 0

    --- Register a name a client can TriggerCallback(name, ...) into.
    function RegisterCallback(name, handler)
        callbacks[name] = handler
    end

    --- Ask one specific client for a value; awaits (bounded) until it answers.
    function TriggerClientCallback(targetSrc, name, ...)
        nextRequestId = nextRequestId + 1
        local requestId = nextRequestId
        local p = promise.new()

        waitingOnClient[requestId] = { src = targetSrc, promise = p }

        TriggerClientEvent('fxdk:callback:s2c:request', targetSrc, name, requestId, ...)

        SetTimeout(CALLBACK_TIMEOUT_MS, function()
            if waitingOnClient[requestId] then
                waitingOnClient[requestId] = nil
                p:resolve(nil)
            end
        end)

        local results = Citizen.Await(p)
        if not results then return nil end
        return table.unpack(results, 1, results.n)
    end

    RegisterNetEvent('fxdk:callback:c2s:request', function(name, requestId, ...)
        local src = source
        local handler = callbacks[name]
        if type(name) ~= 'string' or not handler then
            TriggerClientEvent('fxdk:callback:c2s:response', src, requestId, false)
            return
        end

        local result = table.pack(pcall(handler, src, ...))
        local ok = result[1]
        if not ok then
            print(('[callback] %s errored: %s'):format(name, tostring(result[2])))
            TriggerClientEvent('fxdk:callback:c2s:response', src, requestId, false)
            return
        end

        -- result[1] is the pcall-ok flag, not part of the handler's own
        -- return values -- forward only result[2..n] to the caller.
        TriggerClientEvent('fxdk:callback:c2s:response', src, requestId, true, table.unpack(result, 2, result.n))
    end)

    RegisterNetEvent('fxdk:callback:s2c:response', function(requestId, ok, ...)
        local src = source
        local waiting = waitingOnClient[requestId]
        if not waiting or waiting.src ~= src then
            return -- unknown request, already timed out, or answered by the wrong client
        end
        waitingOnClient[requestId] = nil
        waiting.promise:resolve(ok and table.pack(...) or nil)
    end)
else
    -- ============================== CLIENT ==============================
    local clientCallbacks = {}    -- name -> function(...) -> ...
    local waitingOnServer = {}    -- requestId -> promise
    local nextRequestId = 0

    --- Register a name the server can TriggerClientCallback(src, name, ...) into.
    function RegisterClientCallback(name, handler)
        clientCallbacks[name] = handler
    end

    --- Ask the server for a value; awaits (bounded) until it answers.
    function TriggerCallback(name, ...)
        nextRequestId = nextRequestId + 1
        local requestId = nextRequestId
        local p = promise.new()

        waitingOnServer[requestId] = p

        TriggerServerEvent('fxdk:callback:c2s:request', name, requestId, ...)

        SetTimeout(CALLBACK_TIMEOUT_MS, function()
            if waitingOnServer[requestId] then
                waitingOnServer[requestId] = nil
                p:resolve(nil)
            end
        end)

        local results = Citizen.Await(p)
        if not results then return nil end
        return table.unpack(results, 1, results.n)
    end

    RegisterNetEvent('fxdk:callback:c2s:response', function(requestId, ok, ...)
        local p = waitingOnServer[requestId]
        if not p then return end
        waitingOnServer[requestId] = nil
        p:resolve(ok and table.pack(...) or nil)
    end)

    RegisterNetEvent('fxdk:callback:s2c:request', function(name, requestId, ...)
        local handler = clientCallbacks[name]
        if type(name) ~= 'string' or not handler then
            TriggerServerEvent('fxdk:callback:s2c:response', requestId, false)
            return
        end

        local result = table.pack(pcall(handler, ...))
        local ok = result[1]
        if not ok then
            print(('[callback] %s errored: %s'):format(name, tostring(result[2])))
            TriggerServerEvent('fxdk:callback:s2c:response', requestId, false)
            return
        end

        TriggerServerEvent('fxdk:callback:s2c:response', requestId, true, table.unpack(result, 2, result.n))
    end)
end
