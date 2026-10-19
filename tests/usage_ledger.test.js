'use strict';
// #174：代理把上游返回的 usage 原样记进逐次台账（DATA_DIR/chat-usage-YYYY-MM-DD.jsonl），金额按 usage × 单价实算；
// 上游没给 usage 时才按字数估算并标 estimated。/api/chat 响应带回 token 计数（不含金额、单价、上游地址）。
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'ds-usage-'));
Object.assign(process.env, { DATA_DIR: DIR, PRICE_LLM_IN_PER_M: '0.8', PRICE_LLM_OUT_PER_M: '2.7', CHAT_DAILY_BUDGET_CNY: '0', ALLOWED_ORIGINS: '' });
delete process.env.DASHSCOPE_API_KEY; delete process.env.LLM_API_KEY;
const G = require('../server/guard.js');
const { server, CFG, budget } = require('../server/index.js');

const RAW = {
  prompt_tokens: 1200, completion_tokens: 80, total_tokens: 1280,
  completion_tokens_details: { reasoning_tokens: 30, text_tokens: 80 },
  prompt_tokens_details: { cached_tokens: 512, text_tokens: 1200 }
};
let nextUsage = RAW;
let upstreamUrl = '';

async function withServers(fn) {
  const up = http.createServer((req, res) => {
    req.resume(); req.on('end', () => {
      const j = { choices: [{ message: { content: '哦，你等等啊，我找下眼镜' } }] };
      if (nextUsage) j.usage = nextUsage;
      res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j));
    });
  });
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  upstreamUrl = 'http://127.0.0.1:' + up.address().port + '/v1';
  Object.assign(CFG, { apiKey: 'test-key-not-real', baseUrl: upstreamUrl, model: 'test-model' });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try { return await fn('http://127.0.0.1:' + server.address().port); } finally { server.close(); up.close(); }
}
const chat = (base) => fetch(base + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ persona: 'wang', scenario: 'refund', hint: 'generic', transcript: [{ role: 'scammer', text: '你好，我是快递客服' }] }) });
const ledger = () => fs.readFileSync(path.join(DIR, 'chat-usage-' + G.cnDay() + '.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));

test('上游带 usage：台账原样记录、金额按单价实算；响应带回 token 计数；没 usage 时回退估算并标 estimated', async () => {
  await withServers(async (base) => {
    // 1) 带 usage
    nextUsage = RAW;
    const r1 = await chat(base);
    assert.equal(r1.status, 200);
    const j1 = await r1.json();
    let L = ledger();
    assert.equal(L.length, 1);
    assert.deepEqual(L[0].usage, RAW, 'usage 原样（含 reasoning_tokens、cached_tokens 等原始字段）');
    assert.equal(L[0].estimated, false);
    assert.equal(L[0].model, 'test-model');
    assert.equal(L[0].cny, +((1200 * 0.8 + 80 * 2.7) / 1e6).toFixed(8)); // 0.001176
    assert.deepEqual(L[0].prices, { inPerM: 0.8, outPerM: 2.7 });
    assert.deepEqual(j1.usage, { prompt_tokens: 1200, completion_tokens: 80, total_tokens: 1280, estimated: false, reasoning_tokens: 30, cached_tokens: 512 });
    // 响应和台账都不带 key、上游地址
    for (const s of [JSON.stringify(j1), fs.readFileSync(path.join(DIR, 'chat-usage-' + G.cnDay() + '.jsonl'), 'utf8')]) {
      assert.ok(!s.includes('test-key-not-real') && !s.includes(upstreamUrl) && !s.includes('127.0.0.1'), s);
    }
    assert.ok(!('cny' in j1.usage) && !('prices' in j1));

    // 2) 不带 usage → 估算
    nextUsage = null;
    const j2 = await (await chat(base)).json();
    L = ledger();
    assert.equal(L.length, 2);
    assert.equal(L[1].estimated, true);
    assert.ok(L[1].usage.prompt_tokens > 0 && L[1].usage.completion_tokens > 0);
    assert.equal(L[1].usage.total_tokens, L[1].usage.prompt_tokens + L[1].usage.completion_tokens);
    assert.equal(L[1].cny, +((L[1].usage.prompt_tokens * 0.8 + L[1].usage.completion_tokens * 2.7) / 1e6).toFixed(8));
    assert.equal(j2.usage.estimated, true);
    assert.equal(j2.usage.prompt_tokens, L[1].usage.prompt_tokens);
    assert.ok(!('reasoning_tokens' in j2.usage));

    // 3) 当日汇总：原有字段不变（voice/cost.py 读 inTokens/outTokens），追加 reasoning / cached / estimatedCalls
    budget.flush();
    const day = JSON.parse(fs.readFileSync(path.join(DIR, 'chat-budget.json'), 'utf8'));
    assert.equal(day.calls, 2);
    assert.equal(day.inTokens, 1200 + L[1].usage.prompt_tokens);
    assert.equal(day.outTokens, 80 + L[1].usage.completion_tokens);
    assert.equal(day.reasoningTokens, 30); assert.equal(day.cachedTokens, 512); assert.equal(day.estimatedCalls, 1);
    assert.equal(day.spentCny, +(L[0].cny + L[1].cny).toFixed(6));
  });
});

test('guard.record：失败且无 usage 只释放预占、不记账；normUsage 判定', () => {
  const B = G.createBudget({ capCny: 0.002, prices: { inPerM: 0.8, outPerM: 2.7 } });
  const r = B.reserve(1000, 200);
  assert.equal(B.record(r, null, null, { failed: true }), null);
  assert.equal(B.status().calls, 0);
  assert.ok(B.reserve(1000, 200), '预占已释放');
  const rec = B.record(0, { prompt_tokens: 10, completion_tokens: 2 }, { in: 99, out: 99 });
  assert.equal(rec.estimated, false); assert.deepEqual(rec.usage, { prompt_tokens: 10, completion_tokens: 2 });
  assert.equal(G.normUsage({}), null);
  assert.equal(G.normUsage({ foo: 1 }), null);
  assert.equal(G.normUsage('x'), null);
  assert.deepEqual(G.normUsage({ prompt_tokens: 5 }), { in: 5, out: 0, reasoning: 0, cached: 0 });
});
