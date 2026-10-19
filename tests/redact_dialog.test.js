'use strict';
// 两边说话人、卡号片段、人设侧兜底（#120）：规则在 site/assets/core/extractors.json 的 redact.card / redact.persona，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const FX = require('./fixtures/redact.json').dialog;

const each = (segs) => segs.map((t) => R.redactText(t, X.extractSensitive(t)));

test('两边说话人：与夹具一致（gen-fixtures 生成，pytest 共用），可重复执行', () => {
  assert.ok(FX.filter((c) => c.expect === 'mask').length >= 8);
  assert.ok(FX.filter((c) => c.expect === 'keep').length >= 6);
  for (const c of FX) {
    const out = R.redactDialogSegments(each(c.segments), c.roles);
    assert.deepStrictEqual(out, c.redacted, c.segments.join(' | '));
    assert.strictEqual(JSON.stringify(out) !== JSON.stringify(c.segments), c.expect === 'mask', c.segments.join(' | '));
    assert.deepStrictEqual(R.redactDialogSegments(out, c.roles), out);
  }
});

test('探针三句回归', () => {
  assert.deepStrictEqual(R.redactDialogSegments(['嗯…验证码是472？'], ['bot']), ['嗯…验证码是***？']);
  assert.deepStrictEqual(R.redactDialogSegments(['6222开头…尾号0123对吧'], ['bot']), ['****开头…尾号****对吧']);
  assert.deepStrictEqual(R.redactDialogSegments(['138开头…后面是零零幺三'], ['bot']), ['***开头…后面是****']);
});

test('骗子侧：手机号前缀、手机尾号照留，卡号片段打码', () => {
  assert.deepStrictEqual(R.redactDialogSegments(['138开头…后面是零零幺三'], ['scammer']), ['138开头…后面是零零幺三']);
  assert.deepStrictEqual(R.redactDialogSegments(['你手机尾号0123是吧'], ['scammer']), ['你手机尾号0123是吧']);
  assert.deepStrictEqual(R.findCardSpans('400开头的电话'), []);
  assert.deepStrictEqual(R.findCardSpans('银行卡客服 400 开头'), []);
  assert.deepStrictEqual(R.findCardSpans('银行卡 955 开头').map((s) => s.masked), ['***']);
  assert.deepStrictEqual(R.redactCardSegments(['你那张卡', '尾号多少', '尾号 0123']), ['你那张卡', '尾号多少', '尾号 ****']);
});

test('人设侧兜底：金额 1000 也打，五百块、三点半、10:30 不打', () => {
  assert.strictEqual(R.redactPersona('我只有1000块'), '我只有****块');
  assert.strictEqual(R.redactPersona('我只有五百块，下午三点半到'), '我只有五百块，下午三点半到');
  assert.strictEqual(R.redactPersona('10:30 到，就 20 块钱'), '10:30 到，就 20 块钱');
  assert.strictEqual(R.redactPersona('幺三八'), '***');
  assert.strictEqual(R.redactPersona(null), '');
});
