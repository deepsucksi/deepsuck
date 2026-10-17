'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/js/scenarios.js');
const P = require('../site/assets/js/personas.js');
const T = require('../site/assets/js/tactics.js');
const X = require('../site/assets/js/extractors.js');

function seeded(seed) { return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }

test('场景：至少 7 个，每个都有标签、目标与 ≥5 条样例', () => {
  assert.ok(S.SCENARIOS.length >= 7);
  for (const sc of S.SCENARIOS) {
    assert.ok(sc.tags && sc.tags.length >= 2, sc.id + ' tags');
    assert.ok(sc.goals.length >= 3, sc.id + ' goals');
    assert.ok(sc.samples.length >= 5, sc.id + ' samples');
  }
});

test('每个人设都为每个场景准备了称呼与开场白', () => {
  for (const p of P.PERSONAS) {
    for (const sc of S.SCENARIOS) {
      assert.ok(p.call[sc.id], `${p.id}.call.${sc.id}`);
      assert.ok(p.openings[sc.id] && p.openings[sc.id].length, `${p.id}.openings.${sc.id}`);
    }
    for (const intent of ['verify_identity', 'task_stall', 'loan_stall', 'campus_stall']) {
      assert.ok(p.templates[intent] && p.templates[intent].length >= 3, `${p.id}.${intent}`);
    }
  }
});

test('新话术标签：刷单 / 虚假贷款 / 冒充熟人 / 注销校园贷', () => {
  const has = (txt, id) => T.classify(txt).some((t) => t.id === id);
  assert.ok(has('做完新手任务后有福利单，垫付后返本金和佣金', 'task_rebate'));
  assert.ok(has('无抵押低息贷款秒批，先交解冻金', 'loan_fraud'));
  assert.ok(has('我是你王总，这是我新的微信号，在开会不方便接电话', 'acquaintance'));
  assert.ok(has('你在校期间开通过校园贷，必须注销，先把借呗额度清空', 'campus_loan'));
  assert.ok(!has('今天天气不错，我们去公园散步吧', 'loan_fraud'));
});

test('冒充熟人：先反向核验身份，最多两次', () => {
  const s = new E.Session({ scenario: 'boss', persona: 'wang', rng: seeded(7) });
  s.opening();
  const intents = ['我是你王总，换了新号', '我在开会不方便接电话', '别打我电话，在开会'].map((l) => s.ruleReply(s.ingest(l)).intent);
  assert.equal(intents[0], 'verify_identity');
  assert.equal(intents.filter((i) => i === 'verify_identity').length, 2);
});

test('情境模板：对方没提"流水/冻结"时不会冒出相关接话', () => {
  for (let seed = 1; seed < 40; seed++) {
    const s = new E.Session({ scenario: 'loan', persona: 'lin', rng: seeded(seed) });
    const r = s.ruleReply(s.ingest('您好，您有一笔无抵押贷款可以秒批'));
    assert.ok(!/流水|冻结/.test(r.text), r.text);
  }
});

test('同一意图模板不连续重复', () => {
  const s = new E.Session({ scenario: 'task', persona: 'li', rng: seeded(3) });
  const seen = [];
  for (let i = 0; i < 3; i++) seen.push(s.pick('generic', ''));
  assert.equal(new Set(seen).size, 3);
});

test('全部场景 × 人设：报告中不含任何样例原始敏感值', () => {
  for (const sc of S.SCENARIOS) {
    const raws = [];
    sc.samples.forEach((l) => X.extractSensitive(l).forEach((e) => raws.push(e.value)));
    assert.ok(raws.length >= 3, sc.id + ' 样例应包含 ≥3 条可提取情报');
    for (const p of P.PERSONAS) {
      const s = new E.Session({ scenario: sc.id, persona: p.id, rng: seeded(11) });
      s.opening();
      sc.samples.forEach((l) => s.ruleReply(s.ingest(l)));
      const json = JSON.stringify(s.report());
      for (const raw of raws) assert.ok(!json.includes(raw), `${sc.id}/${p.id} 泄露 ${raw}`);
      assert.ok(!/\{(call|intel|ask)\}|\[object Object\]|undefined/.test(json), `${sc.id}/${p.id} 模板异常`);
    }
  }
});
