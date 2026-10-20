'use strict';
// #206 第六条探针（语音 P0）：已打码星号的代称种类。用例 tests/fixtures/heard_refs_p0.json，
// 与 python/tests/test_heard_refs_p0.py、voice/tests/test_heard_refs_p0.py 共用。
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const X = require('../site/assets/js/extractors.js');
const R = require('../site/assets/js/redact.js');
const F = require('./fixtures/heard_refs_p0.json');

function check(expect, refs) {
  if (expect === 'name+number') return refs.includes('name') && refs.includes('number');
  if (expect === 'number') return refs.includes('number') && !refs.includes('name');
  if (expect === 'name') return refs.includes('name');
  return !refs.includes('name');
}

test('heard_refs P0：号码语境念「那个号」，姓名照旧是名字，「我在***上班」不当名字', () => {
  assert.ok(F.cases.length >= 37);
  for (const c of F.cases) {
    if (c.xfail) { // 已知未修（见 c.xfail），确认仍是旧结果，改好了要去掉 xfail
      assert.ok(!check(c.expect, Object.keys(L.heardRefs([c.text]))), c.text + ' 已通过，请去掉 xfail');
      continue;
    }
    const refs = Object.keys(L.heardRefs([c.text]));
    assert.ok(check(c.expect, refs), c.text + ' 期望 ' + c.expect + '，实际 ' + JSON.stringify(refs));
  }
});

test('探针：「验证码是123」打码后念「那个号」，heard_refs 记 number', () => {
  for (const c of F.speak) {
    const red = R.redactText(c.text, X.extractSensitive(c.text));
    assert.equal(red, c.redacted);
    const sp = L.speakMasked(red, false);
    assert.equal(sp, c.spoken);
    assert.ok(sp.includes('那个号') && !sp.includes('那个名字'), sp);
    assert.deepEqual(Object.keys(L.heardRefs([c.text])).sort(), c.heard);
  }
});
