/*!
 * DeepSuck — cardbin.js
 * 银行卡 BIN（发卡行识别号）本地查询：按卡号前缀（最长匹配）判断发卡行与卡种，不联网、卡号不外传。
 * 数据：site/assets/core/cardbin.json，来自 hexindai/bcbc（MIT），由 scripts/fetch-cardbin.js 生成。
 * BIN 表并非官方注册表，结果仅供参考（收款卡常为被冒用/出租的普通人账户）。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/cardbin.json') : root.DeepSuck.coreData.cardbin;
  var mod = factory(C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.cardbin = mod; }
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';

  var BINS = C.bins, BANKS = C.banks, TYPES = C.types;

  function info(bin, opt, length) {
    return {
      bin: bin, bankCode: opt[0], bank: BANKS[opt[0]] || opt[0], cardType: opt[1], cardTypeName: TYPES[opt[1]] || opt[1],
      length: opt[2], lengthOk: opt[2] === length
    };
  }

  /**
   * lookup(cardNo) -> { bin, bankCode, bank, cardType, cardTypeName, length, lengthOk } | null
   * 从最长前缀（10 位）到最短（3 位）查找，优先返回卡号长度也吻合的条目；都不吻合时返回最长前缀命中（lengthOk=false）。
   */
  function lookup(cardNo) {
    var d = String(cardNo == null ? '' : cardNo).replace(/\D/g, '');
    if (d.length < 12) return null;
    var fallback = null;
    for (var n = Math.min(10, d.length); n >= 3; n--) {
      var p = d.slice(0, n), opts = BINS[p];
      if (!opts) continue;
      for (var i = 0; i < opts.length; i++) if (opts[i][2] === d.length) return info(p, opts[i], d.length);
      if (!fallback) fallback = info(p, opts[0], d.length);
    }
    return fallback;
  }

  return { lookup: lookup, SOURCE: C.source, size: Object.keys(BINS).length };
});
