'use strict';
// #167：人设说出口的话不带两位及以上数字（线上探针 XXMX5LPV 说出「好像是62开头的」）。
// 用例在 tests/fixtures/digit_cap.json，与 python/tests/test_digit_cap.py 共用，两端逐字一致。
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const F = require('./fixtures/digit_cap.json');

const DIGIT = '0-9０-９零〇一幺二两三四五六七八九';
const PAIR = new RegExp('[' + DIGIT + '](?:[\\s、,，\\-－—·*＊]{0,2}[' + DIGIT + '])+', 'g');
// 汉字约数（两三天、一二十分钟）和 TRC20 这类写法不是号码
const pairs = (t) => (String(t).replace(/TRC20|ERC20|BEP20/g, '').match(PAIR) || []).filter((m) => !/^(?:一两|一二|两三|二三|三四|四五|五六|六七|七八|八九)$/.test(m));

test('夹具：正例过滤后只剩最多一位，结果与夹具逐字一致', () => {
  assert.ok(F.positive.length >= 3 && F.negative.length >= 2);
  for (const k of ['好像是62开头的', '六二开头', '前两位是6、2']) assert.ok(F.positive.some((x) => x.in === k), k);
  for (const x of F.positive) {
    const out = E.vagueDigits(x.in);
    assert.equal(out, x.out, x.in);
    assert.deepEqual(pairs(out), [], x.in + ' → ' + out);
    assert.ok(!/好像是好像是|像是像是/.test(out), out);
  }
});

test('夹具：反例原样不变', () => {
  for (const k of ['好像是6开头的']) assert.ok(F.negative.includes(k), k);
  for (const t of F.negative) assert.equal(E.vagueDigits(t), t);
});

test('台词库里没有两个数字挨着的句子（#198 小林三句已换）', () => {
  const core = require('../site/assets/core/personas.json');
  const bad = [];
  for (const p of core.personas) for (const [k, v] of Object.entries(p.templates || {})) v.forEach((x, i) => {
    const t = typeof x === 'string' ? x : (x.t || '');
    if (pairs(t).length) bad.push([p.id, k, i, t]);
  });
  assert.deepEqual(bad, []);
  const lin = core.personas.find((p) => p.id === 'lin').templates;
  for (const t of [lin.otp_stall[12], lin.loan_stall[5], lin.coop_step[7].t]) {
    assert.ok(F.negative.includes(t), t);
    assert.equal(E.vagueDigits(t), t);
  }
});

test('recordBot：两位数字的回复也过滤', () => {
  const s = new E.Session({ scenario: 'police', persona: 'wang', rng: () => 0.3, now: () => 0 });
  for (const x of F.positive) assert.deepEqual(pairs(s.recordBot(x.in, 'coop_step').text), [], x.in);
});
