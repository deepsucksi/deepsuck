'use strict';
// #201 人设侧姓名替换读共用字表 site/assets/core/name_stopchars.json（不另抄一份）：
// 「有」不当姓（「我只有****块钱」不念成「我只那个名字块钱」）；「户名和账号」「收款人信息」「户名和开户行」不替成「那个名字」；
// 拿不准一律当姓名（「户名和平」「收款人姓和」「户名有志强」照样换成「那个名字」）。
// 用例：tests/fixtures/name_stopchars.json 的 personaReply，Python（python/tests/test_name_stopchars_persona.py）、语音同一组。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const X = require('../site/assets/js/extractors.js');
const E = require('../site/assets/js/engine.js');
const L = require('../site/assets/js/llm.js');
const S = require('../site/assets/core/name_stopchars.json');
const PR = require('./fixtures/name_stopchars.json').personaReply;

test('人设原话（户名和账号、收款人信息、户名和开户行、户名有了吗）：替换和发出前过滤后原样不变', () => {
  for (const t of PR.keep) {
    assert.equal(L.sanitizeReply(t), t, 'sanitizeReply ' + t);
    assert.equal(L.speakMasked(t, false), t, 'speakMasked ' + t);
    assert.equal(E.vagueDigits(t), t, 'vagueDigits ' + t);
  }
});

test('「有」不当姓：星号前的字按字表不是姓时不念成「那个名字」', () => {
  for (const c of PR.notSurname) {
    assert.equal(L.speakMasked(c.text, false), c.speak, c.text);
    assert.equal(L.sanitizeReply(c.text), c.speak, c.text);
    assert.equal(E.vagueDigits(c.text), c.vague, c.text);
  }
});

test('真名（含以「和」「姓」「有」开头的）：sanitizeReply 后换成「那个名字」，原名一个字不留', () => {
  for (const c of PR.name) {
    const out = L.sanitizeReply(c.text);
    assert.equal(out, c.reply, c.text);
    assert.ok(!out.includes(c.name) && !/[*＊]/.test(out), c.text + ' -> ' + out);
  }
});

test('上游已打码的姓名：maskNames / speakMasked / vagueDigits 都换成「那个名字」（拿不准一律当姓名）', () => {
  for (const c of PR.maskedName) {
    assert.equal(L.speakMasked(c.text, false), c.reply, 'speakMasked ' + c.text);
    assert.equal(L.sanitizeReply(c.text), c.reply, 'sanitizeReply ' + c.text);
    assert.equal(E.vagueDigits(c.text), c.reply, 'vagueDigits ' + c.text);
  }
});

test('stopSurname 直接读共用字表：surname=false 一律不当姓，surname=true 看 after，不在表里返回 null', () => {
  for (const r of S.chars) {
    if (!r.surname) assert.equal(X.stopSurname(r.char, '**'), true, r.char);
    else assert.equal(X.stopSurname(r.char, '\u0001'), false, r.char);
  }
  assert.equal(X.stopSurname('张', '**'), null);
  assert.equal(X.stopSurname('信', '息'), true);
  assert.equal(X.stopSurname('和', '账号'), true);
  assert.equal(X.stopSurname('和', '平'), false);
});

test('人设侧不另抄字表：llm.js、engine.js 走 extractors.maskedLeadNotSurname，不再只看 notSurname', () => {
  for (const f of ['llm.js', 'engine.js']) {
    const src = fs.readFileSync(path.join(__dirname, '../site/assets/js', f), 'utf8');
    assert.ok(src.includes('maskedLeadNotSurname'), f);
    assert.ok(!/notSurname\.indexOf\(sur\)/.test(src), f);
  }
});
