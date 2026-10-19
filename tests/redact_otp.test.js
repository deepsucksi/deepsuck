'use strict';
// 验证码按上下文打码（#33）：规则在 site/assets/core/extractors.json 的 redact.otp，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const FX = require('./fixtures/redact.json').otp;

const red = (t) => R.redactText(t, X.extractSensitive(t));
const digits = (s) => (s.match(/[0-9零〇一二三四五六七八九幺两]/g) || []).join('');

test('验证码：常见写法都打码（空格、…、⋯、...、中文数字逐位、跨短句、关键词在后）', () => {
  assert.strictEqual(red('您的验证码是472915，请勿告诉他人'), '您的验证码是******，请勿告诉他人');
  assert.strictEqual(red('验证码是 4 7 2 9 1 5'), '验证码是 * * * * * *');
  assert.strictEqual(red('动态码 472...915'), '动态码 ***...***');
  assert.strictEqual(red('校验码⋯四七二⋯九一五'), '校验码⋯***⋯***');
  assert.strictEqual(red('验证码收到了。是…472915'), '验证码收到了。是…******');
  assert.strictEqual(red('472915是验证码吧？'), '******是验证码吧？');
  assert.strictEqual(red('短信码是 4 7 2，9 1 5'), '短信码是 * * *，* * *');
  assert.strictEqual(red('OTP: 4729'), 'OTP: ****');
});

test('验证码：负例不打码（尾号、金额、单位、订单号、无关数字）', () => {
  for (const t of ['472 915', '验证码已发送至尾号1234的手机', '验证码10分钟内有效', '验证码收到了，转了5000元', '金额是5000，验证码还没来',
    '验证码？订单号A47291', '我家门牌号 2046，下午三点到', '验证码是4位的，卡号后四位是8888']) {
    assert.strictEqual(red(t), t, t);
  }
  // #120：半截 3 位也算验证码
  assert.strictEqual(red('验证码是多少？我念一下：一二三'), '验证码是多少？我念一下：***');
  assert.strictEqual(red('嗯…验证码是472？'), '嗯…验证码是***？');
});

test('验证码：手机号、卡号仍走各自的实体打码，不被当成验证码', () => {
  assert.strictEqual(red('验证码发到13800001111了'), '验证码发到138****1111了');
  assert.strictEqual(red('卡号6222020200112233445，验证码等会给你'), '卡号622202*********3445，验证码等会给你');
  assert.deepStrictEqual(R.findOtpSpans('验证码发到 138 0000 1111 了'), []);
});

test('验证码：没有实体时 redactText 也会打码；打码后不留原数字', () => {
  assert.strictEqual(R.redactText('验证码 472915', []), '验证码 ******');
  assert.strictEqual(R.redactText('验证码 472915'), '验证码 ******');
  for (const c of FX) if (c.expect === 'mask') for (const sp of c.spans) assert.strictEqual(digits(sp.masked), '', c.text);
});

test('验证码：与夹具一致（gen-fixtures 生成，pytest 共用）', () => {
  assert.ok(FX.length >= 30);
  for (const c of FX) {
    assert.deepStrictEqual(R.findOtpSpans(c.text), c.spans, c.text);
    assert.strictEqual(red(c.text), c.redacted, c.text);
  }
});
