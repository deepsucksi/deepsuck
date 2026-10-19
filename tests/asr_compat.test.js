// #157：ASR 换 qwen-audio-3.1-asr-flash-streaming 前的人设侧核对用例（与 python/tests/test_asr_compat.py 对应）。
// 原文取自 deepsuck-handoff/qwen-asr 两个模型的识别结果：拆字报姓的打码姓名不能被当成号码，也不能留下拆字说法。
const test = require('node:test');
const assert = require('node:assert');
const E = require('../site/assets/js/engine.js');
const L = require('../site/assets/js/llm.js');
const X = require('../site/assets/js/extractors.js');
const R = require('../site/assets/js/redact.js');

const RAW = ['户名写耳东陈陈晓燕，晓是知晓的晓，燕子的燕。', '户名写耳东陈陈晓燕晓是知晓的晓，燕子的燕。'];
const redact = (t) => R.redactText(t, X.extract(t));

test('split-spelled masked name becomes 那个名字 in vagueDigits', () => {
  for (const raw of RAW) {
    const out = E.vagueDigits(redact(raw));
    assert.ok(out.startsWith('户名写那个名字'), out);
    assert.ok(!/耳东|号|\*/.test(out), out);
    assert.strictEqual(E.vagueDigits(out), out);
  }
  assert.strictEqual(E.vagueDigits('户名写耳东那个名字，晓是'), '户名写那个名字，晓是');
  assert.strictEqual(E.vagueDigits('弓长张**对吧'), '那个名字对吧');
});

test('llm.js does not re-mask a masked name into a number', () => {
  for (const raw of RAW) {
    const red = redact(raw);
    const m = L.buildMessages({ persona: 'wang', scenario: 'refund', hint: 'generic', missing: [], transcript: [{ role: 'scammer', text: red }] });
    const user = m[m.length - 1].content;
    assert.ok(user.includes('户名写〔那个名字〕'), user);
    assert.ok(!/耳东|耳〔|那个号/.test(user), user);
    const out = L.sanitizeReply(red);
    assert.ok(out.startsWith('户名写那个名字') && !/耳|号|\*/.test(out), out);
  }
});

test('qwen transcripts keep scenes and redaction identical to paraformer', () => {
  const pairs = [['户名写耳东陈陈晓燕，晓是知晓的晓，燕子的燕。', '户名写耳东陈陈晓燕晓是知晓的晓，燕子的燕。'],
    ['收款人叫张伟明，弓长张，伟大的伟，明天的明。', '收款人叫张伟明，弓长张，伟大的伟，明天的明。']];
  for (const [q, p] of pairs) {
    assert.strictEqual(E.vagueDigits(redact(q)).replace(/[，。]/g, ''), E.vagueDigits(redact(p)).replace(/[，。]/g, ''));
  }
});
