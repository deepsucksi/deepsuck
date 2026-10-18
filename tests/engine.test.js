'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/js/scenarios.js');
const T = require('../site/assets/js/tactics.js');
const L = require('../site/assets/js/llm.js');

function seeded(seed) { return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }

test('话术分类器：公检法 + 安全账户 + 验证码', () => {
  const ids = T.classify('我是公安局民警，马上把钱转到安全账户，不要告诉家人，把验证码报给我').map((t) => t.id);
  for (const id of ['authority', 'safe_account', 'otp', 'secrecy', 'urgency']) assert.ok(ids.includes(id), id);
});

test('完整会话：情报去重、报告脱敏、无原文泄露', () => {
  for (const sc of S.SCENARIOS) {
    for (const persona of ['wang', 'li', 'lin']) {
      const s = new E.Session({ scenario: sc.id, persona, rng: seeded(42) });
      s.opening();
      for (const l of sc.samples) { const a = s.ingest(l); const r = s.ruleReply(a); assert.ok(r.text.length > 0); }
      s.ingest(sc.samples[3]); // 重复一句，情报应去重
      s.end();
      const rep = s.report();
      assert.equal(rep.schema, E.REPORT_SCHEMA);
      assert.ok(rep.intel.length >= 3, sc.id + ' intel');
      assert.ok(rep.tactics.length >= 3, sc.id + ' tactics');
      assert.ok(rep.stats.estimatedScammerSeconds > 0);
      const json = JSON.stringify(rep);
      for (const raw of ['6217001234567890123', '6222020200112233445', '13900112233', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe',
        '0x12ab34cd56ef7890abcdef1234567890abcd9f3e', 'refund-tb-kefu', 'goldwin-vip', '2876543210', 'kefu_tb2026', '王建国', '李强']) {
        assert.ok(!json.includes(raw), `${sc.id}/${persona} 报告泄露原文: ${raw}`);
      }
      assert.ok(!/\{(call|intel|ask)\}/.test(json), '模板变量未替换');
    }
  }
});

test('LLM：发送给模型的消息已脱敏，输出过滤长数字串', () => {
  const msgs = L.buildMessages({ persona: 'wang', scenario: 'police', hint: 'otp_stall', transcript: [{ role: 'scammer', text: '转到 6222020200112233445，打 13900112233' }] });
  const joined = JSON.stringify(msgs);
  assert.ok(!joined.includes('6222020200112233445') && !joined.includes('13900112233'));
  assert.equal(msgs[0].role, 'system');
  assert.ok(!/\d{5,}/.test(L.sanitizeReply('验证码是 834921，你记一下')));
});

test('拖延句池：secrecy / loan_stall 每个人设 ≥12 条、在轮换链上、用完轮换不重复、近期去重', () => {
  const P = require('../site/assets/core/personas.json');
  for (const p of P.personas) {
    for (const k of ['secrecy', 'loan_stall']) {
      const t = p.templates[k].map((x) => (typeof x === 'string' ? x : x.t));
      assert.ok(new Set(t).size >= 12, p.id + ' ' + k);
    }
  }
  for (const pid of ['wang', 'li', 'lin']) {
    const s = new E.Session({ scenario: 'loan', persona: pid, rng: () => 0, now: () => 0 });
    const out = [];
    for (let i = 0; i < 16; i++) out.push(s.pick(s.freshIntent('secrecy'), '别告诉家人'));
    assert.equal(new Set(out).size, out.length, pid);
    assert.notEqual(s.freshIntent('secrecy'), 'secrecy');
  }
});

test('复述情报：面对骗子的回复不出现打码星号与原值，报告仍脱敏（与 Python 一致）', () => {
  const lines = ['收款卡号 6222020200112233445，户名王建国，工商银行', '有问题打 13900112233，或者加QQ 2876543210',
    '下载 APP：https://refund-tb-kefu.top/dl', 'USDT 转到 TRC20 地址 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'];
  const raws = ['6222020200112233445', '王建国', '13900112233', '2876543210', 'refund-tb-kefu.top', 'TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe'];
  for (const persona of ['wang', 'li', 'lin']) {
    for (let seed = 1; seed < 30; seed++) {
      const s = new E.Session({ scenario: 'police', persona, rng: seeded(seed) });
      s.opening();
      for (const l of lines) {
        const r = s.ruleReply(s.ingest(l));
        if (r.intent !== 'confirm_intel') continue;
        assert.ok(!/[*＊]/.test(r.text), r.text);
        for (const v of raws) assert.ok(r.text.indexOf(v) < 0, r.text);
      }
      const json = JSON.stringify(s.report());
      for (const v of raws) assert.ok(json.indexOf(v) < 0, v);
    }
  }
});

test('纯拖延不连续两轮：第二轮换成小步配合（coop_step）', () => {
  const stall = ['你快点，别磨蹭', '验证码发我', '听不懂吗？赶紧的', '就差你了', '你到底弄好没有', '嗯', '好的'];
  const PURE = ['otp_stall', 'urgency_stall', 'tech_trouble', 'slow_walk', 'ask_repeat', 'misunderstand', 'info_stall', 'generic'];
  for (const persona of ['wang', 'li', 'lin']) {
    for (let seed = 1; seed < 20; seed++) {
      const s = new E.Session({ scenario: 'police', persona, rng: seeded(seed) });
      s.opening();
      let prev = null, coop = 0;
      for (let i = 0; i < 30; i++) {
        const r = s.ruleReply(s.ingest(stall[(i * 3 + seed) % stall.length]));
        assert.ok(!(PURE.includes(prev) && PURE.includes(r.intent)), persona + ' ' + seed + ' ' + i);
        coop += r.intent === 'coop_step';
        prev = r.intent;
      }
      assert.ok(coop > 0);
    }
  }
});

test('验证码拖延句池 ≥16，按池大小自适应的去重窗口', () => {
  for (const persona of ['wang', 'li', 'lin']) {
    const s = new E.Session({ scenario: 'police', persona, rng: seeded(3) });
    const n = s.persona.templates.otp_stall.length, w = Math.floor(n / 2);
    assert.ok(n >= 16, persona);
    const picks = [];
    for (let i = 0; i < 60; i++) picks.push(s.pick('otp_stall', '验证码发我'));
    assert.equal(new Set(picks.slice(0, n)).size, n);
    picks.forEach((x, i) => assert.ok(picks.slice(Math.max(0, i - w), i).indexOf(x) < 0, persona + ' ' + i));
  }
});
