'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const R = require('../site/assets/js/redact.js');

test('银行卡：PCI DSS，16–19 位保留前 6 后 4，中间全部打码', () => {
  assert.equal(R.maskBankCard('6222021234561234'), '622202******1234'); // 16 位
  assert.equal(R.maskBankCard('62220212345612345'), '622202*******2345'); // 17 位
  assert.equal(R.maskBankCard('622305123456789012'), '622305********9012'); // 18 位
  assert.equal(R.maskBankCard('6222 0212 3456 7890 128'), '622202*********0128'); // 19 位，带空格
  assert.equal(R.maskBankCard('6222-0212-3456-7890-128'), '622202*********0128'); // 连字符
  for (let n = 16; n <= 19; n++) {
    const d = '6222021234567890123'.slice(0, n);
    const m = R.maskBankCard(d);
    assert.equal(m.length, n);
    assert.equal(m.slice(0, 6), d.slice(0, 6));
    assert.equal(m.slice(-4), d.slice(-4));
    assert.equal(m.slice(6, -4), '*'.repeat(n - 10));
    assert.ok(!/\d{7,}/.test(m));
  }
});

test('银行卡：非标准长度更保守（8–15 位只留后 4，少于 8 位全部打码）', () => {
  assert.equal(R.maskBankCard('622202123456789'), '***********6789'); // 15 位
  assert.equal(R.maskBankCard('622202123456'), '********3456'); // 12 位
  assert.equal(R.maskBankCard('62220212'), '****0212'); // 8 位
  assert.equal(R.maskBankCard('6222021'), '*******'); // 7 位
  assert.equal(R.maskBankCard(''), '');
  for (let n = 8; n <= 15; n++) {
    const m = R.maskBankCard('6222021234567890123'.slice(0, n));
    assert.equal(m.length, n);
    assert.ok((m.match(/\*/g) || []).length >= n / 2, n + ' 位至少一半打码');
    assert.ok(!/^\d/.test(m), n + ' 位不露 BIN');
  }
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
  assert.match(out, /622202\*{9}3445/);
  assert.match(out, /139\*\*\*\*2233/);
});

test('银行卡分组展示：每 4 位一组，仅用于展示', () => {
  assert.equal(R.formatCardGroups('622202*********3445'), '6222 02** **** ***3 445');
  assert.equal(R.formatCardGroups('622202******2233'), '6222 02** **** 2233');
  assert.equal(R.formatCardGroups('622202*******1234'), '6222 02** **** *123 4');
  assert.equal(R.formatCardGroups('622202********1234'), '6222 02** **** **12 34');
  assert.equal(R.formatCardGroups('*******2001'), '**** ***2 001');
  assert.equal(R.formatCardGroups('6222 02** **** ***3 445'), '6222 02** **** ***3 445');
  assert.equal(R.formatCardGroups('王**'), '王**');
  assert.equal(R.formatCardGroups(null), '');
  assert.equal(R.mask('bank_card', '6222020200112233445'), '622202*********3445'); // 存储格式不变
});
