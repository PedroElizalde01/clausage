const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('extension.js', 'utf8');

const percentSource = source.match(/function percent\(value\) \{[\s\S]*?\n\}/)?.[0];
const barSource = source.match(/function usageBar\(used\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(percentSource && barSource);
eval(`${percentSource}\n${barSource}\nglobalThis.usageBar = usageBar;`);

assert.equal(usageBar(50), '██████████░░░░░░░ 50%');
assert.equal(usageBar(0), `${'░'.repeat(18)} 0%`);
assert.equal(usageBar(100), '████████████████ 100%');
console.log('progress bars: ok');
