// #153：跨轮去重 dedupeTail（与 Python deepsuck.engine.dedupe_tail 同一组用例 tests/fixtures/tail_dedupe.json）
const test = require('node:test');
const assert = require('node:assert');
const E = require('../site/assets/js/engine.js');
const FIX = require('./fixtures/tail_dedupe.json');

test('fixture cases', () => {
  for (const c of FIX.cases) {
    assert.strictEqual(E.dedupeTail(c.text, c.recent, c.persona), c.expected, c.text);
    assert.strictEqual(E.tailSentence(c.text), c.tail, c.text);
    const out = c.expected;
    assert.strictEqual(E.dedupeTail(out, c.recent, c.persona), out);
  }
});

test('pure: input not mutated, window of 3', () => {
  const recent = ['你再说一遍。', 'a', 'b', 'c'];
  assert.strictEqual(E.dedupeTail('你再说一遍。', recent), '你再说一遍。');
  assert.deepStrictEqual(recent, ['你再说一遍。', 'a', 'b', 'c']);
});

test('demo wires dedupe for LLM replies only', () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '../site/assets/js/demo.js'), 'utf8');
  assert.match(src, /dedupeTail\(reply, recentTails\(s\), s\.persona\.id\)/);
});

test('no new lead phrases; fallback only from approved lines', () => {
  const PJ = require('../site/assets/core/personas.json');
  assert.ok(!('lead' in PJ.tailDedupe) && !('particles' in PJ.tailDedupe));
  const src = require('fs').readFileSync(require('path').join(__dirname, '../site/assets/core/personas.json'), 'utf8');
  assert.ok(!src.includes('我是说，') && !src.includes('还是那句，'));
  const pool = PJ.personas.find((p) => p.id === 'chen').templates.ask_repeat.filter((x) => typeof x === 'string' && !x.includes('{'));
  const out = E.dedupeTail(pool[0], pool.slice(0, 3), 'chen');
  assert.ok(pool.slice(3).includes(out), out);
  assert.strictEqual(E.dedupeTail(pool[0], pool.slice(0, 3)), '');
});
