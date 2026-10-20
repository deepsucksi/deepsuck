'use strict';
// #216 P0：对方没报过户名时的露字（真名、星号后残名、带空格的打码姓名）。用例与 python/tests/test_unsaid_leaks.py、voice/tests/test_unsaid_leaks.py 共用
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const R = require('../site/assets/js/redact.js');
const E = require('../site/assets/js/extractors.js');
const F = require('./fixtures/unsaid_leaks.json');

test('打码：redactText 与 Python 一致（「对方叫李四」打成「对方叫李*」）', () => {
  for (const c of F.cases) assert.equal(R.redactText(c.text, E.extract(c.text)), c.redacted, c.text);
});

test('念法：speakMasked 不露字、不露星号，与 Python 一致', () => {
  for (const c of F.cases) {
    const out = L.speakMasked(c.redacted);
    assert.equal(out, c.speak, c.text);
    assert.ok(!/[*＊]/.test(out), c.text);
  }
});

test('heardRefs 与 Python 一致', () => {
  for (const c of F.cases) assert.deepEqual(Object.keys(L.heardRefs([c.redacted])).sort(), c.refs, c.text);
});

test('P0 三句：sanitizeReply 也不露真名和残字', () => {
  for (const c of F.cases.filter((x) => x.p0)) {
    const out = L.sanitizeReply(c.text);
    assert.ok(!/李四|[*＊]/.test(out) && !/[^那]个名字明|明[吗？]/.test(out), c.text + ' -> ' + out);
  }
});

test('#221 打码不过头：「叫」后面不是名字的句子原样念，不出现「那个名字」', () => {
  const cs = F.cases.filter((x) => x.notName);
  assert.ok(cs.length >= 14);
  for (const c of cs) {
    assert.equal(R.redactText(c.text, E.extract(c.text)), c.text, c.text);
    assert.equal(L.speakMasked(c.text), c.text, c.text);
    assert.ok(!/那个名字/.test(L.sanitizeReply(c.text)), c.text);
  }
});

test('#221 不丢字：星号后的动词副词、时间词保留；钱明、马丽、安华照样打码', () => {
  for (const c of F.cases.filter((x) => x.keepTail)) {
    const out = L.speakMasked(R.redactText(c.text, E.extract(c.text)));
    assert.ok(out.endsWith(c.keepTail) && !/[*＊]/.test(out), c.text + ' -> ' + out);
  }
  for (const c of F.cases.filter((x) => x.mustMask)) {
    const out = L.speakMasked(R.redactText(c.text, E.extract(c.text)));
    assert.ok(out.indexOf(c.mustMask) < 0 && /那个名字/.test(out), c.text + ' -> ' + out);
  }
});

test('#221 语音 P0：「李*那边」「收款人李*那边」不露姓，「我在*那边」照旧不当姓名', () => {
  for (const c of F.cases.filter((x) => x.voiceExpect)) {
    const out = L.speakMasked(R.redactText(c.text, E.extract(c.text)));
    assert.ok(!/[李王张刘](?:你发的)?那个/.test(out) && !/[*＊]/.test(out), c.text + ' -> ' + out);
    assert.equal(/那个名字/.test(out), /那个名字/.test(c.voiceExpect), c.text + ' -> ' + out);
  }
});
