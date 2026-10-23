'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const FX = require('./fixtures/redact.json');
const { extract } = require('../site/assets/js/extractors.js');
const { sayNames, redactText } = require('../site/assets/js/redact.js');

/** 与 voice.callredact.redact_line 同序：sayNames 循环再 redactText。 */
function redactLine(text) {
  let t = String(text || '');
  for (let i = 0; i < 8; i++) {
    const nt = sayNames(t, extract(t));
    if (nt === t) break;
    t = nt;
  }
  return redactText(t, extract(t));
}

const IDEM = [
  'http://192.168.1.10:8080/admin 登录',
  '弓长张伟大的',
  '户名是弓长张三丰',
  '户名木子李四',
  '户名耳东陈立',
  '收款人叫有名的名对吧',
  '收款人叫李四',
  '收款人叫李强找没听清',
  '收款人叫王建国',
  '收款人姓张伟',
  '耳东陈，立刻转',
  '耳东陈，耳朵的耳东边的东',
  '耳东陈耳朵的耳东边的东',
  '耳东陈，东方的东',
  '户名是张*。',
  '收款人叫李*',
  '户名是弓长张**',
];

for (const text of IDEM) {
  test('#260 idempotent: ' + text, () => {
    const once = redactLine(text);
    assert.equal(redactLine(once), once);
  });
}

test('#265 charExplain[15] no 耳*', () => {
  const t = FX.charExplain[15].text;
  const out = redactLine(t);
  assert.equal(redactLine(out), out);
  assert.ok(!out.includes('耳*'));
  assert.ok(!out.includes('耳东'));
  assert.ok(!out.includes('陈'));
  assert.ok(out.includes('那个名字'));
});

test('#265 split explain whole phrase', () => {
  for (const text of ['耳东陈，耳朵的耳东边的东', '耳东陈耳朵的耳东边的东']) {
    const out = redactLine(text);
    assert.equal(out, '那个名字');
    assert.equal(redactLine(out), out);
  }
});
