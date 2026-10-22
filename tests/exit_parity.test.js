'use strict';
// #163 复审：同一句话 web（llm.js sanitizeReply）、refs（python）、语音（voice）三个出口读法一致、不露姓不露名。
// 夹具 redact.json 的 exitParity 由 scripts/gen-fixtures.js 用 sanitizeReply 生成，python/tests/test_exit_parity.py 与 voice/tests/test_exit_parity.py 逐项比对
const test = require('node:test');
const assert = require('node:assert');
const LLM = require('../site/assets/js/llm.js');
const FX = require('./fixtures/redact.json').exitParity;

test('#163 exitParity：web 出口与夹具一致，打码的不露姓名、没有星号，反例原样', () => {
  assert.ok(FX.filter((c) => c.expect === 'mask').length >= 15 && FX.filter((c) => c.expect === 'keep').length >= 6);
  for (const c of FX) {
    const out = LLM.sanitizeReply(c.text);
    assert.strictEqual(out, c.expected, c.text); // web 是金标准，same=false 的也逐字一致
    if (!c.same) assert.ok(out.includes('那个名字'), c.text + ' -> ' + out);
    if (c.expect === 'keep') assert.strictEqual(out, c.text);
    else assert.ok(!new RegExp('[' + c.leak + '*＊]').test(out), c.text + ' -> ' + out);
  }
});
