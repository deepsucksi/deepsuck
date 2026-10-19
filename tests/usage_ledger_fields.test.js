'use strict';
// #178：逐次台账一行只含白名单字段（ts、day、model、estimated、failed、usage、cny、prices），
// 不能有对话内容、IP、session、UA；usage 只保留数字叶子，上游塞进 usage 的字符串字段过滤掉。
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'ds-ledger-fields-'));
Object.assign(process.env, { DATA_DIR: DIR, CHAT_DAILY_BUDGET_CNY: '0', ALLOWED_ORIGINS: '', TRUST_PROXY: '1' });
delete process.env.DASHSCOPE_API_KEY; delete process.env.LLM_API_KEY;
const G = require('../server/guard.js');
const { server, CFG } = require('../server/index.js');

const WHITELIST = ['ts', 'day', 'model', 'estimated', 'failed', 'usage', 'cny', 'prices'];
const SECRET_TEXT = '我是快递客服王建国，退款打到6222021234567890123';
const SESSION = 'sess-7f3a9c'; const UA = 'Mozilla/5.0 LedgerProbe/1.0'; const IP = '203.0.113.77';

let mode = 'dirty';
function upstreamUsage() {
  if (mode === 'none') return undefined;
  return {
    prompt_tokens: 900, completion_tokens: 40, total_tokens: 940,
    model: 'upstream-internal-name', request_id: 'req-abc', note: SECRET_TEXT, tags: ['x', 1], flag: true,
    completion_tokens_details: { reasoning_tokens: 12, text_tokens: 40, tier: 'premium' },
    prompt_tokens_details: { cached_tokens: 256, source: 'cache-node-3', audio: { seconds: 2, codec: 'pcm' } },
    extra: { label: 'only-strings' }
  };
}

function checkLine(rec) {
  for (const k of Object.keys(rec)) assert.ok(WHITELIST.includes(k), '台账出现白名单外字段: ' + k);
  for (const k of ['ts', 'day', 'estimated', 'usage', 'cny', 'prices']) assert.ok(k in rec, '缺字段 ' + k);
  (function walk(o, p) {
    for (const [k, v] of Object.entries(o)) {
      if (v && typeof v === 'object') { assert.ok(!Array.isArray(v), p + k + ' 是数组'); walk(v, p + k + '.'); }
      else assert.equal(typeof v, 'number', 'usage 里只能有数字叶子: ' + p + k + '=' + JSON.stringify(v));
    }
  })(rec.usage, 'usage.');
}

test('台账行只含白名单字段；usage 只留数字叶子；不含对话、IP、session、UA', async () => {
  const up = http.createServer((req, res) => {
    req.resume(); req.on('end', () => {
      const j = { choices: [{ message: { content: '哦，你等等啊' } }] };
      const u = upstreamUsage(); if (u) j.usage = u;
      res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(j));
    });
  });
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  Object.assign(CFG, { apiKey: 'test-key-not-real', baseUrl: 'http://127.0.0.1:' + up.address().port + '/v1', model: 'test-model' });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const post = () => fetch('http://127.0.0.1:' + server.address().port + '/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'User-Agent': UA, 'X-Forwarded-For': IP, Cookie: 'sid=' + SESSION },
    body: JSON.stringify({ persona: 'wang', scenario: 'refund', hint: 'generic', session: SESSION, sessionId: SESSION, ua: UA, ip: IP,
      transcript: [{ role: 'scammer', text: SECRET_TEXT }] })
  });
  try {
    mode = 'dirty'; assert.equal((await post()).status, 200);
    mode = 'none'; assert.equal((await post()).status, 200);
  } finally { server.close(); up.close(); }

  const file = path.join(DIR, 'chat-usage-' + G.cnDay() + '.jsonl');
  const raw = fs.readFileSync(file, 'utf8');
  const lines = raw.trim().split('\n').map((l) => JSON.parse(l));
  assert.equal(lines.length, 2);
  lines.forEach(checkLine);
  assert.deepEqual(lines[0].usage, {
    prompt_tokens: 900, completion_tokens: 40, total_tokens: 940,
    completion_tokens_details: { reasoning_tokens: 12, text_tokens: 40 },
    prompt_tokens_details: { cached_tokens: 256, audio: { seconds: 2 } }
  });
  assert.equal(lines[1].estimated, true);
  for (const bad of ['王建国', '6222021234567890123', '快递客服', SESSION, UA, IP, '127.0.0.1', 'test-key-not-real', 'upstream-internal-name', 'req-abc', 'cache-node-3', 'premium', 'only-strings']) {
    assert.ok(!raw.includes(bad), '台账不应出现: ' + bad);
  }
});

test('guard.record：meta 里的其他字段不进台账；numericLeaves', () => {
  const B = G.createBudget({ capCny: 0, prices: { inPerM: 0.8, outPerM: 2.7 } });
  const rec = B.record(0, { prompt_tokens: 1, completion_tokens: 2, id: 'x' }, null,
    { model: 'm', failed: true, ip: IP, ua: UA, session: SESSION, transcript: SECRET_TEXT });
  assert.deepEqual(Object.keys(rec).sort(), ['cny', 'day', 'estimated', 'failed', 'model', 'prices', 'ts', 'usage']);
  assert.deepEqual(rec.usage, { prompt_tokens: 1, completion_tokens: 2 });
  assert.deepEqual(G.LEDGER_FIELDS, WHITELIST);
  assert.deepEqual(G.numericLeaves({ a: 1, b: 'x', c: [1], d: { e: NaN, f: Infinity, g: 3 }, h: null }), { a: 1, d: { g: 3 } });
  assert.deepEqual(G.numericLeaves('str'), {});
});
