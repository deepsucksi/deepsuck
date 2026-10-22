'use strict';
// #194：人设回复压短（提示词长度规则）。用例 tests/fixtures/reply_length.json 与 voice/tests/test_reply_length.py 共用。
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/reply_length.json');

test('网页提示词：四个人设都写短回复上限，保留口癖说明，不再有旧的长回复说法', () => {
  for (const persona of F.personas) {
    for (const hint of F.hints) {
      const sp = L.buildMessages({ persona, scenario: 'police', hint, missing: [],
        transcript: [{ role: 'scammer', text: '你好，我是快递客服' }] })[0].content;
      for (const w of F.web.required) assert.ok(sp.includes(w), persona + ' / ' + hint + ' 缺：' + w);
      for (const w of F.forbidden) assert.ok(!sp.includes(w), persona + ' / ' + hint + ' 仍有：' + w);
      assert.ok(sp.includes(F.maxChars + ' 字'), persona);
    }
  }
});
