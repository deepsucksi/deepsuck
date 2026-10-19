'use strict';
// #187：人设不得说成已经转账或答应去转。用例 tests/fixtures/transfer_claim.json 与 python/tests/test_transfer_claim.py、
// voice/tests/test_transfer_claim.py 共用；Python deepsuck.engine.hold_transfer 逐字一致。
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const L = require('../site/assets/js/llm.js');
const P = require('../site/assets/js/personas.js');
const PJ = require('../site/assets/core/personas.json');
const F = require('./fixtures/transfer_claim.json');

const TC = P.TRANSFER_CLAIM;
const anyClaim = (t) => {
  const s = String(t).replace(new RegExp(TC.quote, 'g'), '\uE010');
  return (s.match(new RegExp('[^' + TC.split.replace(/[\\\]\[^\-]/g, '\\$&') + ']+', 'g')) || []).some((x) => E.transferClaim(x));
};

test('用例够多：正例、反例各不少于 30 条，含长通话里的三句原话', () => {
  assert.ok(F.claim.length >= 30 && F.keep.length >= 30);
  const texts = F.claim.map((c) => c.text);
  for (const w of ['转完了', '转过去了…你那边收到了没', '我先转']) assert.ok(texts.some((t) => t.includes(w)), w);
});

test('正例：改写成拖延说法，逐字等于 expected，过滤后不再有已转 / 承诺转', () => {
  for (const c of F.claim) {
    const out = E.holdTransfer(c.text);
    assert.equal(out, c.expected, c.text);
    if (c.mustKeep) assert.ok(out.includes(c.mustKeep), '#204 保留那一问：' + out);
    assert.notEqual(out, c.text, c.text);
    assert.ok(TC.stall.some((x) => out.includes(x)), out);
    assert.equal(anyClaim(out), false, out);
    assert.equal(E.holdTransfer(out), out, '再过一遍不变：' + out);
  }
});

test('反例：否定、引述对方的话、假设、问细节原样', () => {
  for (const t of F.keep) assert.equal(E.holdTransfer(t), t);
});

test('已批台词全部原样通过（过滤只拦模型的话，不改台词）', () => {
  let n = 0;
  const walk = (o, path) => {
    if (typeof o === 'string') { n++; assert.equal(E.holdTransfer(o), o, path); }
    else if (Array.isArray(o)) o.forEach((v, i) => walk(v, path + '[' + i + ']'));
    else if (o && typeof o === 'object') Object.keys(o).forEach((k) => { if (k !== 'when') walk(o[k], path + '.' + k); });
  };
  PJ.personas.forEach((p) => walk(p, p.id));
  assert.ok(n > 1000);
});

test('网页：sanitizeReply 接上过滤；提示词规则 3 是同一句、不举原话', () => {
  assert.equal(L.sanitizeReply('好，我先转。'), '好，还在弄，没弄好。');
  assert.equal(L.sanitizeReply('转过去了…你那边收到了没？'), '还在弄，没弄好。');
  assert.equal(L.sanitizeReply('我还没转，你别急。'), '我还没转，你别急。');
  const sp = L.systemPrompt(P.PERSONAS[0], null, 'fake_progress', [], ['你快点转账']);
  assert.ok(sp.includes('3. ' + TC.rule));
  for (const w of ['转完了', '我先转', '转过去了', '收到了没']) assert.ok(!sp.includes(w), w);
});
