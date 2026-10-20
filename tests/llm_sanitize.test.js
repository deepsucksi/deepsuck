// #194：llm.js sanitizeReply 与 Python deepsuck.llmfilter.sanitize_reply 共用用例 tests/fixtures/llm_sanitize.json
const test = require('node:test');
const assert = require('node:assert');
const L = require('../site/assets/js/llm.js');
const E = require('../site/assets/js/engine.js');
const FIX = require('./fixtures/llm_sanitize.json');

test('sanitizeReply fixture cases', () => {
  for (const c of FIX.cases) {
    assert.strictEqual(L.sanitizeReply(c.text), c.expected, c.text);
    assert.strictEqual(L.sanitizeReply(L.sanitizeReply(c.text)), c.twice, c.text);
  }
});

test('proxy pipeline: sanitize twice → dedupeTail → vagueDigits', () => {
  for (const c of FIX.pipeline) {
    let s = L.sanitizeReply(L.sanitizeReply(c.text));
    s = E.dedupeTail(s, c.recent.slice(-3).map(E.tailSentence), c.persona);
    assert.strictEqual(E.vagueDigits(s), c.expected, c.text);
  }
});
