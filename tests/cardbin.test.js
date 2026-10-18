'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const CB = require('../site/assets/js/cardbin.js');
const X = require('../site/assets/js/extractors.js');
const C = require('../site/assets/core/cardbin.json');
const { build, render } = require('../scripts/fetch-cardbin.js');

test('cardbin.json：来源、许可证与结构', () => {
  assert.equal(C.schema, 'deepsuck.core.cardbin/v1');
  assert.equal(C.source.license, 'MIT');
  assert.match(C.source.homepage, /github\.com\/hexindai\/bcbc/);
  assert.ok(CB.size > 1500);
  for (const [bin, opts] of Object.entries(C.bins)) {
    assert.match(bin, /^\d{3,10}$/);
    for (const [bank, type, len] of opts) { assert.ok(C.banks[bank], bank); assert.ok(C.types[type], type); assert.ok(len >= 12 && len <= 19); }
  }
});

test('lookup：最长前缀 + 长度优先', () => {
  assert.equal(CB.lookup('6222020200112233445').bank, '中国工商银行');
  assert.equal(CB.lookup('6222 0202 0011 2233 445').cardTypeName, '借记卡');
  // 同一前缀 622305：16 位 → 南京银行，18 位 → 工商银行
  assert.equal(CB.lookup('6223051234567890').bankCode, 'NJCB');
  assert.equal(CB.lookup('622305123456789012').bankCode, 'ICBC');
  assert.equal(CB.lookup('1234567890123456'), null);
  assert.equal(CB.lookup('62220212'), null); // 太短，不当作卡号
});

test('提取器：银行卡 meta.issuer 来自 BIN，且不含 BIN 数字', () => {
  const e = X.extract('卡号6222020200112233445').find((x) => x.type === 'bank_card');
  assert.equal(e.meta.issuer.bank, '中国工商银行');
  assert.equal(e.meta.bank, '中国工商银行');
  assert.equal(e.meta.bankFrom, 'bin');
  assert.ok(!JSON.stringify(e.meta).includes('622202'));
  const f = X.extract('收款人是张伟，开户行招商银行 6225 8812 3456 7891').find((x) => x.type === 'bank_card');
  assert.equal(f.meta.bank, '招商银行');
  assert.equal(f.meta.bankFrom, undefined); // 上下文里的开户行优先
});

test('fetch-cardbin build()：清洗与同前缀多条', () => {
  const d = build('bin,bank,type,length\n622305,NJCB,DC,16\n622305,ICBC,DC,18\nabc,ICBC,DC,16\n622202,NOPE,DC,19\n', 'bank,name\nNJCB,南京银行\nICBC,中国工商银行\n');
  assert.deepEqual(d.bins, { 622305: [['NJCB', 'DC', 16], ['ICBC', 'DC', 18]] });
  assert.ok(render(d).endsWith('}\n'));
});

test('cardbin.json 由 scripts/fetch-cardbin.js 的 render() 生成（未被手改）', () => {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'site', 'assets', 'core', 'cardbin.json'), 'utf8'));
  assert.equal(fs.readFileSync(path.join(__dirname, '..', 'site', 'assets', 'core', 'cardbin.json'), 'utf8'), render(data));
});
