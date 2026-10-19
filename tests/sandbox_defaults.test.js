'use strict';
// #108 沙盒直连模式不内置服务商地址和模型名；已保存在浏览器里的旧配置原样保留。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.join(__dirname, '..');
const llm = require('../site/assets/js/llm.js');

test('llm.js 默认 baseUrl / model 为空', () => {
  assert.equal(llm.DEFAULTS.baseUrl, '');
  assert.equal(llm.DEFAULTS.model, '');
});

test('已保存的旧配置读取后保持原值（不清除、不覆盖）', () => {
  const old = { engine: 'direct', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus', apiKey: 'sk-test-not-real' };
  const raw = JSON.stringify(old);
  const r = llm.restoreDirectConfig(raw);
  assert.equal(r.engine, 'direct');
  assert.deepEqual(r.direct, { baseUrl: old.baseUrl, model: old.model, apiKey: old.apiKey });
  // 对象形式同样保留，且不改动传入对象
  const copy = JSON.parse(raw);
  assert.deepEqual(llm.restoreDirectConfig(copy).direct, { baseUrl: old.baseUrl, model: old.model, apiKey: old.apiKey });
  assert.deepEqual(copy, old);
  // 其他旧值（自定义服务、只存了规则引擎）也原样读回
  assert.deepEqual(llm.restoreDirectConfig('{"engine":"rule","baseUrl":"https://example.test/v1","model":"m1","apiKey":""}'),
    { engine: 'rule', direct: { baseUrl: 'https://example.test/v1', model: 'm1', apiKey: '' } });
});

test('没保存过 / 坏 JSON：用空默认值、规则引擎', () => {
  for (const v of [null, '', 'not json', '"x"']) {
    assert.deepEqual(llm.restoreDirectConfig(v), { engine: 'rule', direct: { baseUrl: '', model: '', apiKey: '' } }, String(v));
  }
});

test('missingDirectConfig 列出缺的项', () => {
  assert.deepEqual(llm.missingDirectConfig({}), ['Base URL', 'model', 'API Key']);
  assert.deepEqual(llm.missingDirectConfig({ baseUrl: 'https://h/v1', model: 'm', apiKey: 'k' }), []);
  assert.deepEqual(llm.missingDirectConfig({ baseUrl: ' ', model: 'm' }, { apiKey: false }), ['Base URL']);
});

test('直连配置为空时 chatCompletions 直接拒绝并提示，不发请求', async () => {
  const orig = global.fetch; let called = 0;
  global.fetch = () => { called++; return Promise.reject(new Error('should not fetch')); };
  try {
    await assert.rejects(llm.chatCompletions({ baseUrl: '', model: '', apiKey: 'k' }, []), /未配置 Base URL、model.*QUICKSTART/);
    assert.equal(called, 0);
  } finally { global.fetch = orig; }
});

test('demo.html 直连输入框默认值为空、占位为通用格式，并链到 QUICKSTART', () => {
  const html = fs.readFileSync(path.join(ROOT, 'site/demo.html'), 'utf8');
  assert.match(html, /id="cfgBase" value="" placeholder="https:\/\/你的接口地址\/v1"/);
  assert.match(html, /id="cfgModel" value="" placeholder="模型名"/);
  assert.match(html, /github\.com\/deepsucksi\/deepsuck\/blob\/main\/docs\/QUICKSTART\.md/);
  const i18n = fs.readFileSync(path.join(ROOT, 'site/assets/js/i18n.js'), 'utf8');
  assert.match(i18n, /'d\.base\.ph': 'https:\/\/your-api-host\/v1'/);
  assert.match(i18n, /'d\.model\.ph': 'model name'/);
});

test('demo.js 读取设置时用 restoreDirectConfig，且读取时不删除 localStorage', () => {
  const js = fs.readFileSync(path.join(ROOT, 'site/assets/js/demo.js'), 'utf8');
  const load = js.slice(js.indexOf('function loadSettings'), js.indexOf('function openSettings'));
  assert.match(load, /restoreDirectConfig/);
  assert.doesNotMatch(load, /removeItem|setItem/);
});

test('服务端代理未设 LLM_BASE_URL / LLM_MODEL 时仍有默认值（行为不变）', () => {
  const src = fs.readFileSync(path.join(ROOT, 'server/index.js'), 'utf8');
  assert.match(src, /baseUrl: process\.env\.LLM_BASE_URL \|\| 'https:\/\/[^']+'/);
  assert.match(src, /model: process\.env\.LLM_MODEL \|\| '[^']+'/);
});
