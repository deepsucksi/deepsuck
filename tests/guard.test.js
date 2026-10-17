'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');
const os = require('os');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const G = require('../server/guard.js');

test('guard：限流（每 IP / 每天 / 全局）', () => {
  let t = Date.parse('2026-10-18T00:00:00Z');
  const L = G.createLimiter({ perIpPerMin: 2, perIpPerDay: 3, globalPerMin: 3, now: () => t });
  assert.equal(L.check('a'), null); assert.equal(L.check('a'), null);
  assert.match(L.check('a'), /频繁/);
  t += 61000; assert.equal(L.check('a'), null);
  t += 61000; assert.match(L.check('a'), /今日/);
  assert.equal(L.check('b'), null); assert.equal(L.check('c'), null); assert.equal(L.check('d'), null);
  assert.match(L.check('e'), /全站/);
  t += 24 * 3600 * 1000; assert.equal(L.check('a'), null); // 跨天重置
});

test('guard：预算预占 + 结算 + 持久化', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ds-budget-'));
  const B = G.createBudget({ capCny: 0.003, dir, prices: { inPerM: 0.8, outPerM: 2 } });
  const r1 = B.reserve(1000, 100); assert.ok(r1 > 0);
  B.commit(r1, { in: 1000, out: 100 }); // 0.001
  const r2 = B.reserve(1000, 100); B.commit(r2, { in: 1000, out: 100 });
  const r3 = B.reserve(1000, 100); assert.ok(r3); // 0.002 + 0.001 = 0.003 刚好
  assert.equal(B.reserve(1000, 100), null); // 预占后超额
  B.commit(r3, null); // 失败调用：释放预占
  assert.ok(B.reserve(1000, 100));
  B.flush();
  const B2 = G.createBudget({ capCny: 0.003, dir });
  assert.equal(B2.status().spentCny, 0.002); assert.equal(B2.status().calls, 2);
  assert.equal(G.createBudget({ capCny: 0 }).reserve(1e9, 1e9) > 0, true); // 0 = 不限
});

test('guard：工具函数', () => {
  assert.equal(G.cnDay(Date.parse('2026-10-17T16:30:00Z')), '2026-10-18');
  assert.deepEqual(G.parseOrigins('https://deepsuck.si/, https://www.deepsuck.si'), ['https://deepsuck.si', 'https://www.deepsuck.si']);
  assert.ok(G.estimateTokens([{ content: '你好你好' }]) >= 4);
});

function listen(srv) { return new Promise((r) => srv.listen(0, '127.0.0.1', () => r(srv.address().port))); }

test('server（子进程，假上游）：CORS 白名单、每局轮数、每日预算触发后 429', async () => {
  let upstreamCalls = 0;
  const up = http.createServer((req, res) => {
    upstreamCalls++;
    req.resume(); req.on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { content: '哎呀，你再说一遍？' } }], usage: { prompt_tokens: 1000, completion_tokens: 100 } }));
    });
  });
  const upPort = await listen(up);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ds-srv-'));
  const port = 20000 + Math.floor(Math.random() * 20000);
  const child = spawn(process.execPath, [path.join(__dirname, '..', 'server', 'index.js')], {
    env: Object.assign({}, process.env, {
      DASHSCOPE_API_KEY: 'test-key', LLM_API_KEY: '', LLM_BASE_URL: 'http://127.0.0.1:' + upPort, HOST: '127.0.0.1', PORT: String(port),
      CHAT_DAILY_BUDGET_CNY: '0.0025', DATA_DIR: dir, ALLOWED_ORIGINS: 'https://deepsuck.si', CHAT_MAX_TURNS: '3',
      RATE_LIMIT_PER_MIN: '100', SERVE_STATIC: '0'
    }), stdio: ['ignore', 'pipe', 'pipe']
  });
  try {
    await new Promise((r, j) => { const to = setTimeout(j, 5000); child.stdout.on('data', (d) => { if (/已启动/.test(d)) { clearTimeout(to); r(); } }); child.on('exit', j); });
    const base = 'http://127.0.0.1:' + port;
    const O = { 'Content-Type': 'application/json', Origin: 'https://deepsuck.si' };
    const body = (n) => JSON.stringify({ persona: 'wang', scenario: 'refund', hint: 'generic', transcript: Array.from({ length: n }, () => ({ role: 'scammer', text: '你好，我是客服' })) });
    const pre = await fetch(base + '/api/chat', { method: 'OPTIONS', headers: O });
    assert.equal(pre.status, 204); assert.equal(pre.headers.get('access-control-allow-origin'), 'https://deepsuck.si');
    assert.equal((await fetch(base + '/api/chat', { method: 'POST', headers: { Origin: 'https://evil.example' }, body: body(1) })).status, 403);
    assert.equal((await fetch(base + '/api/chat', { method: 'POST', body: body(1) })).status, 403); // 无 Origin
    const turns = await fetch(base + '/api/chat', { method: 'POST', headers: O, body: body(4) });
    assert.equal(turns.status, 429); assert.equal((await turns.json()).code, 'max_turns');
    const ok1 = await fetch(base + '/api/chat', { method: 'POST', headers: O, body: body(1) });
    assert.equal(ok1.status, 200); assert.match((await ok1.json()).reply, /再说一遍/);
    assert.equal((await fetch(base + '/api/chat', { method: 'POST', headers: O, body: body(1) })).status, 200);
    const over = await fetch(base + '/api/chat', { method: 'POST', headers: O, body: body(1) });
    assert.equal(over.status, 429); assert.equal((await over.json()).code, 'budget');
    assert.equal(upstreamCalls, 2); // 超额请求没有打到上游
    const h = await (await fetch(base + '/api/health', { headers: O })).json();
    assert.equal(h.budget.capCny, 0.0025); assert.equal(h.limits.maxTurns, 3);
    assert.ok(!JSON.stringify(h).includes('test-key'));
    assert.equal((await fetch(base + '/index.html')).status, 404); // SERVE_STATIC=0
  } finally { child.kill('SIGTERM'); up.close(); }
});
