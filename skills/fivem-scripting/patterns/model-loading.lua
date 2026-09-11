--[[
    Pattern: timeout-bounded model / anim dict / ptfx loading helpers

    Purpose:
        RequestModel/RequestAnimDict/RequestNamedPtfxAsset are all
        fire-and-forget; you must poll Has*Loaded until it's true before
        using the asset, and that poll must be bounded so a bad/missing
        asset name can't hang the calling coroutine forever. Each loader
        returns true/false instead of erroring, plus a matching release
        helper (assets stay streamed in until you explicitly release them).

    Side: client.

    Usage:
        if loadModel('a_m_y_business_01', 8000) then
            local ped = CreatePed(4, GetHashKey('a_m_y_business_01'), coords.x, coords.y, coords.z, heading, true, true)
            releaseModel('a_m_y_business_01') -- safe once the ped/object/vehicle exists
        end

        if loadAnimDict('missheistdockssetup1clipboard@base') then
            TaskPlayAnim(PlayerPedId(), 'missheistdockssetup1clipboard@base', 'base', 8.0, -8.0, -1, 0, 0, false, false, false)
            releaseAnimDict('missheistdockssetup1clipboard@base')
        end

    Dependencies: none.

    Verified with fxref on 2026-09-11 (all apiset client): RequestModel,
    HasModelLoaded, SetModelAsNoLongerNeeded, IsModelValid, RequestAnimDict,
    HasAnimDictLoaded, RemoveAnimDict, RequestNamedPtfxAsset,
    HasNamedPtfxAssetLoaded, RemoveNamedPtfxAsset.
]]

local DEFAULT_TIMEOUT_MS = 10000

--- Requests `model` (name or hash) and waits (bounded) until it's loaded.
--- Returns false immediately if the model isn't a valid/streamed model.
local function loadModel(model, timeoutMs)
    local hash = type(model) == 'string' and GetHashKey(model) or model
    if not IsModelValid(hash) then
        return false
    end
    if HasModelLoaded(hash) then
        return true
    end

    RequestModel(hash)
    local start = GetGameTimer()
    timeoutMs = timeoutMs or DEFAULT_TIMEOUT_MS
    while not HasModelLoaded(hash) do
        if GetGameTimer() - start > timeoutMs then
            return false
        end
        Wait(0) -- per-frame: polling model load status, bounded by timeoutMs
    end
    return true
end

--- Marks `model` as no longer needed so the streamer can evict it.
local function releaseModel(model)
    local hash = type(model) == 'string' and GetHashKey(model) or model
    SetModelAsNoLongerNeeded(hash)
end

--- Requests animation dictionary `dict` and waits (bounded) until it's loaded.
local function loadAnimDict(dict, timeoutMs)
    if HasAnimDictLoaded(dict) then
        return true
    end

    RequestAnimDict(dict)
    local start = GetGameTimer()
    timeoutMs = timeoutMs or DEFAULT_TIMEOUT_MS
    while not HasAnimDictLoaded(dict) do
        if GetGameTimer() - start > timeoutMs then
            return false
        end
        Wait(0) -- per-frame: polling anim dict load status, bounded by timeoutMs
    end
    return true
end

--- Releases animation dictionary `dict`.
local function releaseAnimDict(dict)
    RemoveAnimDict(dict)
end

--- Requests particle effect asset `assetName` and waits (bounded) until loaded.
local function loadPtfx(assetName, timeoutMs)
    if HasNamedPtfxAssetLoaded(assetName) then
        return true
    end

    RequestNamedPtfxAsset(assetName)
    local start = GetGameTimer()
    timeoutMs = timeoutMs or DEFAULT_TIMEOUT_MS
    while not HasNamedPtfxAssetLoaded(assetName) do
        if GetGameTimer() - start > timeoutMs then
            return false
        end
        Wait(0) -- per-frame: polling ptfx asset load status, bounded by timeoutMs
    end
    return true
end

--- Releases particle effect asset `assetName`.
local function releasePtfx(assetName)
    RemoveNamedPtfxAsset(assetName)
end
