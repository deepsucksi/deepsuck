'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

test('server：health / 静态文件 / 未配置 Key 时 /api/chat 返回 503 / 禁止目录穿越', async () => {
  delete process.env.DASHSCOPE_API_KEY; delete process.env.LLM_API_KEY;
  const { server, CFG } = require('../server/index.js');
  CFG.apiKey = '';
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + server.address().port;
  try {
    const h = await (await fetch(base + '/api/health')).json();
    assert.equal(h.ok, true); assert.equal(h.llmConfigured, false);
    const idx = await fetch(base + '/');
    assert.equal(idx.status, 200);
    assert.match(await idx.text(), /DeepSuck/);
    const chat = await fetch(base + '/api/chat', { method: 'POST', body: '{}' });
    assert.equal(chat.status, 503);
    const trav = await fetch(base + '/..%2f..%2fpackage.json');
    assert.ok(trav.status === 403 || trav.status === 404);
  } finally { server.close(); }
});

test('server：托管 live-config.js 时注入 local=true；直接读文件时不带', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const { server } = require('../server/index.js');
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const js = await (await fetch('http://127.0.0.1:' + server.address().port + '/assets/js/live-config.js')).text();
    assert.match(js, /\.local = true/);
    const raw = fs.readFileSync(path.join(__dirname, '..', 'site', 'assets', 'js', 'live-config.js'), 'utf8');
    assert.doesNotMatch(raw, /\.local = true/);
  } finally { server.close(); }
});
