'use strict';
// 公开文案不点名任何商业公司或产品（OpenAI / DeepSeek / Apate / ChatGPT / Anthropic / Claude / GPT 等）。
// 只检查面向用户的文案：站点 HTML、i18n 词条、README、docs、语音页静态资源。代码标识符、环境变量、API 地址不在此列。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.join(__dirname, '..');
const BANNED = /openai|deepseek|apate|chatgpt|anthropic|claude|gpt/i;

function walk(dir, exts, skip = []) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (skip.some((s) => p.includes(s))) continue;
    if (e.isDirectory()) out.push(...walk(p, exts, skip));
    else if (exts.includes(path.extname(e.name))) out.push(p);
  }
  return out;
}

const files = [
  ...walk(path.join(ROOT, 'site'), ['.html'], ['vendor']),
  path.join(ROOT, 'site/assets/js/i18n.js'),
  ...fs.readdirSync(ROOT).filter((f) => /^README/i.test(f)).map((f) => path.join(ROOT, f)),
  ...walk(path.join(ROOT, 'docs'), ['.md']),
  ...walk(path.join(ROOT, 'voice/static'), ['.html', '.json']),
  ...walk(path.join(ROOT, 'voice'), ['.md'], ['static']),
];

test('公开文案不出现商业公司/产品名', () => {
  assert.ok(files.length >= 10);
  const hits = [];
  for (const f of files) {
    const lines = fs.readFileSync(f, 'utf8').replace(/data:[a-z]+\/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+/g, '').split('\n');
    lines.forEach((l, i) => { const m = l.match(BANNED); if (m) hits.push(`${path.relative(ROOT, f)}:${i + 1}: ${m[0]}`); });
  }
  assert.deepEqual(hits, []);
});

test('首页「零成本」段落用中性说法', () => {
  const html = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
  assert.match(html, /任何兼容标准聊天接口的大模型/);
});

// 首页、i18n 词条、README 不点名具体商业模型或云服务；具体配置写在 docs/QUICKSTART.md（#100）
test('首页、i18n、README 不点名具体商业模型或云服务', () => {
  const MODEL = /qwen|百炼|通义|千问|阿里云|aliyun|alibaba|bailian|dashscope|paraformer|cosyvoice/i;
  const pub = [
    path.join(ROOT, 'site/index.html'),
    path.join(ROOT, 'site/assets/js/i18n.js'),
    ...fs.readdirSync(ROOT).filter((f) => /^README/i.test(f)).map((f) => path.join(ROOT, f)),
  ];
  const hits = [];
  for (const f of pub) {
    fs.readFileSync(f, 'utf8').split('\n').forEach((l, i) => { const m = l.match(MODEL); if (m) hits.push(`${path.relative(ROOT, f)}:${i + 1}: ${m[0]}`); });
  }
  assert.deepEqual(hits, []);
});
