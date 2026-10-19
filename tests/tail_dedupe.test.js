// #153：跨轮去重 dedupeTail（与 Python deepsuck.engine.dedupe_tail 同一组用例 tests/fixtures/tail_dedupe.json）
const test = require('node:test');
const assert = require('node:assert');
const E = require('../site/assets/js/engine.js');
const FIX = require('./fixtures/tail_dedupe.json');

test('fixture cases', () => {
  for (const c of FIX.cases) {
    assert.strictEqual(E.dedupeTail(c.text, c.recent, c.persona), c.expected, c.text);
    assert.strictEqual(E.tailSentence(c.text), c.tail, c.text);
    const out = c.expected;
    assert.strictEqual(E.dedupeTail(out, c.recent, c.persona), out);
  }
});

test('pure: input not mutated, window of 3', () => {
  const recent = ['你再说一遍。', 'a', 'b', 'c'];
  assert.strictEqual(E.dedupeTail('你再说一遍。', recent), '你再说一遍。');
  assert.deepStrictEqual(recent, ['你再说一遍。', 'a', 'b', 'c']);
});

test('demo wires dedupe for LLM replies only', () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '../site/assets/js/demo.js'), 'utf8');
  assert.match(src, /dedupeTail\(reply, recentTails\(s\), s\.persona\.id\)/);
});

test('no new lead phrases; fallback only from approved lines', () => {
  const PJ = require('../site/assets/core/personas.json');
  assert.ok(!('lead' in PJ.tailDedupe) && !('particles' in PJ.tailDedupe));
  const src = require('fs').readFileSync(require('path').join(__dirname, '../site/assets/core/personas.json'), 'utf8');
  assert.ok(!src.includes('我是说，') && !src.includes('还是那句，'));
  const pool = PJ.personas.find((p) => p.id === 'chen').templates.ask_repeat.filter((x) => typeof x === 'string' && !x.includes('{'));
  const out = E.dedupeTail(pool[0], pool.slice(0, 3), 'chen');
  assert.ok(pool.slice(3).includes(out), out);
  assert.strictEqual(E.dedupeTail(pool[0], pool.slice(0, 3)), '');
});

// #188：兜底只从 tailDedupe.fallbackPick 标了的 ask_repeat 里挑（不改台词原文；Python / 语音同一份配置，见 python/tests/test_tail_dedupe.py）
const SCENE_RE = /按钮|红的|绿的|页面|菜单|第[一二三四五六七八九两\d]步|打开|登录|填|链接|APP|发|消息|一条|一段|那段|字/;
const PJ188 = require('../site/assets/core/personas.json');
const picked = (pid) => { const lst = PJ188.personas.find((p) => p.id === pid).templates.ask_repeat; return PJ188.tailDedupe.fallbackPick[pid].map((i) => lst[i]); };

test('#188 fallbackPick：每个人设都有、下标有效、只标不带场景 / 变量、最多一位数字的已批句', () => {
  for (const p of PJ188.personas) {
    const pick = PJ188.tailDedupe.fallbackPick[p.id];
    assert.ok(Array.isArray(pick) && pick.length >= 1, p.id);
    for (const i of pick) {
      const x = p.templates.ask_repeat[i];
      assert.ok(typeof x === 'string' && !x.includes('{'), p.id + i);
      assert.ok(!SCENE_RE.test(x), x);
      assert.ok((x.match(/[0-9０-９]/g) || []).length <= 1 && E.vagueDigits(x) === x, x);
    }
  }
});

test('#188 删空兜底只出标了的句子，「哪个按钮，红的绿的？」不会出现', () => {
  for (const p of PJ188.personas) {
    const ok = picked(p.id);
    const all = p.templates.ask_repeat.filter((x) => typeof x === 'string');
    for (const t of ['行。', '好的吧', '你再说一遍。', '嗯…我听着呢', '我看看。']) {
      const out = E.dedupeTail(t, [t], p.id);
      assert.ok(ok.includes(out), p.id + ' ' + out);
    }
    // 刚说过的标记句不再挑；标记句都说过了就返回空串（不回退到带场景的句子）
    const out = E.dedupeTail('行。', ['行。'].concat(ok.slice(0, 2)), p.id);
    assert.ok(out === '' || (ok.includes(out) && !ok.slice(0, 2).includes(out)), out);
    assert.ok(!all.filter((x) => !ok.includes(x)).includes(E.dedupeTail('行。', ['行。'], p.id)));
  }
  assert.ok(!picked('wang').includes('哪个按钮？红的绿的？你说清楚点阿姨照着按。'));
});
