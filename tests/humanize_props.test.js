'use strict';
// #129：跑题句不编道具、对方没开口不插跑题句、文字回复不带表情；与 personas/tests/test_humanize_props.py 同规则。
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const H = require('../site/assets/js/humanize.js');
const C = require('../site/assets/js/core-data.js');

const PERSONAS = ['wang', 'chen', 'lin', 'zheng', 'retiree', 'mom', 'graduate', 'shop_owner'];
const EMOJI = /[\u{1F300}-\u{1FAFF}\u2600-\u27BF\uFE0F]|\[(?:强|玫瑰|握手|抱拳|微笑)\]/u;

test('跑题句池与 Python 一致，且不含编出来的道具', () => {
  const py = JSON.parse(execFileSync('python3', ['-c',
    'import json,sys; sys.path[:0]=[".","python"]\nfrom personas.humanize import Humanizer\nprint(json.dumps({p: Humanizer(profile=p, seed=1).digressions for p in ' + JSON.stringify(PERSONAS) + '}, ensure_ascii=False))'],
  { cwd: path.join(__dirname, '..') }).toString());
  for (const p of PERSONAS) {
    const d = new H.Humanizer({ profile: p, seed: 1 }).digressions;
    assert.deepEqual(d, py[p], p);
    assert.ok(d.length >= 3, p);
    for (const x of d) assert.ok(!/药|买菜|广场舞|外孙/.test(x), p + ' ' + x);
  }
});

test('对方没开口不插跑题句；输出不带表情', () => {
  for (const p of PERSONAS) {
    for (let seed = 0; seed < 40; seed++) {
      const h = new H.Humanizer({ profile: p, seed, weights: { digress: 50 } });
      assert.ok(h.apply('喂？哪位').ops.indexOf('digress') < 0, p);
      const r = h.apply('好的，你说吧，我听着。', '你好，我这边有点事', 'generic');
      assert.ok(!EMOJI.test(r.text), p + ' ' + r.text);
      assert.ok(r.ops.indexOf('emoji') < 0);
    }
  }
  assert.ok([...Array(20).keys()].some((s) => new H.Humanizer({ profile: 'wang', seed: s, weights: { digress: 50 } }).apply('嗯，你说。', '喂，你好', 'generic').ops.indexOf('digress') >= 0));
  assert.ok(C);
});
