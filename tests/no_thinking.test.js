'use strict';
// #166：qwen3.8-flash（百炼兼容接口）默认开思考。代理发往上游固定带 enable_thinking:false（客户端打不开）；
// 浏览器直连只对 qwen 型号 / 百炼地址带，其他接口不带（严格接口会拒绝不认识的字段）。
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

delete process.env.LLM_ENABLE_THINKING;
const llm = require('../site/assets/js/llm.js');
const quirks = require('../site/assets/js/llm-quirks.js');

function captureFetch() {
  const sent = [];
  const orig = global.fetch;
  global.fetch = async (url, opt) => {
    sent.push({ url, body: JSON.parse(opt.body) });
    return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '啊，你说啥' } }] }) };
  };
  return { sent, restore: () => { global.fetch = orig; } };
}

test('代理：发往上游的请求体带 enable_thinking:false，客户端传 true 也被覆盖', async () => {
  delete process.env.DASHSCOPE_API_KEY; delete process.env.LLM_API_KEY;
  const got = [];
  const upstream = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      got.push({ url: req.url, body: JSON.parse(raw) });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { content: '哦，你等等啊' } }], usage: { prompt_tokens: 10, completion_tokens: 3 } }));
    });
  });
  await new Promise((r) => upstream.listen(0, '127.0.0.1', r));
  const { server, CFG } = require('../server/index.js');
  assert.equal(CFG.enableThinking, false, '默认关');
  const saved = { apiKey: CFG.apiKey, baseUrl: CFG.baseUrl, model: CFG.model };
  CFG.apiKey = 'test-key'; CFG.baseUrl = 'http://127.0.0.1:' + upstream.address().port + '/v1'; CFG.model = 'some-model';
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const r = await fetch('http://127.0.0.1:' + server.address().port + '/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona: 'wang', scenario: 'refund', hint: 'generic', enable_thinking: true, enableThinking: true,
        extra_body: { enable_thinking: true }, transcript: [{ role: 'scammer', text: '你好，我是快递客服' }] })
    });
    assert.equal(r.status, 200, await r.clone().text());
    assert.equal(got.length, 1);
    assert.equal(got[0].url, '/v1/chat/completions');
    // 型号不是 qwen、地址也不是百炼时代理照样带（代理上游固定按百炼处理）
    assert.equal(got[0].body.enable_thinking, false);
    assert.equal(got[0].body.extra_body, undefined);
  } finally {
    server.close(); upstream.close();
    Object.assign(CFG, saved);
  }
});

test('代理：LLM_ENABLE_THINKING 只认 1/true/on/yes，默认关', () => {
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'server', 'index.js'), 'utf8');
  assert.match(src, /enableThinking: \/\^\(1\|true\|on\|yes\)\$\/i\.test\(String\(process\.env\.LLM_ENABLE_THINKING \|\| ''\)/);
});

test('requestBody：cfg.enableThinking 是布尔值时原样带上（服务端代理的路径）', () => {
  assert.equal(llm.requestBody({ model: 'm', enableThinking: false }, [], 'https://h/v1').enable_thinking, false);
  assert.equal(llm.requestBody({ model: 'm', enableThinking: true }, [], 'https://h/v1').enable_thinking, true);
});

test('直连：qwen 型号或百炼地址带 enable_thinking:false，其他接口不带', async () => {
  const cases = [
    [{ baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen3.8-flash' }, true],
    [{ baseUrl: 'https://my-gateway.example/v1', model: 'Qwen3.8-Flash' }, true],
    [{ baseUrl: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', model: 'some-other-model' }, true],
    [{ baseUrl: 'https://api.example.com/v1', model: 'llama-3' }, false],
    [{ baseUrl: 'https://open.bigmodel.example/api/v1', model: 'glm-4' }, false],
  ];
  const cap = captureFetch();
  try {
    for (const [c] of cases) await llm.chatCompletions(Object.assign({ apiKey: 'k' }, c), [{ role: 'user', content: '喂' }]);
  } finally { cap.restore(); }
  assert.equal(cap.sent.length, cases.length);
  cases.forEach(([c, want], i) => {
    const b = cap.sent[i].body;
    if (want) assert.equal(b.enable_thinking, false, c.model + ' @ ' + c.baseUrl);
    else assert.ok(!('enable_thinking' in b), '不应带 enable_thinking：' + c.model + ' @ ' + c.baseUrl);
  });
});

test('llm-quirks.thinkingOff 判定', () => {
  assert.equal(quirks.thinkingOff('qwen3.8-flash', ''), true);
  assert.equal(quirks.thinkingOff('', 'https://dashscope.aliyuncs.com/compatible-mode/v1'), true);
  assert.equal(quirks.thinkingOff('my-qwen', 'https://h/v1'), false);
  assert.equal(quirks.thinkingOff('', ''), false);
});

test('demo.html 在 llm.js 之前加载 llm-quirks.js', () => {
  const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', 'site', 'demo.html'), 'utf8');
  const a = html.indexOf('assets/js/llm-quirks.js'), b = html.indexOf('assets/js/llm.js');
  assert.ok(a > 0 && a < b);
});
