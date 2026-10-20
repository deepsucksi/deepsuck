'use strict';
// #220：名字后面紧跟数字 / 金额词时金额不被吃掉。用例与 python/tests/test_name_amount.py 共用
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/name_amount.json');

test('名字 + 金额：sanitizeReply', () => {
  for (const c of F.cases) {
    const out = L.sanitizeReply(c.text);
    assert.equal(out, c.reply, c.id);
    if (c.refs.includes('name')) assert.ok(!/[李张王]/.test(out), c.id + ' 姓不出现');
  }
});

test('名字 + 金额：heardRefs', () => {
  for (const c of F.cases) assert.deepEqual(Object.keys(L.heardRefs([c.text])).sort(), c.refs, c.id);
});
