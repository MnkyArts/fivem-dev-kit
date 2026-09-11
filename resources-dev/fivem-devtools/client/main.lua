-- fivem-devtools :: client
--
-- Protocol and architecture: $KIT/docs/fxclient.md. This file only reacts to
-- net events the server dispatches after picking the allowed dev player --
-- nothing here runs unprompted, and nothing here is a per-frame loop.

-- ---------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------

local function buildUploadUrl(path)
    local endpoint = GetCurrentServerEndpoint()
    if not endpoint or endpoint == '' then
        return nil
    end
    return ('http://%s/fivem-devtools%s'):format(endpoint, path)
end

-- ---------------------------------------------------------------------
-- screenshot: server picked us, we grab a frame via screenshot-basic and
-- upload it directly (over HTTP, not via this resource's queue) to our own
-- server HTTP handler.
-- ---------------------------------------------------------------------

RegisterNetEvent('fivem-devtools:client:screenshot', function(id, opts)
    opts = opts or {}

    local url = buildUploadUrl(('/upload/screenshot?id=%d'):format(id))
    if not url then
        TriggerServerEvent('fivem-devtools:server:done', id, false, 'GetCurrentServerEndpoint() returned nothing')
        return
    end

    local resmonEnabled = false
    if opts.resmon then
        ExecuteCommand('resmon 1')
        resmonEnabled = true
    end

    Wait(1500) -- let resmon (if enabled) and the current frame settle before capturing

    exports['screenshot-basic']:requestScreenshotUpload(url, 'file', {
        encoding = (opts.encoding == 'jpg') and 'jpg' or 'png',
        quality = 0.92,
    }, function(result)
        if resmonEnabled then
            ExecuteCommand('resmon 0')
        end
        -- Our own /upload/screenshot handler replies with the plain body
        -- 'ok' on success (see server/main.lua respondPlain(200, 'ok')) and
        -- an error string otherwise -- if the upload never reached it at
        -- all (network failure), `result` will be nil or something else.
        if result == 'ok' then
            TriggerServerEvent('fivem-devtools:server:done', id, true, 'uploaded')
        else
            TriggerServerEvent('fivem-devtools:server:done', id, false, 'upload did not confirm: ' .. tostring(result))
        end
    end)
end)

-- ---------------------------------------------------------------------
-- profile: kick off the CPU profiler, wait for it to finish, dump JSON to
-- the FiveM app dir. fxclient-agent.ps1 (running on this same Windows PC)
-- is what actually uploads the resulting file -- this resource only starts
-- the recording and can't itself reach the server's real filesystem to send
-- it (SaveResourceFile is server-only, and the profiler can only write to
-- citizen:/ on the client -- see docs/fxclient.md).
-- ---------------------------------------------------------------------

RegisterNetEvent('fivem-devtools:client:profile', function(id, opts)
    opts = opts or {}
    local frames = tonumber(opts.frames) or 300
    if frames < 1 then
        frames = 300
    end

    local cmd
    if type(opts.resource) == 'string' and opts.resource ~= '' then
        -- Resource-scoped recording (Profiler.cpp:551-574, `resourceCmd`,
        -- registered as the 2-arg overload of the "resource" subcommand):
        -- `profiler resource <resourceName> <frames>`.
        cmd = ('profiler resource %s %d'):format(opts.resource, frames)
    else
        -- No resource given -> record every resource (Profiler.cpp:495-527,
        -- `recordCmd`): `profiler record <frames>`.
        cmd = ('profiler record %d'):format(frames)
    end

    ExecuteCommand(cmd)
    Wait(200) -- give the console command a moment to take effect

    if not ProfilerIsRecording() then
        TriggerServerEvent('fivem-devtools:server:log', 'error', ('devtools profile %d: `%s` did not start a recording -- most likely the client is in production mode (launch FiveM with +set moo 31337; see fxclient logs --errors), else a recording was already active or the resource name is wrong'):format(id, cmd))
        return
    end

    -- A frame-limited recording stops itself (BeginTick counts frames down
    -- to 0 -- Profiler.cpp ~796); this loop is a bound, not the primary
    -- stop mechanism, and it's a Wait()-driven loop so it never runs
    -- per-frame.
    local maxWaitMs = math.floor(frames / 60 * 1000) + 1500
    local waited = 0
    while ProfilerIsRecording() and waited < maxWaitMs do
        Wait(250)
        waited = waited + 250
    end

    ExecuteCommand(('profiler saveJSON devprofile-%d.json'):format(id))
    TriggerServerEvent('fivem-devtools:server:log', 'info', ('devtools profile %d: saveJSON devprofile-%d.json issued -- fxclient-agent.ps1 uploads it next'):format(id, id))
end)

-- ---------------------------------------------------------------------
-- info: a snapshot of fps/coords/vehicle/resource states, sent back over a
-- net event (small payload, no upload needed).
-- ---------------------------------------------------------------------

RegisterNetEvent('fivem-devtools:client:info', function(id, opts)
    opts = opts or {}

    local ped = PlayerPedId()
    local coords = GetEntityCoords(ped)

    local frameTime = GetFrameTime()
    local fps = 0
    if frameTime > 0.0 then
        fps = math.floor(1.0 / frameTime + 0.5)
    end

    local vehicle = GetVehiclePedIsIn(ped, false)
    local vehicleInfo = nil
    if vehicle ~= 0 then
        local model = GetEntityModel(vehicle)
        vehicleInfo = { model = model, name = GetDisplayNameFromVehicleModel(model) }
    end

    local resourceStates = {}
    local wanted = opts.resources
    if type(wanted) == 'table' and #wanted > 0 then
        for i = 1, math.min(#wanted, Config.MaxInfoResources) do
            local name = wanted[i]
            if type(name) == 'string' then
                resourceStates[name] = GetResourceState(name)
            end
        end
    else
        local total = GetNumResources()
        local cap = math.min(total, Config.MaxInfoResources)
        for i = 0, cap - 1 do
            local name = GetResourceByFindIndex(i)
            if type(name) == 'string' and name ~= '' then
                resourceStates[name] = GetResourceState(name)
            end
        end
    end

    TriggerServerEvent('fivem-devtools:server:info', id, {
        fps = fps,
        coords = { x = coords.x, y = coords.y, z = coords.z },
        heading = GetEntityHeading(ped),
        vehicle = vehicleInfo,
        pedHealth = GetEntityHealth(ped),
        gameBuild = GetGameBuildNumber(),
        resourceCount = GetNumResources(),
        resourceStates = resourceStates,
    })
end)

-- ---------------------------------------------------------------------
-- exec: run one console command on the client (dev only).
-- ---------------------------------------------------------------------

RegisterNetEvent('fivem-devtools:client:exec', function(id, command)
    if type(command) ~= 'string' or command == '' then
        TriggerServerEvent('fivem-devtools:server:done', id, false, 'missing command')
        return
    end
    local ok, err = pcall(ExecuteCommand, command)
    if ok then
        TriggerServerEvent('fivem-devtools:server:done', id, true, 'executed')
    else
        TriggerServerEvent('fivem-devtools:server:done', id, false, 'ExecuteCommand failed: ' .. tostring(err))
    end
end)
