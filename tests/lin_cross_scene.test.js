'use strict';
// 小林两句会串场景的台词（EVAL.md 记录的露馅）：改成不依赖场景的说法，防止回退。
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../site/assets/core/personas.json');

test('小林 coop_step / campus_stall 不含只属于单一场景的说法', () => {
  const lin = C.personas.find((p) => p.id === 'lin');
  const txt = (x) => (typeof x === 'string' ? x : x.t);
  const coop = lin.templates.coop_step.map(txt).join('\n');
  assert.ok(!/第一单|点赞/.test(coop), '刷单说法会串到杀猪盘/退款');
  for (const t of lin.templates.campus_stall.filter((x) => typeof x === 'string')) {
    assert.ok(!/文号|国家规定|校园贷|网贷/.test(t), '无条件的 campus_stall 句会出现在非校园贷场景：' + t);
  }
});
