'use strict';
// #216：打码金额「****块钱」念量词说法、heardRefs 记 number。用例与 python/tests/test_amount_stars.py 共用
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/amount_stars.json');

test('打码金额：sanitizeReply 换成量词说法', () => {
  for (const c of F.cases) assert.equal(L.sanitizeReply(c.text), c.reply, c.id);
});

test('打码金额：heardRefs 记 number', () => {
  for (const c of F.cases) assert.deepEqual(Object.keys(L.heardRefs([c.text])).sort(), c.refs, c.id);
});
