--[[
    Pattern: NUI focus/message/callback bridge

    Purpose:
        The client-side half of a focus-on-open, focus-off-on-close NUI page:
        SetNuiFocus when opening, SendNUIMessage to push data in,
        RegisterNuiCallback to receive data back, a throttle helper so
        SendNUIMessage can't be called faster than MESSAGE_THROTTLE_MS, and an
        Escape-key close that only polls while the UI is actually open.
        Pairs with patterns/nui/index.html + script.js + style.css.

    Side: client.

    Usage:
        RegisterCommand('myres:openui', function() openUI({ example = true }) end, false)
        -- from the NUI page: fetch(.../close) or press Escape to close.

    Dependencies: files/ui_page entries for html/index.html, html/script.js,
        html/style.css in fxmanifest.lua (see templates/fxmanifest.nui.lua).

    Close key: INPUT_FRONTEND_PAUSE_ALTERNATE, control index 200, default key
    ESC -- verified via `fxref docs show docs/game-references/controls`.

    Verified with fxref on 2026-09-11: SetNuiFocus (apiset client),
    RegisterNuiCallback (apiset client, the current native form --
    runtime-facts §12 notes the capitalized RegisterNUICallback Lua global is
    legacy). SendNUIMessage (documented table-taking Lua wrapper, confirmed
    via `fxref docs show docs/scripting-reference/runtimes/lua/functions/SendNUIMessage`
    -- distinct from the raw SendNuiMessage(jsonString) native) is in
    fxlint's runtime-globals allowlist. IsControlJustReleased (apiset client).
]]

local MESSAGE_THROTTLE_MS = 50
local nuiOpen = false
local lastMessageAt = 0

local function openUI(data)
    nuiOpen = true
    SetNuiFocus(true, true)
    SendNUIMessage({ action = 'open', payload = data })
end

local function closeUI()
    if not nuiOpen then return end
    nuiOpen = false
    SetNuiFocus(false, false)
    SendNUIMessage({ action = 'close' })
end

--- Drops the message instead of sending if called again within
--- MESSAGE_THROTTLE_MS of the last one. Returns whether it actually sent.
local function sendThrottled(payload)
    local now = GetGameTimer()
    if now - lastMessageAt < MESSAGE_THROTTLE_MS then
        return false
    end
    lastMessageAt = now
    SendNUIMessage(payload)
    return true
end

RegisterNuiCallback('close', function(data, cb)
    closeUI()
    cb({ ok = true }) -- cb() must always be called or the page's fetch() hangs until it times out
end)

RegisterNuiCallback('submit', function(data, cb)
    -- `data` is already the decoded JSON body the page posted, e.g. data.someField
    cb({ ok = true })
end)

RegisterCommand('myres:openui', function()
    openUI({ example = true })
end, false)

CreateThread(function()
    while true do
        local sleep = 500

        if nuiOpen then
            sleep = 0 -- per-frame: only while the UI is open, to catch Escape promptly
            if IsControlJustReleased(0, 200) then -- INPUT_FRONTEND_PAUSE_ALTERNATE (default ESC)
                closeUI()
            end
        end

        Wait(sleep)
    end
end)
