/*!
 * DeepSuck — normalize.js
 * 中文"去武装"写法规范化：骗子常把联系方式写成 "微 信"、"V信"、"扣扣"、"xxx点com"、"幺三九…"、"１３９"、"1 3 9 0 …" 来躲避关键词过滤。
 * 在提取情报与识别话术之前先规范化；同时维护 规范化文本 → 原文 的位置映射，确保脱敏时替换的是原文中的对应片段。
 * 规则数据见 site/assets/core/extractors.json 的 obfuscation 段。
 * Apache-2.0
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

  function escCls(s) { return s.replace(/[\]\\^\-]/g, '\\$&').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t'); }
  var DJ = O.digitJoin || null;
  var SEP = DJ ? '[' + escCls(DJ.separators) + ']' : '[\\s\\-]';
  var NUM_CHARS = Object.keys(O.numerals).join('');
  // 中文数字之间允许夹空格 / 横杠 / 换行 / 标点（“六二二二，零二零二”），每处至多 2 个
  var RE_NUM_RUN = new RegExp('[0-9' + NUM_CHARS + '](?:' + SEP + '{0,2}[0-9' + NUM_CHARS + ']){' + (O.numeralRunMin - 1) + ',}', 'g');
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
  // 平台名 / 字段名中间夹标点或表情（“微，信”“微🙏信”）：表情按 UTF-16 代理对（U+1F000–U+1FBFF）与常见符号区，与 Python 版同一范围
  var KG = O.keywordGap || null;
  var EMOJI = '[\\uD83C-\\uD83E][\\uDC00-\\uDFFF]|[\\u2600-\\u27BF\\u2B00-\\u2BFF\\u2190-\\u21FF\\uFE0F\\u200D]';
  var GAP = KG ? '(?:[' + escCls(KG.chars || '') + ']' + (KG.emoji ? '|' + EMOJI : '') + ')' : null;
  var RE_GAP_KW = KG ? (KG.keywords || []).map(function (w) {
    return { re: new RegExp(w.split('').map(escRe).join('(?:' + GAP + '){0,' + (KG.max || 3) + '}'), 'g'), to: w };
  }) : [];
  var RE_EMOJI_IN_DIGITS = KG && KG.emoji ? new RegExp('(?<=[0-9' + NUM_CHARS + '])(?:' + EMOJI + '){1,' + (KG.max || 3) + '}(?=[0-9' + NUM_CHARS + '])', 'g') : null;
  var RE_SPACED_DIGITS = /(?<![0-9])[0-9](?:[ \u00a0\-·.,_/]{1,2}[0-9]){6,}(?![0-9])/g;
  var DIGIT_CHARS = (O.digitChars || {}).map || {};
  var RE_DIGIT_CHARS = Object.keys(DIGIT_CHARS).length ? new RegExp('[' + Object.keys(DIGIT_CHARS).join('') + ']+', 'g') : null;
  var RE_FILLER = O.fillerChars ? new RegExp('[' + escRe(O.fillerChars) + ']+', 'g') : null;
  var RE_DIGIT_GROUPS = (O.digitGroupKeywords || []).length
    ? new RegExp('(?:' + O.digitGroupKeywords.map(escRe).join('|') + ')[^0-9\\n]{0,4}[0-9]{2,5}(?:[ \\u00a0][0-9]{2,5}){1,4}(?![0-9])', 'g') : null;

  var VARIANT = (O.variantChars || {}).map || {};
  var RE_VARIANT = Object.keys(VARIANT).length ? new RegExp('[' + Object.keys(VARIANT).join('') + ']', 'g') : null;
  var TYPO = (O.typoKeywords || {}).map || {};
  var TYPO_KEYS = Object.keys(TYPO).sort(function (a, b) { return b.length - a.length || (a < b ? -1 : a > b ? 1 : 0); });
  var RE_TYPO = TYPO_KEYS.length ? new RegExp(TYPO_KEYS.map(escRe).join('|'), 'g') : null;
  var RE_DIGIT_JOIN = DJ ? new RegExp('(?<![0-9A-Za-z])[0-9]{1,' + DJ.maxGroup + '}(?:' + SEP + '{1,' + DJ.maxSep + '}[0-9]{1,' + DJ.maxGroup + '})+(?![0-9A-Za-z])', 'g') : null;
  var RE_UNIT_AFTER = DJ ? new RegExp(DJ.unitAfter) : null;
  var RE_STD_FORMAT = /^(?:[0-9]{4}(?:[ -][0-9]{4}){3}(?:[ -][0-9]{1,3})?|(?:86[\s-]?)?1[3-9][0-9][\s.-]?[0-9]{4}[\s.-]?[0-9]{4})$/;
  var WJ = O.walletJoin || null;
  var B58 = '1-9A-HJ-NP-Za-km-z';
  var RE_ETH_JOIN = WJ ? new RegExp('(?<![0-9A-Za-z])0x[0-9a-fA-F]{1,40}(?:' + SEP + '{1,3}[0-9a-fA-F]{' + WJ.minChunk + ',40})+(?![0-9A-Za-z])', 'g') : null;
  var RE_TRON_JOIN = WJ ? new RegExp('(?<![0-9A-Za-z])T[' + B58 + ']{' + (WJ.minChunk - 1) + ',33}(?:' + SEP + '{1,3}[' + B58 + ']{' + WJ.minChunk + ',33})+(?![0-9A-Za-z])', 'g') : null;

  function luhn(d) {
    var sum = 0, alt = false;
    for (var i = d.length - 1; i >= 0; i--) { var n = +d.charAt(i); if (alt) { n *= 2; if (n > 9) n -= 9; } sum += n; alt = !alt; }
    return d.length > 0 && sum % 10 === 0;
  }
  function binHit(d) {
    var B = typeof module === 'object' && module.exports ? require('./cardbin.js') : (self.DeepSuck || {}).cardbin;
    return !!(B && B.lookup(d));
  }
  /** 拼起来是否像一个完整号码：11 位手机号（可带 86）或 16–19 位银行卡（Luhn / 62 银联 / BIN 命中） */
  function plausibleNumber(d) {
    if (d.length === 11 && /^1[3-9]/.test(d)) return 'phone';
    if (d.length === 13 && /^861[3-9]/.test(d)) return 'phone';
    if (d.length >= 16 && d.length <= 19 && !/^(\d)\1+$/.test(d) && (luhn(d) || /^62/.test(d) || binHit(d))) return 'bank_card';
    return null;
  }
  function completeAlone(d) { return (d.length === 11 && /^1[3-9]/.test(d)) || (d.length >= 16 && d.length <= 19); }

  /** 在一段“数字 + 分隔符”里找能拼成完整号码的连续分组，返回要删除的分隔符下标集合 */
  function joinGroups(m, tailUnit) {
    var G = [], re = /[0-9]+/g, g;
    while ((g = re.exec(m)) !== null) G.push({ s: g.index, e: g.index + g[0].length, d: g[0] });
    var drop = {}, any = false;
    for (var i = 0; i < G.length;) {
      var best = -1, tot = G[i].d;
      if (!completeAlone(G[i].d)) {
        for (var j = i + 1; j < G.length; j++) {
          if (completeAlone(G[j].d)) break;
          if (j === G.length - 1 && tailUnit) break;
          tot += G[j].d;
          if (tot.length > 19) break;
          if (plausibleNumber(tot) && !RE_STD_FORMAT.test(m.slice(G[i].s, G[j].e))) best = j;
        }
      }
      if (best > i) {
        for (var k = G[i].e; k < G[best].s; k++) if (!/[0-9]/.test(m[k])) { drop[k] = 1; any = true; }
        i = best + 1;
      } else i++;
    }
    return any ? drop : null;
  }

  function joinChunks(m, re, want) {
    var C = [], g;
    re.lastIndex = 0;
    while ((g = re.exec(m)) !== null) C.push({ s: g.index, e: g.index + g[0].length, n: g[0].length });
    var tot = 0;
    for (var j = 0; j < C.length; j++) {
      tot += C[j].n;
      if (tot === want) {
        if (j === 0) return null;
        var drop = {};
        for (var k = C[0].e; k < C[j].s; k++) if (!/[0-9A-Za-z]/.test(m[k])) drop[k] = 1;
        return drop;
      }
      if (tot > want) return null;
    }
    return null;
  }

  function isNum(c) { return O.numerals[c] != null || /[0-9]/.test(c); }
  function numDigits(t) { var r = ''; for (var i = 0; i < t.length; i++) if (isNum(t[i])) r += O.numerals[t[i]] != null ? O.numerals[t[i]] : t[i]; return r; }
  /**
   * #2：全中文数字串后面紧跟量词 / 时间单位（“一三九零零一一二二三三两小时”）时，末尾 1–2 个中文数字是数量，返回号码部分的结束下标；
   * 末字是“两”一律截掉；否则只有整串拼不成号码、截掉末尾 1–2 个中文数字后能拼成时才截。与 Python _quantity_cut 一致。
   */
  function quantityCut(m) {
    var pos = [];
    for (var i = 0; i < m.length; i++) if (O.numerals[m[i]] != null && !/[0-9]/.test(m[i])) pos.push(i);
    if (!pos.length || pos[pos.length - 1] !== m.length - 1) return null;
    function endOf(c) { while (c > 0 && !isNum(m[c - 1])) c--; return c; }
    if (m[m.length - 1] === '两') return endOf(m.length - 1);
    if (plausibleNumber(numDigits(m))) return null;
    for (var t = 1; t <= 2; t++) {
      if (pos.length <= t) break;
      var c = endOf(pos[pos.length - t]);
      if (plausibleNumber(numDigits(m.slice(0, c)))) return c;
    }
    return null;
  }

  function shift(drop, n) { var o = {}; Object.keys(drop).forEach(function (k) { o[+k + n] = 1; }); return o; }

  function dropper(m, drop) {
    if (!drop) return null;
    var r = [];
    for (var i = 0; i < m.length; i++) if (!drop[i]) r.push([m[i], i]);
    return r;
  }

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
      var rep = replacer(m[0], m, s);
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
    // 异体字 / 繁体（帐→账）与关键词错别字（personas 混淆表：转帐→转账、银航→银行），逐字等长替换
    if (RE_VARIANT) state = apply(state, RE_VARIANT, function (m) { return [[VARIANT[m], 0]]; });
    if (RE_TYPO) state = apply(state, RE_TYPO, function (m) { var t = TYPO[m], r = []; for (var i = 0; i < t.length; i++) r.push([t[i], i]); return r; });
    // 圈码数字 ①③⑨ → 139（逐字符，位置精确）；装饰符号 ❤★ 等直接删除（“薇❤信”→“薇信”）
    if (RE_DIGIT_CHARS) state = apply(state, RE_DIGIT_CHARS, function (m) { var r = []; for (var i = 0; i < m.length; i++) r.push([DIGIT_CHARS[m[i]], i]); return r; });
    if (RE_FILLER) state = apply(state, RE_FILLER, function () { return []; });
    RE_SPACED_KW.forEach(function (k) { state = apply(state, k.re, function (m) { return m === k.to ? null : k.to; }); });
    if (RE_EMOJI_IN_DIGITS) state = apply(state, RE_EMOJI_IN_DIGITS, function () { return ' '; }); // “二幺幺四🌹🌹幺三六二”：数字之间的表情当作一个空格
    RE_GAP_KW.forEach(function (k) {
      state = apply(state, k.re, function (m, mm, full) {
        if (m === k.to) return null;
        var a = mm.index, b = a + m.length;
        if (a > 0 && ((KG.notAfter || {})[k.to] || '').indexOf(full[a - 1]) >= 0) return null;
        if (b < full.length && ((KG.notBefore || {})[k.to] || '').indexOf(full[b]) >= 0) return null;
        return k.to;
      });
    });
    RE_SPACED_LETTERS.forEach(function (re) { state = apply(state, re, function (m) { var t = m.replace(/[\s·]+/g, ''); return t === m ? null : t; }); });
    state = apply(state, RE_DOT, function () { return '.'; });
    state = apply(state, RE_NUM_RUN, function (m, mm, full) {
      if (!RE_HAS_NUMERAL.test(m)) return null;
      // “13900112233两小时”：紧跟在阿拉伯数字后、后面接单位的中文数字是量词用法，不并入号码
      var k = m.length;
      while (k > 0 && O.numerals[m[k - 1]] != null && !/[0-9]/.test(m[k - 1])) k--;
      var keep = m.length;
      var unit = !!(RE_UNIT_AFTER && RE_UNIT_AFTER.test(full.slice(mm.index + m.length)));
      if (k > 0 && k < m.length && unit && /[0-9]/.test(m[k - 1])) {
        if (!RE_HAS_NUMERAL.test(m.slice(0, k))) return null;
        keep = k;
      } else if (unit) {
        var cut = quantityCut(m);
        if (cut != null) {
          if (!RE_HAS_NUMERAL.test(m.slice(0, cut))) return null;
          keep = cut;
        }
      }
      var r = [];
      for (var i = 0; i < m.length; i++) r.push([i < keep ? (O.numerals[m[i]] || m[i]) : m[i], i]);
      return r;
    });
    state = apply(state, RE_SPACED_DIGITS, function (m) {
      var r = [];
      for (var i = 0; i < m.length; i++) if (/[0-9]/.test(m[i])) r.push([m[i], i]);
      return r;
    });
    // “企鹅 699 700 370” → “企鹅 699700370”：只删除两侧都是数字的空格
    if (RE_DIGIT_GROUPS) state = apply(state, RE_DIGIT_GROUPS, function (m) {
      var r = [];
      for (var i = 0; i < m.length; i++) {
        if (/[ \u00a0]/.test(m[i]) && /[0-9]/.test(m[i - 1] || '') && /[0-9]/.test(m[i + 1] || '')) continue;
        r.push([m[i], i]);
      }
      return r.length === m.length ? null : r;
    });
    // 数字间夹空格 / 横杠 / 换行 / 标点：只有拼起来是合法手机号 / 银行卡时才拼接
    if (RE_DIGIT_JOIN) state = apply(state, RE_DIGIT_JOIN, function (m, mm, full) {
      return dropper(m, joinGroups(m, RE_UNIT_AFTER.test(full.slice(mm.index + m.length))));
    });
    if (RE_ETH_JOIN) state = apply(state, RE_ETH_JOIN, function (m) { return dropper(m, joinChunks(m.slice(2), /[0-9a-fA-F]+/g, 40) ? shift(joinChunks(m.slice(2), /[0-9a-fA-F]+/g, 40), 2) : null); });
    if (RE_TRON_JOIN) state = apply(state, RE_TRON_JOIN, function (m) { return dropper(m, joinChunks(m, new RegExp('[' + B58 + ']+', 'g'), 34)); });
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

  return { normalize: normalize, plausibleNumber: plausibleNumber, luhn: luhn };
});
