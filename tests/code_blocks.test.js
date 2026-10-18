'use strict';
// 首页代码块（R11）：两块（快速开始 + 目录结构）、目录与仓库实际结构一致、注释有英文、不提其他公司。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const i18n = fs.readFileSync(path.join(ROOT, 'site/assets/js/i18n.js'), 'utf8');

test('代码块：两块 figure.codeblock，旧的 pre.code 已移除，快速开始带复制按钮', () => {
  assert.equal((html.match(/<figure class="codeblock/g) || []).length, 2);
  assert.ok(!/<pre class="code">/.test(html));
  assert.match(html, /class="cb-copy" data-copy="cbQs"/);
  assert.match(html, /id="cbQs"/);
});

test('目录结构里列出的路径在仓库里都存在', () => {
  const tree = html.slice(html.indexOf('codeblock tree'), html.indexOf('</figure>', html.indexOf('codeblock tree')));
  const paths = [...tree.matchAll(/<span class="k">([^<]+\/)<\/span>/g)].map((m) => m[1]);
  assert.ok(paths.includes('voice/') && paths.includes('python/deepsuck/'));
  for (const p of paths) {
    const full = p.startsWith('assets/') ? path.join(ROOT, 'site', p) : path.join(ROOT, p);
    assert.ok(fs.existsSync(full), p);
  }
});

test('代码块注释都有英文翻译；不提其他公司或产品', () => {
  const keys = [...html.matchAll(/data-i18n="(cb\.[^"]+)"/g)].map((m) => m[1]);
  assert.ok(keys.length >= 10);
  for (const k of keys) assert.ok(i18n.includes(`'${k}':`), k);
  const blocks = html.slice(html.indexOf('<figure class="codeblock'), html.lastIndexOf('</figure>'));
  assert.ok(!/openai|apate|deepseek/i.test(blocks));
});
