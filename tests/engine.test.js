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
