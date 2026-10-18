/*!
 * DeepSuck — tactics.js
 * 诈骗话术分类器：基于关键词/正则的可解释规则，输出命中的话术标签与风险分。
 * 规则刻意保持简单透明，方便社区审阅与补充（见 CONTRIBUTING.md）。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/tactics.json') : root.DeepSuck.coreData.tactics;
  var N = isNode ? require('./normalize.js') : root.DeepSuck.normalize;
  var mod = factory(C, N);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.tactics = mod; }
})(typeof self !== 'undefined' ? self : this, function (C, N) {
  'use strict';

  // 规则数据见 site/assets/core/tactics.json（关键词正则源码，JS/Python 通用）
  var TACTICS = C.tactics.map(function (t) {
    return { id: t.id, label: t.label, weight: t.weight, cap: t.cap || 3, weak: !!t.weak, re: new RegExp(t.pattern) };
  });

  var BY_ID = {};
  TACTICS.forEach(function (t) { BY_ID[t.id] = t; });

  /**
   * classify(text) -> [{ id, label, weight, match }]
   */
  function classify(text) {
    var s = N.normalize(String(text || '')).text; // 先还原 "微 信""扣扣" 等去武装写法
    var hits = [];
    TACTICS.forEach(function (t) {
      var m = s.match(t.re);
      if (m) hits.push({ id: t.id, label: t.label, weight: t.weight, match: m[0] });
    });
    return hits;
  }

  /** 根据累计命中次数计算 0–100 风险分 */
  function riskScore(counts) {
    var raw = 0, strong = false;
    Object.keys(counts || {}).forEach(function (id) {
      var t = BY_ID[id];
      if (!t || !(counts[id] > 0)) return;
      raw += t.weight * Math.min(t.cap, counts[id]); // cap：同一话术最多累计几次
      if (!t.weak) strong = true;
    });
    if (!strong) raw /= 2; // 只有弱信号（如“客服”“尽快”）时减半：正常客服来电也常见
    return Math.min(100, Math.round(100 * (1 - Math.exp(-raw / 18))));
  }

  return { TACTICS: TACTICS, BY_ID: BY_ID, classify: classify, riskScore: riskScore };
});
