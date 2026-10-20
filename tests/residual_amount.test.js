'use strict';
// #222 后续：打码姓名后面紧跟数字 / 金额词时不当残名。用例与 python/tests/test_residual_amount.py 共用
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/residual_amount.json');

test('残名与金额：sanitizeReply 网页出口', () => {
  for (const c of F.cases) assert.equal(L.sanitizeReply(c.text), c.reply, c.id);
});

test('残名与金额：speakMasked', () => {
  for (const c of F.cases) assert.equal(L.speakMasked(c.text), c.speak, c.id);
});
