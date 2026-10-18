'use strict';
// 语音演示页（voice/static/index.html，R11 视觉）：voice.js / playbook.js 用到的元素都在；顺序为 参考话术 → 通话 → 看板；品牌文件走 /static/brand/。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const dir = path.join(__dirname, '..', 'voice', 'static');
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');

function ids(js) { return [...new Set([...js.matchAll(/\$\("([A-Za-z]+)"\)/g)].map((m) => m[1]))]; }

test('voice.js 与 playbook.js 引用的 id 都在页面里', () => {
  for (const f of ['voice.js', 'playbook.js']) {
    const js = fs.readFileSync(path.join(dir, f), 'utf8');
    const need = ids(js);
    assert.ok(need.length > 3, f);
    for (const id of need) assert.match(html, new RegExp(`id="${id}"`), `${f} → #${id}`);
    assert.match(html, new RegExp(`<script src="/static/${f.replace('.', '\\.')}"`));
  }
});

test('DOM 顺序：参考话术面板 → 通话 → 实时看板；桌面网格把面板放在看板上方', () => {
  const a = html.indexOf('id="playbook"'), b = html.indexOf('class="card call"'), c = html.indexOf('class="card board"');
  assert.ok(a > 0 && a < b && b < c, `${a} ${b} ${c}`);
  assert.match(html, /grid-template-areas:"call pb" "call dash"/);
});

test('R11 品牌：顶栏用听筒标志与字标、Manrope 字体，不提 DeepSeek，无表情符号', () => {
  for (const ref of ['/static/brand/symbol.png', '/static/brand/wordmark.svg', '/static/brand/Manrope.ttf', '#111313', '#ed7950']) assert.ok(html.includes(ref), ref);
  assert.ok(!/deepseek/i.test(html));
  assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(html));
});
