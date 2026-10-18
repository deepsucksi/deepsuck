'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const X = require('../site/assets/js/extractors.js');

const types = (t) => X.extractSensitive(t).map((e) => e.type);
const one = (t, type) => X.extractSensitive(t).find((e) => e.type === type);

test('银行卡：16–19 位，带空格/连字符，附开户行与 Luhn', () => {
  const e = one('把钱转到 6217 0012 3456 7890 123，户名李强，建设银行', 'bank_card');
  assert.ok(e);
  assert.equal(e.masked, '621700*********0123');
  assert.equal(e.meta.bank, '建设银行');
  assert.equal(e.meta.digits, 19);
  assert.equal(X.luhn('4111111111111111'), true);
  assert.equal(X.luhn('4111111111111112'), false);
});

test('手机号 / 400 热线 / 座机，不误伤银行卡', () => {
  assert.deepEqual(types('打我 139-0011-2233 或 400-820-1234 或 021-61234567'), ['phone', 'phone', 'phone']);
  assert.deepEqual(types('卡号6222020200112233445'), ['bank_card']);
});

test('QQ / 微信 / 支付宝 需要上下文', () => {
  assert.equal(one('我的 QQ 是 2876543210', 'qq').masked, '28******10');
  assert.ok(one('加我微信 kefu_tb2026', 'wechat'));
  assert.equal(one('支付宝账号：abc.def@163.com', 'alipay').masked, 'ab***@163.com');
  assert.equal(one('支付宝 13912345678', 'alipay').masked, '139****5678');
  assert.equal(one('单纯的数字 2876543210', 'qq'), undefined);
});

test('BTC / ETH / TRON 地址', () => {
  assert.ok(one('ERC20：0x12ab34cd56ef7890abcdef1234567890abcd9f3e', 'crypto_eth'));
  assert.ok(one('TRC20 地址：TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe', 'crypto_tron'));
  assert.ok(one('BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa', 'crypto_btc'));
  assert.ok(one('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq', 'crypto_btc'));
});

test('URL：完整链接、www 与裸域名，邮箱不算 URL', () => {
  assert.equal(one('网址 https://refund-tb-kefu.top/dl ，下载', 'url').value, 'https://refund-tb-kefu.top/dl');
  assert.ok(one('平台 www.goldwin-vip.top 注册', 'url'));
  assert.ok(one('登录 kefu-jd.vip 查看', 'url'));
  assert.deepEqual(types('邮箱 abc@163.com'), ['email']);
});

test('身份证：带上下文时识别为 id_card', () => {
  assert.equal(one('身份证号110101199001011234', 'id_card').masked, '110101********1234');
});

test('收款户名', () => {
  assert.equal(one('户名：王建国，工商银行', 'name').masked, '王**');
});

test('非敏感上下文：金额 / APP 名 / 渠道', () => {
  const all = X.extract('下载“安心退”APP，先交 2000 元保证金，用支付宝或 USDT');
  const by = (t) => all.filter((e) => e.type === t).map((e) => e.value);
  assert.deepEqual(by('app_name'), ['安心退']);
  assert.deepEqual(by('amount'), ['2000 元']);
  assert.ok(by('channel').includes('支付宝') && by('channel').includes('USDT'));
});

test('所有样例台词中的敏感信息都已脱敏（masked 不含原文）', () => {
  const S = require('../site/assets/js/scenarios.js');
  for (const sc of S.SCENARIOS) for (const line of sc.samples) {
    for (const e of X.extractSensitive(line)) {
      assert.notEqual(e.masked, e.value, `${e.type} 未脱敏: ${e.value}`);
    }
  }
});

test('已打码的情报不会被二次提取/打码（机器人复述时）', () => {
  assert.deepEqual(types('收到，网址/域名 bi***tc.top，银行卡 6222 **** **** 3445'), []);
  assert.deepEqual(types('收到，银行卡 622202*********3445，户名王**'), []);
});

test('收款户名：去掉"写/填"等动词与句尾语气词', () => {
  assert.equal(one('户名写钱伟就行', 'name').value, '钱伟');
  assert.equal(one('收款人是吴刚吧', 'name').value, '吴刚');
});
