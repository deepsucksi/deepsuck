/*!
 * DeepSuck — personas.js
 * 机器人人设与话术模板。模板变量：{call} 对骗子的称呼，{intel} 刚拿到的情报（自然复述：尾号 / 姓氏 / 那个网址，不念星号），{ask} 追问下一条情报。
 * 底线：人设永远不给出真实的验证码、卡号、密码、身份证号；只"假装配合"，拖延并套取对方信息。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/personas.json') : root.DeepSuck.coreData.personas;
  var mod = factory(C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.personas = mod; }
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';
  // 人设与拖延台词库见 site/assets/core/personas.json。
  // 模板可以是字符串，或 { when: '正则源码', t: '文本' }：仅当骗子本轮消息命中 when 时可用（且优先），加载时编译为 { re, t }。
  function compile(list) {
    return list.map(function (it) { return typeof it === 'string' ? it : { re: new RegExp(it.when), t: it.t }; });
  }
  var PERSONAS = C.personas.map(function (p) {
    var templates = {};
    Object.keys(p.templates).forEach(function (k) { templates[k] = compile(p.templates[k]); });
    return Object.assign({}, p, { templates: templates });
  });
  var BY_ID = {};
  PERSONAS.forEach(function (p) { BY_ID[p.id] = p; });
  // 别名 → 人设 id（personas.json 的 aliases：li → wang，xiaochen / mom → chen，shop_owner → zheng）
  var PERSONA_ALIASES = C.aliases || {};
  function resolveId(id) { id = String(id || ''); return Object.prototype.hasOwnProperty.call(PERSONA_ALIASES, id) ? PERSONA_ALIASES[id] : id; }
  // 拖延类意图在"骗子侧"估算会额外耗费的等待时间（秒）
  var STALL_SECONDS = C.stallSeconds;
  // 每个意图给大模型的策略提示（llm.js 与 Python voice 端共用）
  var INTENT_HINTS = C.intentHints;
  // 复述情报给骗子听的说法（不念星号）；engine.js speakIntel 使用
  var SPEAK_INTEL = C.speakIntel;
  return { PERSONAS: PERSONAS, BY_ID: BY_ID, PERSONA_ALIASES: PERSONA_ALIASES, resolveId: resolveId, STALL_SECONDS: STALL_SECONDS, INTENT_HINTS: INTENT_HINTS, SPEAK_INTEL: SPEAK_INTEL };
});
