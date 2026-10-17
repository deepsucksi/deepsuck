/*!
 * DeepSuck — normalize.js
 * 中文"去武装"写法规范化：骗子常把联系方式写成 "微 信"、"V信"、"扣扣"、"xxx点com"、"幺三九…"、"１３９"、"1 3 9 0 …" 来躲避关键词过滤。
 * 在提取情报与识别话术之前先规范化；同时维护 规范化文本 → 原文 的位置映射，确保脱敏时替换的是原文中的对应片段。
 * 规则数据见 site/assets/core/extractors.json 的 obfuscation 段。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var C = isNode ? require('../core/extractors.json') : root.DeepSuck.coreData.extractors;
  var mod = factory(C.obfuscation);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.normalize = mod; }
})(typeof self !== 'undefined' ? self : this, function (O) {
  'use strict';

  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  var NUM_CHARS = Object.keys(O.numerals).join('');
  var RE_NUM_RUN = new RegExp('[0-9' + NUM_CHARS + '](?:[\\s\\-]{0,2}[0-9' + NUM_CHARS + ']){' + (O.numeralRunMin - 1) + ',}', 'g');
  var RE_HAS_NUMERAL = new RegExp('[' + NUM_CHARS + ']');
  var latinDots = O.dotWords.filter(function (w) { return /^[A-Za-z]+$/.test(w); }); // dot：两侧须有空格
  var cjkDots = O.dotWords.filter(function (w) { return latinDots.indexOf(w) < 0; });
  var RE_DOT = new RegExp('(?<=[A-Za-z0-9])(?:\\s*(?:' + cjkDots.map(escRe).join('|') + ')\\s*|\\s+(?:' + latinDots.map(escRe).join('|') + ')\\s+)(?=[A-Za-z]{2,})', 'g');
  var RE_SPACED_LETTERS = O.spacedLetters.map(function (w) {
    return new RegExp('(?<![A-Za-z])' + w.split('').map(escRe).join('[\\s·]+') + '(?![A-Za-z])', 'gi');
  });
  var RE_SPACED_KW = O.spaceInsideKeywords.map(function (w) {
    return { re: new RegExp(w.split('').map(escRe).join('[\\s·_\\-*]+'), 'g'), to: w };
  });
  var RE_SPACED_DIGITS = /(?<![0-9])[0-9](?:[ \u00a0\-·.,_/]{1,2}[0-9]){6,}(?![0-9])/g;

  /** 内部状态：s 为当前文本，st/en 为每个字符对应原文的 [起, 止) */
  function init(text) {
    var st = [], en = [];
    for (var i = 0; i < text.length; i++) { st.push(i); en.push(i + 1); }
    return { s: text, st: st, en: en };
  }

  /**
   * 对 state 应用一个正则替换。replacer(match) 返回：
   *   - 字符串：整段替换，新字符都映射到整个匹配区间；
   *   - 数组 [[ch, k], ...]：逐字符替换，ch 映射到匹配内第 k 个字符的位置（保留精确映射）。
   */
  function apply(state, re, replacer) {
    var s = state.s, out = '', st = [], en = [], last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(s)) !== null) {
      if (m[0] === '') { re.lastIndex++; continue; }
      var a = m.index, b = a + m[0].length;
      var rep = replacer(m[0], m);
      if (rep == null) continue;
      for (var i = last; i < a; i++) { out += s[i]; st.push(state.st[i]); en.push(state.en[i]); }
      if (typeof rep === 'string') {
        for (var j = 0; j < rep.length; j++) { out += rep[j]; st.push(state.st[a]); en.push(state.en[b - 1]); }
      } else {
        rep.forEach(function (p) { out += p[0]; st.push(state.st[a + p[1]]); en.push(state.en[a + p[1]]); });
      }
      last = b;
    }
    if (last === 0) return state;
    for (var k = last; k < s.length; k++) { out += s[k]; st.push(state.st[k]); en.push(state.en[k]); }
    return { s: out, st: st, en: en };
  }

  function fullwidth(state) {
    return apply(state, /[\uFF01-\uFF5E\u3000]+/g, function (m) {
      var r = [];
      for (var i = 0; i < m.length; i++) {
        var c = m.charCodeAt(i);
        r.push([c === 0x3000 ? ' ' : String.fromCharCode(c - 0xFEE0), i]);
      }
      return r;
    });
  }

  /**
   * normalize(text) -> { text, changed, span(start, end) -> [origStart, origEnd] }
   */
  function normalize(text) {
    var raw = String(text == null ? '' : text);
    var state = init(raw);
    state = fullwidth(state);
    RE_SPACED_KW.forEach(function (k) { state = apply(state, k.re, function (m) { return m === k.to ? null : k.to; }); });
    RE_SPACED_LETTERS.forEach(function (re) { state = apply(state, re, function (m) { var t = m.replace(/[\s·]+/g, ''); return t === m ? null : t; }); });
    state = apply(state, RE_DOT, function () { return '.'; });
    state = apply(state, RE_NUM_RUN, function (m) {
      if (!RE_HAS_NUMERAL.test(m)) return null;
      var r = [];
      for (var i = 0; i < m.length; i++) r.push([O.numerals[m[i]] || m[i], i]);
      return r;
    });
    state = apply(state, RE_SPACED_DIGITS, function (m) {
      var r = [];
      for (var i = 0; i < m.length; i++) if (/[0-9]/.test(m[i])) r.push([m[i], i]);
      return r;
    });
    var fin = state;
    return {
      text: fin.s,
      changed: fin.s !== raw,
      span: function (a, b) {
        if (fin.s === raw) return [a, b];
        if (b <= a) return [fin.st[a] || 0, fin.st[a] || 0];
        return [fin.st[a], fin.en[b - 1]];
      }
    };
  }

  return { normalize: normalize };
});
