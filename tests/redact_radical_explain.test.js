'use strict';
// #163 偏旁说法（「单人旁一个韦」「三点水的江」）与没有提示词的单段解释（「李子的李」「张伟晨，伟大的伟」）：
// 规则在 site/assets/core/extractors.json 的 nameRules.explain.radicals / standalone，夹具 redact.json 的 radicalExplain，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const FX = require('./fixtures/redact.json').radicalExplain;

const LEAK = /韦|江|工|花|伟|晨|旁一个|点水|字头|字旁|的李|子的/;

test('#163 夹具 radicalExplain：逐项一致，打码的不露偏旁和字', () => {
  assert.ok(FX.filter((c) => c.expect === 'mask').length >= 12 && FX.filter((c) => c.expect === 'keep').length >= 8);
  for (const c of FX) {
    const ents = X.extractSensitive(c.text);
    assert.deepStrictEqual(R.findNameSpans(c.text, ents), c.spans, c.text);
    const out = R.redactText(c.text, ents);
    assert.strictEqual(out, c.redacted, c.text);
    assert.strictEqual(out !== c.text, c.expect === 'mask', c.text);
    if (c.expect === 'mask') assert.ok(!LEAK.test(out), c.text + ' -> ' + out);
  }
});

test('#163 issue 原句', () => {
  const red = (t) => R.redactText(t, X.extractSensitive(t));
  assert.strictEqual(red('弓长张，单人旁一个韦'), '弓长张，******');
  assert.strictEqual(red('三点水的江'), '*****');
  assert.strictEqual(red('伟大的那个伟字'), '*******');
  assert.strictEqual(red('李子的李'), '****');
  assert.strictEqual(red('张伟晨，伟大的伟'), '张**，****');
});
