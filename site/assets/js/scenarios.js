/*!
 * DeepSuck — scenarios.js
 * 沙盒场景定义：访客扮演骗子，机器人扮演"潜在受害人"。
 * goals = 机器人在周旋中希望诱导对方暴露的情报类型（按优先级）。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/scenarios.json') : root.DeepSuck.coreData.scenarios;
  var mod = factory(C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.scenarios = mod; }
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';
  // 场景数据见 site/assets/core/scenarios.json。样例台词中的账号、电话、地址、域名均为虚构/测试数据。
  var SCENARIOS = C.scenarios;
  var BY_ID = {};
  SCENARIOS.forEach(function (s) { BY_ID[s.id] = s; });
  return { SCENARIOS: SCENARIOS, BY_ID: BY_ID };
});
