// fxlint bad-resource fixture: client side JS.
// Not referenced from fxmanifest.lua on purpose -- side is picked up via the
// client/ path heuristic fallback instead of the manifest script lists.

(async () => {
    while (true) { // expect: P001
        DoSomethingForever();
    }
})();

(async () => {
    while (true) {
        await Delay(0); // expect: P002
    }
})();

let ped = GetPlayerPed(-1); // expect: C002

// supports the C010 case in server/extra.js
emitNet('bad:jsClientTriggered');

on('bad:jsLocalHandler', () => {
    TriggerClientEvent('bad:jsWrongSide', -1); // expect: C009
});

if (source) { // expect: C009
    console.log(source);
}
