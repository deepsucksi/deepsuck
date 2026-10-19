'use strict';
// 跨 ASR 分段的验证码打码（#92）：规则在 site/assets/core/extractors.json 的 redact.otp.seg*，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const E = require('../site/assets/js/engine.js');
const FX = require('./fixtures/redact.json').otpSegments;

const each = (segs) => segs.map((t) => R.redactText(t, X.extractSensitive(t)));
const DIGIT = /[0-9０-９零〇一二三四五六七八九幺两]/;

test('跨分段验证码：与夹具一致（gen-fixtures 生成，pytest 共用），可重复执行', () => {
  assert.ok(FX.length >= 20);
  for (const c of FX) {
    const e = each(c.segments);
    assert.deepStrictEqual(R.findOtpSpansSegments(e), c.spans, c.segments.join(' | '));
    assert.deepStrictEqual(R.redactOtpSegments(e), c.redacted, c.segments.join(' | '));
    assert.strictEqual(JSON.stringify(R.redactOtpSegments(e)) !== JSON.stringify(e), c.expect === 'mask', c.segments.join(' | '));
    assert.deepStrictEqual(R.redactOtpSegments(c.redacted), c.redacted);
    if (c.expect === 'mask') for (const sps of c.spans) for (const sp of sps) assert.ok(!DIGIT.test(sp.masked));
  }
  assert.ok(FX.some((c) => c.expect === 'mask' && c.segments.length === 2));
  assert.ok(FX.some((c) => c.expect === 'mask' && c.segments.length === 3));
  assert.ok(FX.filter((c) => c.expect === 'keep').length >= 8);
});

test('跨分段验证码：两段、三段、中文数字、标点；金额时间不打码', () => {
  assert.deepStrictEqual(R.redactOtpSegments(['验证码是 38', '27 15']), ['验证码是 **', '** **']);
  assert.deepStrictEqual(R.redactOtpSegments(['验证码是 38。', '27，', '15']), ['验证码是 **。', '**，', '**']);
  assert.deepStrictEqual(R.redactOtpSegments(['校验码是三八', '二七', '一五']), ['校验码是**', '**', '**']);
  assert.deepStrictEqual(R.redactOtpSegments(['验证码收到了吧', '那你先转 3000 元']), ['验证码收到了吧', '那你先转 3000 元']);
  assert.deepStrictEqual(R.redactOtpSegments(['验证码已发送', '下午 3 点', '15 分到']), ['验证码已发送', '下午 3 点', '15 分到']);
  assert.deepStrictEqual(R.redactOtpSegments([]), []);
  assert.deepStrictEqual(R.redactOtpSegments(['验证码 472915']), ['验证码 ******']);
  assert.deepStrictEqual(R.redactOtpSegments([null, '验证码 38', '2715']), ['', '验证码 **', '****']);
});

test('跨分段验证码：窗口为前后 2 段', () => {
  assert.strictEqual(R.otpSegWindow(), 2);
  const far = ['验证码是', '嗯', '嗯', '嗯', '嗯', '嗯', '38 27 15'];
  assert.deepStrictEqual(R.redactOtpSegments(far), far);
  assert.deepStrictEqual(R.redactOtpSegments(['验证码是 38', '嗯', '27 15'], 0), ['验证码是 38', '嗯', '27 15']);
});

test('跨分段验证码：Session.ingest 回头给前一段补打码，金额不误伤', () => {
  const s = new E.Session({ scenario: 'refund', persona: 'lin', rng: () => 0, now: () => 0 });
  assert.strictEqual(s.ingest('验证码是 38').redacted, '验证码是 38');
  s.recordBot('嗯你慢点说', 'generic'); // 中间夹着人设的话，仍按对方自己的连续分段判断
  assert.strictEqual(s.ingest('27 15').redacted, '** **');
  assert.deepStrictEqual(s.messages.filter((m) => m.role === 'scammer').map((m) => m.text), ['验证码是 **', '** **']);
  const t = new E.Session({ scenario: 'refund', persona: 'lin', rng: () => 0, now: () => 0 });
  t.ingest('验证码收到了吧');
  assert.strictEqual(t.ingest('那你先转 3000 元').redacted, '那你先转 3000 元');
});
