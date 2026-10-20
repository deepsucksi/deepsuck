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
