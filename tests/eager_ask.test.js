// #194：不一口答应就紧跟着要号码、户名——规则句只在 personas.json eagerAsk.rule 一处，网页 llm.js 硬性规则 8 从它拼
// （与 voice/tests/test_eager_ask.py 对应：语音 FOLLOW_UP_RULE 同一句，只在每轮变化的部分）
const test = require('node:test');
const assert = require('node:assert');
const P = require('../site/assets/js/personas.js');
const S = require('../site/assets/js/scenarios.js');
const L = require('../site/assets/js/llm.js');
const PJ = require('../site/assets/core/personas.json');

test('eagerAsk.rule exported and used in web rule 8', () => {
  const rule = PJ.eagerAsk.rule;
  assert.ok(typeof rule === 'string' && rule.includes('户名'));
  assert.strictEqual(P.EAGER_ASK.rule, rule);
  for (const id of ['wang', 'chen', 'lin', 'zheng']) {
    const sp = L.systemPrompt(P.BY_ID[id], S.BY_ID.refund, 'generic', []);
    const line = sp.split('\n').find((x) => x.startsWith('8. '));
    assert.ok(line && line.includes(rule), id);
    assert.strictEqual(sp.split(rule).length, 2, id); // 只出现一次
  }
});

test('llm.js has no second copy of the eagerAsk sentence', () => {
  const src = require('fs').readFileSync(require.resolve('../site/assets/js/llm.js'), 'utf8');
  assert.ok(!src.includes(PJ.eagerAsk.rule));
});
