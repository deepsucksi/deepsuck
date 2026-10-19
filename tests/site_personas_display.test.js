'use strict';
// #60 站点展示层：人设名单、人数以 site/assets/core/personas.json 为准；
// 页面、英文翻译、分享图模板里不再出现已下线的李大爷，也不写具体年龄。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const C = require('../site/assets/core/personas.json');
const N = C.personas.length;

// 展示层文件（不含 core-data.js：它由 personas.json 生成，下面直接查数据源）
const DISPLAY = ['site/index.html', 'site/demo.html', 'site/intel.html', 'site/404.html', 'site/assets/js/i18n.js',
  'site/assets/js/demo.js', 'site/assets/js/home.js', 'site/assets/js/hero-chat.js', 'scripts/og/og.html']
  .filter((p) => fs.existsSync(path.join(ROOT, p)));

test('展示层不出现李大爷 / Uncle Li / persona=li，也不写“N 岁”', () => {
  for (const p of DISPLAY) {
    const s = read(p);
    assert.ok(!/李大爷|Uncle Li|persona=li\b/.test(s), p);
    assert.ok(!/\d+\s*岁/.test(s), p);
  }
});

test('personas.json 的人设简介不写具体年龄（页面直接展示 tagline）', () => {
  for (const p of C.personas) assert.ok(!/\d+\s*岁|[一二三四五六七八九十]+岁/.test(p.tagline), p.id);
});

test('沙盒的 og / twitter 描述与英文翻译里的人设数与 personas.json 一致', () => {
  const demo = read('site/demo.html');
  const zh = demo.match(/× (\d+) 个“受害人”人设/g) || [];
  assert.equal(zh.length, 2);
  for (const m of zh) assert.equal(Number(m.match(/\d+/)[0]), N, m);
  assert.match(read('site/assets/js/i18n.js'), new RegExp(`× ${N} "victim" personas`));
  for (const p of C.personas) assert.ok(demo.includes(p.name), p.name); // meta description 列出全部人设
});

test('分享图模板不写死人设人数与名单（由 scripts/og.js 从 personas.json 注入）', () => {
  const html = read('scripts/og/og.html');
  assert.ok(!/\d+\s*个人设/.test(html));
  assert.match(html, /window\.__OG/);
  assert.match(read('scripts/og.js'), /personas\.json|readCore\('personas'\)/);
});
