const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('extension.js', 'utf8');

function grab(pattern) {
    let match = source.match(pattern)?.[0];
    assert.ok(match, `could not extract ${pattern}`);
    return match;
}

const pieces = [
    grab(/const POLL_INTERVAL = \d+;/),
    grab(/const POLL_MAX_INTERVAL = \d+;/),
    grab(/const REASON_LABEL = \{[\s\S]*?\n\};/),
    grab(/function percent\(value\) \{[\s\S]*?\n\}/),
    grab(/function usageBar\(used\) \{[\s\S]*?\n\}/),
    grab(/function reasonLabel\(reason\) \{[\s\S]*?\n\}/),
    grab(/function cacheAge\(fetchedAt\) \{[\s\S]*?\n\}/),
    grab(/function statusLine\(data\) \{[\s\S]*?\n\}/),
    grab(/function reading\(window, available, fresh\) \{[\s\S]*?\n\}/),
    grab(/function nextDelay\(delay, data\) \{[\s\S]*?\n\}/),
];
eval(`${pieces.join('\n')}
Object.assign(globalThis, {
    usageBar, reasonLabel, cacheAge, statusLine, reading, nextDelay,
    POLL_INTERVAL, POLL_MAX_INTERVAL,
});`);

// Bars keep a fixed width so the menu does not jitter between states.
assert.equal(usageBar(50), '██████████░░░░░░░ 50%');
assert.equal(usageBar(0), `${'░'.repeat(18)} 0%`);
assert.equal(usageBar(100), '████████████████ 100%');
assert.equal(usageBar(null), `${'░'.repeat(17)} --%`);
assert.equal(usageBar(null).length, usageBar(50).length);

// Status names the real problem instead of blaming the network for everything.
assert.equal(statusLine({ fresh: true }), 'LIVE');
assert.equal(statusLine({ state: 'stale', reason: 'rate', fetched_at: Date.now() / 1000 - 7260 }),
    'CACHE 2h old / RATE LIMITED');
assert.equal(statusLine({ state: 'stale', reason: 'network', fetched_at: Date.now() / 1000 - 600 }),
    'CACHE 10m old / OFFLINE');
assert.equal(statusLine({ state: 'auth' }), 'AUTH EXPIRED');
assert.equal(statusLine({}), 'ERROR');

// A cached reading is void once its window has reset, but only then.
assert.equal(reading({ percent: 57, expired: true }, true, false), null);
assert.equal(reading({ percent: 57, expired: true }, true, true), 57);
assert.equal(reading({ percent: 42, expired: false }, true, false), 42);
assert.equal(reading({ percent: 42 }, false, false), null);

// Failures back off; success returns to the base cadence; Retry-After is honoured.
assert.equal(nextDelay(POLL_INTERVAL, { fresh: true }), POLL_INTERVAL);
assert.equal(nextDelay(POLL_INTERVAL, {}), POLL_INTERVAL * 2);
assert.equal(nextDelay(POLL_MAX_INTERVAL, {}), POLL_MAX_INTERVAL);
assert.equal(nextDelay(POLL_INTERVAL, { retry_after: 900 }), 900);
assert.equal(nextDelay(POLL_INTERVAL, { retry_after: 10 }), POLL_INTERVAL);

// The indicator reschedules itself rather than firing on a fixed interval.
assert.match(source, /_scheduleNext\(\)/);
assert.ok(!source.includes('GLib.SOURCE_CONTINUE'), 'fixed-interval timer should be gone');

assert.match(source, /PopupMenuItem\('\[ REFRESH NOW \]'\)/);
assert.match(source, /font-family: monospace/);
assert.match(source, /\[ REFRESHING… \]/);
assert.ok(!source.includes("addAction('Refresh now'"));
console.log('console UI: ok');
