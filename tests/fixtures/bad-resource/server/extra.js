// fxlint bad-resource fixture: server side JS -- exists to exercise C010,
// which only makes sense for JS (on() vs onNet()). Side is picked up via the
// server/ path heuristic fallback, same as client/extra.js.

on('bad:jsClientTriggered', () => { // expect: C010
    console.log('a client triggers this -- should be onNet(), not on()');
});
