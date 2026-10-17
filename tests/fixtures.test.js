'use strict';
// 共享测试夹具（tests/fixtures/*.json）：JS 实现必须与夹具一致；Python 实现由 python/tests 用同一批夹具校验。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const gen = require('../scripts/gen-fixtures.js');
const { mulberry32 } = require('../scripts/lib/rng.js');

test('tests/fixtures/*.json 与 JS 实现同步（改了规则请运行 npm run fixtures 并检查 diff）', () => {
  const files = gen.render();
  for (const f of Object.keys(files)) {
    assert.equal(fs.readFileSync(path.join(gen.DIR, f), 'utf8'), files[f], f + ' 已过期');
  }
});

test('mulberry32 可复现（与 python/deepsuck/rng.py 一致）', () => {
  const r = mulberry32(42);
  const xs = [r(), r(), r()].map((x) => Math.round(x * 1e9));
  assert.deepEqual(xs, [601103752, 448290559, 852465793]);
});
