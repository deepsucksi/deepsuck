// #130：打码片段换成含糊说法、叠词去重、人设姓名规则（与 python/tests/test_masked_fragments.py 对应）
const test = require('node:test');
const assert = require('node:assert');
const E = require('../site/assets/js/engine.js');
const P = require('../site/assets/js/personas.js');
const S = require('../site/assets/js/scenarios.js');
const L = require('../site/assets/js/llm.js');
const PJ = require('../site/assets/core/personas.json');

test('masked names fully replaced with 那个名字', () => {
  for (const [src, sur] of [['户名是张**对吧？', '张'], ['是王*明吗', '王'], ['李*…是这个名字？', '李'], ['姓张**的那个？', '张'], ['欧阳**是谁啊', '欧阳']]) {
    const out = E.vagueDigits(src);
    assert.ok(!out.includes('*') && out.includes('那个名字'), out);
    assert.ok(!out.includes(sur + '那个') && !out.includes('姓王的那个人'), out);
    assert.strictEqual(E.vagueDigits(out), out);
  }
  assert.strictEqual(E.vagueDigits('是王*明吗'), '是那个名字吗');
  assert.strictEqual(E.vagueDigits('户名是张**是吧？'), '户名是那个名字是吧？');
});

test('other masks become vague', () => {
  for (const src of ['你发的bi***tc.top', '邮箱ab***@qq.com', 'bi***t***.top']) {
    const out = E.vagueDigits(src);
    assert.ok(!out.includes('*') && !/[A-Za-z]{2}/.test(out), out);
  }
});

test('vague phrases appear at most once', () => {
  for (const src of ['嗯…卡号6222 **** **** 7890，尾号7890，验证码472是吧', '6222开头…尾号0123对吧，还有138开头…后面是零零幺三', '金额是3000块，3000块对吧，就3000块']) {
    const out = E.vagueDigits(src);
    assert.ok((out.match(/没听清/g) || []).length <= 1 && (out.match(/那几个数/g) || []).length <= 1, out);
    assert.ok(!/\d{2,}|[零一幺二两三四五六七八九]{3,}/.test(out), out);
    assert.ok(!/[，,、…]{2,}[，,、]|[，,、]{2,}/.test(out), out);
  }
});

test('web prompt carries the shared name rule', () => {
  assert.ok(PJ.nameRule.startsWith('不复述对方说的任何人名'));
  // #173：报过名字时是原句；没报过名字时去掉举的说法（“那个名字”“户名没记全”），规则本身还在
  const sp = L.systemPrompt(P.BY_ID.lin, S.BY_ID.refund, 'generic', [], ['户名是张**']);
  assert.ok(sp.includes(PJ.nameRule));
  assert.ok(L.systemPrompt(P.BY_ID.lin, S.BY_ID.refund, 'generic', []).includes('不复述对方说的任何人名'));
  assert.ok(!/〔姓/.test(sp));
});
