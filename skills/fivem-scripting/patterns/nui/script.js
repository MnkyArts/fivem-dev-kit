/*
    Pattern: NUI page bridge script (pairs with ../nui-bridge.lua + index.html)

    - window.addEventListener('message') receives SendNUIMessage({...}) payloads.
    - postToLua() is the throttled wrapper around fetch(); every NUI callback
      it targets must call cb(...) Lua-side or this fetch() hangs until the
      browser's own timeout (see ../nui-bridge.lua's cb({ok=true}) calls).
    - Escape closes the page locally *and* tells Lua, so SetNuiFocus gets
      turned back off even if the page is closed from the browser side.

    Side: browser (CEF) -- not the Citizen JS runtime. GetParentResourceName()
    is an NUI-page-only helper FiveM injects into this context; it is not a
    Citizen native and isn't in fxref.
*/

(function () {
    'use strict';

    var root = document.getElementById('root');
    var payloadEl = document.getElementById('payload');
    var closeBtn = document.getElementById('closeBtn');
    var submitBtn = document.getElementById('submitBtn');

    var THROTTLE_MS = 50;
    var lastPostAt = 0;

    function resourceName() {
        // Only meaningful when this page is actually loaded by FiveM's NUI
        // host; guarded so this file can still be opened directly in a
        // browser for layout work.
        return typeof GetParentResourceName === 'function' ? GetParentResourceName() : 'nui-bridge';
    }

    // Throttled POST to a Lua-side RegisterNuiCallback(name, ...) handler.
    // Returns the fetch() promise, or null if this call was dropped.
    function postToLua(name, body) {
        var now = Date.now();
        if (now - lastPostAt < THROTTLE_MS) {
            return null;
        }
        lastPostAt = now;

        return fetch('https://' + resourceName() + '/' + name, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json; charset=UTF-8' },
            body: JSON.stringify(body || {}),
        });
    }

    function show(payload) {
        payloadEl.textContent = payload ? JSON.stringify(payload) : '';
        root.classList.remove('hidden');
    }

    function hide() {
        root.classList.add('hidden');
    }

    function closeUI() {
        hide();
        postToLua('close', {});
    }

    window.addEventListener('message', function (event) {
        var data = event.data || {};
        if (data.action === 'open') {
            show(data.payload);
        } else if (data.action === 'close') {
            hide();
        }
    });

    window.addEventListener('keyup', function (event) {
        if (event.key === 'Escape' && !root.classList.contains('hidden')) {
            closeUI();
        }
    });

    closeBtn.addEventListener('click', closeUI);

    submitBtn.addEventListener('click', function () {
        postToLua('submit', { example: true });
    });
})();
