'use strict';
// 提取器修复回归（intel/extractor-fixes），与 python/tests/test_extractor_fixes.py 同一组断言。
// 表情写法的坐标 JS（UTF-16）与 Python（码点）不同，所以不进共享夹具，只断言类型和值。
const test = require('node:test');
const assert = require('node:assert/strict');
const X = require('../site/assets/js/extractors.js');
const E = require('../site/assets/js/engine.js');

const got = (t) => new Set(X.extract(t).map((e) => e.type + '|' + String(e.value).replace(/\s/g, '')));
const hasType = (t, type) => X.extract(t).some((e) => e.type === type);

test('关键词内夹空格 / 标点 / 表情', () => {
  for (const t of ['加微 信 wgold_3487', '加微，信 wgold_3487', '加微😀信 wgold_3487', '加微🙏🙏信：kefu_tb2026', '微信号码事 wgold_3487']) {
    assert.ok(got(t).has('channel|微信'), t);
    assert.ok(hasType(t, 'wechat'), t);
  }
});

test('关键词间隔不误报', () => {
  assert.equal(got('稍微，信息我晚点发').size, 0);
  assert.ok(!got('我很信任，微，信任何人都行').has('channel|微信'));
});

test('#1 16 位片段不当整卡', () => {
  const r = X.stitch(['卡号是 6221887154833655', '995，户名王某某']);
  assert.deepEqual(r.map((x) => [x.type, x.value]), [['bank_card', '6221887154833655995']]);
  assert.equal(r[0].supersedes[0].value, '6221887154833655');
  const s = new E.Session({ scenario: 'refund', persona: 'wang', rng: () => 0.5 });
  for (const t of ['卡号是 6221887154833655', '995，户名王某某']) s.ingest(t);
  assert.deepEqual(Object.keys(s.intel).filter((k) => k.startsWith('bank_card|')), ['bank_card|6221887154833655995']);
  assert.deepEqual(X.stitch(['卡号 6222 0202 0011 2233', '445 元']), []);
});

test('#2 中文数字后的量词不并入号码', () => {
  assert.deepEqual([...got('电话一三九零零一一二二三三两小时后再打')], ['phone|13900112233']);
  assert.ok(got('电话一三九零零一一二二三三三小时后').has('phone|13900112233'));
  assert.ok(got('卡号六二二二零二零二零零一一二二三三四四五两张卡').has('bank_card|6222020200112233445'));
  assert.equal(got('买两张票').size, 0);
});

test('手写错字的屏蔽词', () => {
  assert.deepEqual(X.stitch(['房问号 199', '0069 7308 是同事的工好']), []);
  assert.deepEqual(X.stitch(['工好 151', '0859 5928']), []);
});

test('数字之间的表情', () => {
  assert.ok(got('卡号六二二二🌹🌹零二零二🌹零零一一二二三三四四五').has('bank_card|6222020200112233445'));
  assert.ok(got('电话 一三九😊零零一一😊二二三三').has('phone|13900112233'));
  assert.equal(got('我今年😊六十😊八岁').size, 0);
});

test('逐字报数跨换行', () => {
  assert.ok(got('电化，幺，八\n六，幺，七，九，五，四，三，八，六').has('phone|18617954386'));
});

test('姓名边界与句中姓名', () => {
  assert.ok(got('户名周杰农业银行').has('name|周杰'));
  assert.ok(got('户名周杰然后民生银航').has('name|周杰'));
  assert.ok(got('收款人叫李强找没听清').has('name|李强'));
  assert.ok(got('收款人是我们公司财务李强，卡号6222020200112233445').has('name|李强'));
  assert.ok(got('钱转到李强的账户上就行').has('name|李强'));
  assert.ok(!hasType('转到王经理的卡上', 'name'));
});

test('EX-0013 备注不是姓名', () => {
  assert.ok(!hasType('【示例数据】收款户名只保留姓氏。', 'name'));
  assert.ok(!hasType('收款人是我的朋友', 'name'));
});
