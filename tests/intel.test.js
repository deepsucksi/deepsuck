'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const I = require('../site/assets/js/intel.js');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/js/scenarios.js');

const lib = JSON.parse(fs.readFileSync(path.join(__dirname, '../site/data/intel.json'), 'utf8'));

test('情报库：intel.json 通过校验，且当前全部为示例数据', () => {
  assert.deepEqual(I.validateLibrary(lib), []);
  assert.ok(lib.entries.length >= 10);
  for (const e of lib.entries) {
    assert.equal(e.example, true, e.id);
    assert.match(e.id, /^EX-\d{4}$/);
    assert.match(e.notes, /示例数据/, e.id + ' notes 应标注示例数据');
  }
  const types = new Set(lib.entries.map((e) => e.type));
  for (const t of ['phone', 'crypto_wallet', 'url', 'app', 'script', 'bank_card', 'name']) assert.ok(types.has(t), t);
});

test('示例数据使用不可能真实存在的值', () => {
  for (const e of lib.entries) {
    if (e.type === 'phone') assert.match(e.value, /^100\d{8}$/, '示例电话须使用不可分配的 100 号段');
    if (e.type === 'url') assert.match(e.value, /\.example(\/|$)/, '示例网址须使用 RFC 2606 保留域名');
    if (e.type === 'crypto_wallet' && e.chain === 'TRON') assert.match(e.value, /Example/);
  }
});

test('发布策略：电话/钱包/网址完整，银行卡/姓名/账号打码', () => {
  assert.equal(I.publishValue('phone', '+86 139-0011-2233'), '13900112233');
  assert.equal(I.publishValue('crypto_tron', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'), 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe');
  assert.equal(I.publishValue('url', 'https://a-b.top/dl。'), 'https://a-b.top/dl');
  assert.equal(I.publishValue('bank_card', '6222020200112233445'), '622202*********3445');
  assert.equal(I.publishValue('bank_card', '6222020200112233'), '622202******2233');
  assert.equal(I.publishValue('name', '王建国'), '王**');
  assert.equal(I.publishValue('id_card', '110101199003071234'), '110101********1234');
  assert.ok(!I.publishValue('wechat', 'kefu_tb2026').includes('kefu_tb2026'));
  assert.ok(!I.publishValue('something_new', 'secret123456').includes('secret123456'), '未知类型保守打码');
});

test('校验器拦截未打码的银行卡与姓名', () => {
  const base = { id: 'DS-2026-0001', scenario: 'police', firstSeen: '2026-10-18', source: 'community', status: 'active' };
  assert.ok(I.validateEntry({ ...base, type: 'bank_card', value: '6222020200112233445' }).length > 0);
  assert.ok(I.validateEntry({ ...base, type: 'name', value: '王建国' }).length > 0);
  assert.deepEqual(I.validateEntry({ ...base, type: 'bank_card', value: '622202*********3445' }), []);
  assert.deepEqual(I.validateEntry({ ...base, type: 'bank_card', value: '622202******2233' }), []);
  assert.deepEqual(I.validateEntry({ ...base, type: 'bank_card', value: '***********6789' }), []);
  // 旧格式、露出过多数字、星号位数不对都会被拦截
  assert.ok(I.validateEntry({ ...base, type: 'bank_card', value: '6222 **** **** 3445' }).length > 0);
  assert.ok(I.validateEntry({ ...base, type: 'bank_card', value: '6222020*********3445' }).length > 0);
  assert.ok(I.validateEntry({ ...base, type: 'bank_card', value: '622202***3445' }).length > 0);
  assert.ok(I.validateEntry({ ...base, type: 'phone', value: '1', source: 'example' }).some((m) => /example/.test(m)));
});

test('检索与筛选', () => {
  const all = lib.entries;
  assert.ok(I.filterEntries(all, { type: 'phone' }).every((e) => e.type === 'phone'));
  assert.ok(I.filterEntries(all, { scenario: 'task' }).every((e) => e.scenario === 'task'));
  assert.equal(I.filterEntries(all, { q: '100 0000 0001' })[0].value, '10000000001');
  assert.ok(I.filterEntries(all, { q: '安全账户' }).length >= 1);
  const withRemoved = all.concat([{ ...all[0], id: 'X', status: 'removed' }]);
  assert.equal(I.filterEntries(withRemoved, {}).length, all.length, 'removed 默认不展示');
});

test('CSV 导出：BOM、转义与防公式注入', () => {
  const csv = I.toCSV([{ id: 'a', type: 'script', value: '=HYPERLINK("x"),"引号"', tactics: ['otp', 'urgency'] }]);
  assert.ok(csv.startsWith('\ufeff' + I.CSV_COLS.join(',')));
  assert.ok(csv.includes('"\'=HYPERLINK(""x""),""引号"""'));
  assert.ok(csv.includes('otp|urgency'));
});

test('会话 submission()：按策略输出，report() 仍不含完整电话', () => {
  const s = new E.Session({ scenario: 'police', persona: 'wang' });
  S.BY_ID.police.samples.forEach((l) => s.ingest(l));
  const sub = s.submission();
  assert.equal(sub.schema, I.SUBMISSION_SCHEMA);
  const v = sub.indicators.map((i) => i.value);
  assert.ok(v.includes('13900112233'));
  assert.ok(v.includes('http://gaj-sh-gov.cc/case/8872'));
  assert.ok(v.includes('622202*********3445'));
  const card = sub.indicators.find((i) => i.type === 'bank_card');
  assert.equal(card.issuer, '中国工商银行'); // BIN 推断
  assert.equal(card.cardType, '借记卡');
  assert.ok(v.includes('王**'));
  assert.ok(!JSON.stringify(sub).includes('6222020200112233445'));
  assert.ok(!JSON.stringify(sub).includes('王建国'));
  assert.ok(!JSON.stringify(s.report()).includes('13900112233'));
  assert.ok(I.submissionMarkdown(sub).includes('`13900112233`'));
});
