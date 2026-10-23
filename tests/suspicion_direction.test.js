'use strict';
// #194：规则 8 起疑只写方向、不给例句。用例 tests/fixtures/suspicion_direction.json 与 voice/tests/test_suspicion_direction.py 共用。
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const F = require('./fixtures/suspicion_direction.json');

test('网页提示词：规则 8 写起疑方向，不给具体起疑例句', () => {
  for (const persona of F.personas) {
    for (const hint of F.hints) {
      const sp = L.buildMessages({ persona, scenario: 'police', hint, missing: [],
        transcript: [{ role: 'scammer', text: '你好，我是快递客服' }] })[0].content;
      for (const w of F.required) assert.ok(sp.includes(w), persona + ' / ' + hint + ' 缺：' + w);
      for (const w of F.forbidden) assert.ok(!sp.includes(w), persona + ' / ' + hint + ' 仍有：' + w);
    }
  }
});
