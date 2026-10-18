'use strict';
// 断续句情报回归（#8）：与 python/tests/test_halting_recall.py 共用 tests/fixtures/halting_vectors.json。
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const VEC = require('./fixtures/halting_vectors.json');

const INTEL = ['bank_card', 'phone', 'crypto_tron', 'crypto_eth', 'crypto_btc'];
function sessionIntel(turns) {
  const s = new E.Session({ scenario: 'refund', persona: 'wang', rng: () => 0.5, now: () => 0 });
  for (const t of turns) s.ingest(t);
  return Object.keys(s.intel).map((k) => s.intel[k]).filter((i) => INTEL.includes(i.type))
    .map((i) => [i.type, String(i.raw).replace(/[^0-9A-Za-z]/g, '')]).sort();
}

for (const c of VEC.positive) {
  test('断续句正例：' + c.name, () => {
    assert.deepEqual(sessionIntel(c.turns), c.want.slice().sort());
  });
}

for (const c of VEC.negative) {
  test('断续句负例：' + c.name, () => {
    assert.deepEqual(sessionIntel(c.turns), []);
  });
}
