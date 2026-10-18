'use strict';
// 首页人设轮播计时（site/assets/js/carousel.js）：自动前进、悬停/焦点/不可见/后台/暂停/减少动态时停、手动选择后继续。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRotator } = require('../site/assets/js/carousel.js');

function clock() {
  let now = 0, seq = 0; const q = new Map();
  return {
    setTimeout: (f, ms) => { const id = ++seq; q.set(id, { f, at: now + ms }); return id; },
    clearTimeout: (id) => { q.delete(id); },
    tick(ms) {
      const end = now + ms;
      for (;;) {
        let next = null;
        for (const [id, t] of q) if (t.at <= end && (!next || t.at < next[1].at)) next = [id, t];
        if (!next) break;
        q.delete(next[0]); now = next[1].at; next[1].f();
      }
      now = end;
    },
    pending: () => q.size
  };
}
function make(extra) {
  const c = clock(); const seen = [];
  const r = createRotator(Object.assign({ count: 4, delay: 6000, onChange: (i, manual) => seen.push([i, manual]), setTimeout: c.setTimeout, clearTimeout: c.clearTimeout }, extra));
  return { c, r, seen };
}

test('可见后每 6 秒自动前进一张，循环回到第一张', () => {
  const { c, r, seen } = make();
  c.tick(20000); assert.equal(seen.length, 0, '不可见时不动');
  r.set('visible', true);
  c.tick(5999); assert.equal(r.state.active, 0);
  c.tick(1); assert.equal(r.state.active, 1);
  c.tick(18000); assert.equal(r.state.active, 0);
  assert.ok(seen.every(([, m]) => m === false));
});

test('悬停、键盘焦点、页面后台、用户暂停时停住，恢复后重新计满一个周期', () => {
  for (const key of ['hover', 'focus', 'hidden', 'paused']) {
    const { c, r } = make();
    r.set('visible', true); c.tick(4000);
    r.set(key, true); c.tick(30000); assert.equal(r.state.active, 0, key);
    assert.equal(c.pending(), 0, key);
    r.set(key, false); c.tick(5999); assert.equal(r.state.active, 0, key);
    c.tick(1); assert.equal(r.state.active, 1, key);
  }
});

test('减少动态：不自动播放，但手动切换照常', () => {
  const { c, r, seen } = make();
  r.set('reduced', true); r.set('visible', true);
  c.tick(60000); assert.equal(r.state.active, 0); assert.equal(r.running(), false);
  r.go(2); assert.equal(r.state.active, 2); assert.deepEqual(seen.at(-1), [2, true]);
  c.tick(60000); assert.equal(r.state.active, 2);
});

test('手动选择后从该张继续自动轮播；越界下标取模', () => {
  const { c, r } = make();
  r.set('visible', true); c.tick(5000);
  r.go(3); c.tick(5999); assert.equal(r.state.active, 3);
  c.tick(1); assert.equal(r.state.active, 0);
  r.go(-1); assert.equal(r.state.active, 3);
});

test('home.js 接线：用 carousel.js、6 秒、减少动态与暂停按钮；index.html 先加载 carousel.js', () => {
  const root = path.join(__dirname, '..', 'site');
  const home = fs.readFileSync(path.join(root, 'assets/js/home.js'), 'utf8');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'assets/css/home.css'), 'utf8');
  assert.match(home, /DeepSuckCarousel\.createRotator/);
  assert.match(home, /prefers-reduced-motion: reduce/);
  assert.match(home, /delay:\s*6000/);
  assert.match(home, /focus-visible/);
  const a = html.indexOf('src="assets/js/carousel.js"'), b = html.indexOf('src="assets/js/home.js"');
  assert.ok(a > 0 && a < b, 'carousel.js 在 home.js 之前');
  assert.match(css, /team-progress 6s/);
});
