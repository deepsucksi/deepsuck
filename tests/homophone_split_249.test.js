'use strict';
// #249：同音 / ASR 拆字写法 + 名 + 数字按姓名打码，普通词走 nameRules.split.numWhitelist；夹具与 python/tests/test_homophone_split_249.py 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const FX = require('./fixtures/homophone_split_249.json').cases;

test('夹具逐项与 Python 一致，打码 / 放行两类都有', () => {
  assert.ok(FX.some((c) => c.expect === 'mask') && FX.some((c) => c.expect === 'keep'));
  FX.forEach((c) => {
    const out = R.redactText(c.text, X.extractSensitive(c.text));
    assert.strictEqual(out, c.redacted, c.text);
    assert.strictEqual(out !== c.text, c.expect === 'mask', c.text);
  });
});

test('语料组 3 句：工厂张三五百块打码（三归名字），工厂张贴 / 工厂张家港放行', () => {
  const red = (t) => R.redactText(t, X.extractSensitive(t));
  assert.strictEqual(red('工厂张三五百块转给我'), '工厂张*五百块转给我');
  assert.strictEqual(red('工厂张贴通知三份'), '工厂张贴通知三份');
  assert.strictEqual(red('工厂张家港二厂明天停工'), '工厂张家港二厂明天停工');
});

test('文字出口 nameSayRegions：同音写法 + 名 + 数字整段读成「那个名字」，白名单不动', () => {
  const say = (t) => R.sayNames ? R.sayNames(t, X.extractSensitive(t)) : null;
  if (!R.sayNames) return;
  assert.strictEqual(say('尔东陈伟明500'), '那个名字500');
  assert.strictEqual(say('我在尔东陈列馆2楼等你'), '我在尔东陈列馆2楼等你');
});
