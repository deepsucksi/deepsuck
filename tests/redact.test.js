'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const R = require('../site/assets/js/redact.js');

test('银行卡：保留前 4 后 4', () => {
  assert.equal(R.maskBankCard('6222021234561234'), '6222 **** **** 1234');
  assert.equal(R.maskBankCard('6222 0212 3456 7890 128'), '6222 **** **** 0128');
});

test('手机号：138****5678，兼容 +86 与分隔符', () => {
  assert.equal(R.maskPhone('13812345678'), '138****5678');
  assert.equal(R.maskPhone('+86 138-1234-5678'), '138****5678');
  assert.equal(R.maskPhone('400-820-1234'), '400-***-1234');
});

test('加密地址：0x12ab...9f3e', () => {
  assert.equal(R.maskCrypto('0x12ab34cd56ef7890abcdef1234567890abcd9f3e'), '0x12ab...9f3e');
  assert.equal(R.maskCrypto('TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'), 'TQ7x...BcDe');
});

test('URL：隐藏路径、主机名中段打码', () => {
  assert.equal(R.maskUrl('https://refund-taobao-kefu.top/app/download?id=9'), 'https://re***fu.top/***');
  assert.equal(R.maskUrl('www.goldwin-vip.top'), 'www.go***ip.top');
  assert.ok(!R.maskUrl('http://gaj-sh-gov.cc/case/8872').includes('8872'));
});

test('其他：QQ / 微信 / 身份证 / 姓名 / 邮箱', () => {
  assert.equal(R.maskQQ('2876543210'), '28******10');
  assert.equal(R.maskIdCard('110101199001011234'), '110101********1234');
  assert.equal(R.maskName('王建国'), '王**');
  assert.equal(R.maskEmail('abc.def@163.com'), 'ab***@163.com');
  assert.ok(!R.maskHandle('kefu_tb2026').includes('tb20'));
});

test('redactText：替换文本中的所有敏感片段', () => {
  const X = require('../site/assets/js/extractors.js');
  const t = '转到 6222020200112233445 户名王建国，电话 13900112233';
  const out = R.redactText(t, X.extract(t));
  assert.ok(!/6222020200112233445|13900112233|王建国/.test(out), out);
  assert.match(out, /6222 \*\*\*\* \*\*\*\* 3445/);
  assert.match(out, /139\*\*\*\*2233/);
});
