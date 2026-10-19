'use strict';
// #185 应答字、虚词不能当成姓：「户名对得上就行」不能记成收款户名「对得上就」，人设也就不会念「收钱的人姓对」。
// 用例：tests/fixtures/name_stopchars.json + site/assets/core/name_stopchars.json 每个字的 negatives，Python 端同一组。
const test = require('node:test');
const assert = require('node:assert/strict');
const X = require('../site/assets/js/extractors.js');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/core/name_stopchars.json');
const FX = require('./fixtures/name_stopchars.json');

const STOP = new Set(S.chars.map((r) => r.char));
const names = (t) => X.extract(t).filter((e) => e.type === 'name').map((e) => e.value);

test('共用字表每个字的反例：取不出以该字开头的姓名', () => {
  for (const r of S.chars) for (const t of r.negatives) {
    assert.ok(!names(t).some((n) => n[0] === r.char), r.char + '：' + t + ' -> ' + names(t));
  }
});

test('fixture 反例：一个姓名都不取（姓对、户名对、姓是…）', () => {
  for (const t of FX.negatives) assert.deepEqual(names(t), [], t);
});

test('fixture 正例：真名照常取到', () => {
  for (const c of FX.positives) assert.deepEqual(names(c.text), [c.name], c.text);
});

test('取到的姓名第一个字都不在字表里（正例 + 反例全部文本）', () => {
  const all = FX.negatives.concat(FX.positives.map((c) => c.text));
  for (const r of S.chars) all.push(...r.negatives);
  for (const t of all) for (const n of names(t)) assert.ok(!STOP.has(n[0]), t + ' -> ' + n);
});

test('高压档原句：会话里不记假户名（确认台词的「姓{s}」只取已记下的户名）', () => {
  const s = new E.Session({ scenario: 'pig', persona: 'lin', seed: 1000 });
  for (const t of FX.negatives) s.ingest(t);
  assert.ok(!Object.values(s.intel).some((i) => i.type === 'name'), JSON.stringify(s.intel));
});
