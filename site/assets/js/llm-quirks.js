/*!
 * DeepSuck — llm-quirks.js
 * 个别服务商的请求参数差异（#166）。llm.js 按规则不写服务商名（tests/brand_copy.test.js），这里单独放。
 * thinkingOff：百炼（DashScope）兼容接口上的 qwen3.x（如 qwen3.8-flash）默认开思考，要显式发 enable_thinking: false；
 * 其他服务商的接口可能拒绝不认识的字段，所以只在型号以 qwen 开头或接口地址含 dashscope 时才带。
 * Apache-2.0
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.llmQuirks = mod; }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var THINKING_OFF = { model: /^\s*qwen/i, baseUrl: /dashscope/i };
  /** 直连时是否要显式关思考：型号以 qwen 开头，或接口地址含 dashscope */
  function thinkingOff(model, baseUrl) {
    return THINKING_OFF.model.test(String(model || '')) || THINKING_OFF.baseUrl.test(String(baseUrl || ''));
  }
  return { thinkingOff: thinkingOff };
});
