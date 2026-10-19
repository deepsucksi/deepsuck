'use strict';
// #4 不抢话（网页大模型模式，llm.js；与 voice/tests/test_scene_leak.py 同一口径）：
// 系统提示词里不放场景名、描述和按后台场景挑的称呼；称呼、想要的情报、套情报类意图只按对方已经说过的话来。
const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../site/assets/js/scenarios.js');
const P = require('../site/assets/js/personas.js');
const L = require('../site/assets/js/llm.js');

const CUES = S.HEARD_CUES;
const NEUTRAL = ['喂，你好，听得到吗？', '是本人吧？我这边找你有点事。'];
const TELLING_CALLS = ['警察同志', '领导', '经理', '警官'];
function scenesIn(t) { return Object.keys(CUES.scenes).filter(function (k) { return new RegExp(CUES.scenes[k]).test(t); }); }

test('neutral opening: no scenario name, cue, telling call, wish list or elicit hint', () => {
  P.PERSONAS.forEach(function (p) {
    S.SCENARIOS.forEach(function (sc) {
      const sys = L.buildMessages({
        persona: p.id, scenario: sc.id, hint: 'elicit_wallet', missing: sc.goals,
        transcript: NEUTRAL.map(function (t) { return { role: 'scammer', text: t }; })
      })[0].content;
      assert.ok(!sys.includes(sc.title) && !sys.includes(sc.desc), p.id + '/' + sc.id);
      assert.deepEqual(scenesIn(sys), [], p.id + '/' + sc.id);
      assert.ok(!TELLING_CALLS.some(function (c) { return sys.includes(c); }), p.id + '/' + sc.id);
      assert.ok(sys.includes('先不用称呼对方') && !/对方已经提到、但还没说清楚|仍希望诱导/.test(sys), p.id + '/' + sc.id);
      assert.ok(!sys.includes(P.INTENT_HINTS.elicit_wallet), p.id + '/' + sc.id);
    });
  });
});

test('call and wish list follow what the scammer said', () => {
  const sys = L.buildMessages({
    persona: 'wang', scenario: 'refund', hint: 'elicit_account', missing: ['bank', 'url', 'wallet'],
    transcript: [{ role: 'scammer', text: '我是市公安局的民警，你的卡涉嫌洗钱，钱要转到安全账户' }]
  })[0].content;
  assert.ok(sys.includes('称呼对方为"' + P.BY_ID.wang.call.police + '"'));
  assert.ok(sys.includes('收款账户') && !sys.includes('钱包地址') && !sys.includes('网址或 APP'));
  assert.deepEqual(L.heardScenes(['你好', '我是派出所的', '你有一笔贷款额度']), ['police', 'loan']);
  assert.deepEqual(L.heardScenes(['你开过校园贷']), ['campus', 'loan']);
});

test('call that itself names another scene is not used', () => {
  // 小陈妈妈在刷单场景里叫对方“客服”，“客服”会带出退款场景，对方没说客服时不用
  const sys = L.systemPrompt(P.BY_ID.chen, S.BY_ID.task, 'generic', [], ['在家也能做的兼职，点赞一单返几块钱']);
  assert.ok(!sys.includes('"客服"') && sys.includes('先不用称呼对方'));
});
