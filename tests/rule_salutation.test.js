'use strict';
// #114：规则引擎回复里的称呼 {call} 只按骗子已经说出口的场景取（与 python/tests/test_rule_salutation.py 同一口径）。
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const P = require('../site/assets/js/personas.js');
const S = require('../site/assets/js/scenarios.js');
const { mulberry32 } = require('../site/assets/js/humanize.js');

const NEUTRAL = ['喂，你好，听得到吗？', '是本人吧？我这边找你有点事。', '你现在方便说话吗？', '我等你一下。'];

test('no telling salutation before the scammer names a scene', () => {
  P.PERSONAS.forEach(function (p) {
    const bad = Object.keys(p.call).map(function (k) { return p.call[k]; })
      .filter(function (c) { return E.scenesIn(c).length; }).concat(['领导', '经理']);
    S.SCENARIOS.forEach(function (sc) {
      [1, 7, 42].forEach(function (seed) {
        const s = new E.Session({ scenario: sc.id, persona: p.id, rng: mulberry32(seed), now: function () { return 0; } });
        assert.equal(s.salutation(), '');
        s.opening(); // 开场白按场景选（已批准台词），不在本 issue 范围；这里只看称呼
        const texts = [];
        NEUTRAL.forEach(function (t) { texts.push(s.ruleReply(s.ingest(t)).text); });
        assert.deepEqual(s.heardScenes(), []);
        texts.forEach(function (x) {
          const hit = bad.filter(function (c) { return x.includes(c) && !x.includes('冒充' + c); });
          assert.deepEqual(hit, [], p.id + '/' + sc.id + '/' + seed + ': ' + x);
        });
      });
    });
  });
});

test('salutation follows the heard scene, not the backend scenario', () => {
  const s = new E.Session({ scenario: 'refund', persona: 'wang', rng: mulberry32(1), now: function () { return 0; } });
  s.ingest('我是市公安局的民警，你的卡涉嫌洗钱。');
  assert.deepEqual(s.heardScenes(), ['police']);
  assert.equal(s.fill('{call}你说慢一点'), '警察同志你说慢一点');
  const s2 = new E.Session({ scenario: 'police', persona: 'wang', rng: mulberry32(1), now: function () { return 0; } });
  assert.equal(s2.fill('{call}你说慢一点'), '你说慢一点');
  const s3 = new E.Session({ scenario: 'task', persona: 'chen', rng: mulberry32(1), now: function () { return 0; } });
  s3.ingest('在家也能做的兼职，点赞一单返几块钱，日结。');
  assert.equal(s3.salutation(), '');
  s3.ingest('我是平台客服，带你做任务。');
  assert.equal(s3.salutation(), '客服');
  assert.deepEqual(E.heardScenes(['你开过校园贷账户']), ['campus', 'loan']);
});
