'use strict';
// #222 P0：姓名语境里的真名抽成 name 并打码。用例与 python/tests/test_name_context.py 共用
const test = require('node:test');
const assert = require('node:assert/strict');
const X = require('../site/assets/js/extractors.js');
const R = require('../site/assets/js/redact.js');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/name_context.json');

test('姓名语境：extractSensitive 抽到的姓名', () => {
  for (const c of F.cases) assert.deepEqual(X.extractSensitive(c.text).filter((e) => e.type === 'name').map((e) => e.value), c.names, c.id);
});

test('姓名语境：redactText 打码', () => {
  for (const c of F.cases) assert.equal(R.redactText(c.text, X.extractSensitive(c.text)), c.redacted, c.id);
});

test('姓名语境：sanitizeReply 网页出口', () => {
  for (const c of F.cases) assert.equal(L.sanitizeReply(c.text), c.reply, c.id);
});

test('姓名语境：findNameContext 只跑语境规则', () => {
  assert.deepEqual(X.findNameContext('我叫张三，转给李四').map((e) => [e.value, e.start, e.lead]), [['张三', 2, '我叫'], ['李四', 7, '转给']]);
  assert.deepEqual(X.findNameContext('我是王阿姨，是王牌吗'), []);
});
