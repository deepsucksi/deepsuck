'use strict';
// #11 人设统一：site/assets/core/personas.json 是人设唯一数据源。
// 首页卡片（index.html data-persona 与标签）、home.js 轮播 CAST、hero-chat 示例、沙盒 demo 选项、
// 体验页（voice/static）选项都与它一致：同一组 id、同一编号 / 身份 / 头像。
// 跨语言的一致性（/api/config、评测人设集合）见 voice/tests/test_personas_unify.py。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const C = require('../site/assets/core/personas.json');
const P = require('../site/assets/js/personas.js');

const IDS = ['wang', 'chen', 'lin', 'zheng'];
const ROSTER = [
  ['wang', '01', '王阿姨', '退休老人', 'retired'],
  ['chen', '02', '小陈妈妈', '宝妈', 'parent'],
  ['lin', '03', '小林', '刚毕业学生', 'graduate'],
  ['zheng', '04', '郑老板', '个体小老板', 'owner'],
];

test('personas.json：四位人设，顺序、编号、名字、身份、头像与首页一一对应', () => {
  assert.deepEqual(C.personas.map((p) => p.id), IDS);
  for (const [id, no, name, role, photo] of ROSTER) {
    const p = C.personas.find((x) => x.id === id);
    assert.equal(p.no, no); assert.equal(p.name, name); assert.equal(p.role, role);
    assert.equal(p.photo, `assets/brand/round6/${photo}-400.webp`);
    assert.ok(fs.existsSync(path.join(ROOT, 'site', p.photo)), p.photo);
    assert.ok(p.avatar && p.tagline);
  }
});

test('首页角色 id 集合 == personas.json == home.js CAST == 沙盒选项', () => {
  const html = read('site/index.html');
  const cards = [...html.matchAll(/class="team-member[^"]*" data-persona="([a-z]+)"[\s\S]*?round6\/([a-z]+)-800\.webp[\s\S]*?team-number">(\d+)<\/span><b[^>]*>([^<]+)<\/b>/g)]
    .map((m) => [m[1], m[3], m[4], m[2]]);
  assert.deepEqual(cards, ROSTER.map(([id, no, , role, photo]) => [id, no, role, photo]));
  const home = read('site/assets/js/home.js');
  const cast = [...home.slice(home.indexOf('var CAST'), home.indexOf('];', home.indexOf('var CAST'))).matchAll(/id: '([a-z]+)', name: '([^']+)'/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(cast, ROSTER.map((r) => [r[0], r[2]]));
  assert.deepEqual(P.PERSONAS.map((p) => p.id), IDS);
  // 首页“四位人设”一行
  const line = html.slice(html.indexOf('class="personas-line"'), html.indexOf('</div>', html.indexOf('class="personas-line"')));
  const tags = [...line.matchAll(/<span class="tag"[^>]*>([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.deepEqual(tags, ROSTER.map(([, no, name, role]) => `${no} ${name} · ${role}`));
  assert.ok(!/李大爷/.test(line));
});

test('hero-chat 示例对话的人设名都在 personas.json 里', () => {
  const src = read('site/assets/js/hero-chat.js');
  const names = new Set(C.personas.map((p) => p.name));
  const used = [...src.matchAll(/title: "[^"]* · ([^"]+)"/g)].map((m) => m[1]);
  assert.ok(used.length >= 4);
  for (const n of used) assert.ok(names.has(n), n);
});

test('首页卡片跳转带 persona 参数：沙盒 demo.html?persona=、体验页 ?persona=', () => {
  const home = read('site/assets/js/home.js');
  assert.match(home, /'persona=' \+ c\.id/);
  assert.match(home, /LIVE_URL \+ '\?persona=' \+ c\.id/);
});

test('别名映射：li → wang（李大爷下线），xiaochen / mom → chen，shop_owner → zheng', () => {
  assert.deepEqual(C.aliases, { li: 'wang', xiaochen: 'chen', mom: 'chen', shop_owner: 'zheng' });
  assert.equal(P.resolveId('li'), 'wang');
  assert.equal(P.resolveId('xiaochen'), 'chen');
  assert.equal(P.resolveId('mom'), 'chen');
  assert.equal(P.resolveId('shop_owner'), 'zheng');
  assert.equal(P.resolveId('chen'), 'chen');
  for (const v of Object.values(C.aliases)) assert.ok(IDS.includes(v));
  for (const k of Object.keys(C.aliases)) assert.ok(!IDS.includes(k));
});

test('体验页选项：按 /api/config 渲染编号、身份、头像，支持 ?persona= 直达', () => {
  const js = read('voice/static/voice.js');
  const html = read('voice/static/index.html');
  assert.match(html, /id="persona"[^>]*role="radiogroup"/);
  for (const k of ['p.no', 'p.role', 'p.photo', 'aliases']) assert.ok(js.includes(k), k);
  assert.match(js, /get\("persona"\)/);
});

test('人设资料里不出现李大爷；新人设不写年龄，不用感叹号与 emoji（王阿姨的资料本次不动）', () => {
  const s = JSON.stringify(C.personas);
  assert.ok(!s.includes('李大爷'));
  for (const p of C.personas.filter((x) => x.id !== 'wang')) {
    const blob = JSON.stringify([p.tagline, p.voiceStyle || [], (p.voiceShots || []).map((x) => x.reply), p.prompt]);
    assert.ok(!/\d+\s*岁/.test(blob), p.id);
    assert.ok(!/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/u.test(blob), p.id);
  }
  for (const id of ['chen', 'zheng']) {
    const p = C.personas.find((x) => x.id === id);
    assert.ok(!/[!！]/.test(JSON.stringify([p.voiceStyle, p.voiceShots.map((x) => x.reply)])), id);
  }
});
