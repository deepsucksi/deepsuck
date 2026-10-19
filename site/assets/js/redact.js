/*!
 * DeepSuck — redact.js
 * 脱敏模块：所有对外展示 / 导出的情报都必须经过这里。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  // 验证码规则在共享核心 json（redact.otp）；浏览器里 core-data.js 须先于本文件加载，缺失时只按实体打码
  var core = function () {
    if (isNode) return require('../core/extractors.json');
    return root.DeepSuck && root.DeepSuck.coreData && root.DeepSuck.coreData.extractors;
  };
  var mod = factory(core);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.redact = mod; }
})(typeof self !== 'undefined' ? self : this, function (core) {
  'use strict';

  function digitsOnly(s) { return String(s || '').replace(/\D/g, ''); }

  function stars(n) { return new Array(Math.max(0, n) + 1).join('*'); }

  /**
   * PCI DSS 显示规则：16–19 位卡号保留前 6 位（BIN）与后 4 位，中间全部打码：
   *   6222 0212 3456 1234 -> 622202******1234；6222020200112233445 -> 622202*********3445
   * 8–15 位（非标准长度）只留后 4 位，少于 8 位全部打码，保证至少一半数字被隐藏。
   */
  /**
   * 仅用于展示：把（已打码的）卡号每 4 位一组，622202*********3445 -> 6222 02** **** ***3 445。
   * 存储、导出、STIX 仍用不分组的 maskBankCard 结果；只含数字与 * 以外字符的值原样返回。
   */
  function formatCardGroups(v) {
    var s = String(v == null ? '' : v).replace(/[\s-]/g, '');
    if (!/^[0-9*]+$/.test(s)) return String(v == null ? '' : v);
    return s.replace(/(.{4})(?=.)/g, '$1 ');
  }

  function maskBankCard(v) {
    var d = digitsOnly(v);
    if (d.length < 8) return stars(d.length);
    if (d.length < 16) return stars(d.length - 4) + d.slice(-4);
    return d.slice(0, 6) + stars(d.length - 10) + d.slice(-4);
  }

  /** 13812345678 / +86 138-1234-5678 -> 138****5678 ; 400-123-4567 -> 400-***-4567 */
  function maskPhone(v) {
    var d = digitsOnly(v);
    if (d.length === 13 && d.indexOf('86') === 0) d = d.slice(2);
    if (/^400|^800/.test(d) && d.length === 10) return d.slice(0, 3) + '-***-' + d.slice(-4);
    if (d.length === 11) return d.slice(0, 3) + '****' + d.slice(-4);
    if (d.length <= 4) return stars(d.length);
    return d.slice(0, 2) + stars(d.length - 4) + d.slice(-2);
  }

  /** 0x12ab....9f3e -> 0x12ab...9f3e ; TQ7x...ab12 ; bc1qxy...wlh */
  function maskCrypto(v) {
    var s = String(v || '');
    if (s.length <= 10) return s.slice(0, 2) + '...';
    var head = /^0x/i.test(s) ? 6 : (/^bc1/i.test(s) ? 6 : 4);
    return s.slice(0, head) + '...' + s.slice(-4);
  }

  /** QQ 12345678 -> 12****78 */
  function maskQQ(v) {
    var d = digitsOnly(v);
    if (d.length <= 4) return stars(d.length);
    return d.slice(0, 2) + stars(d.length - 4) + d.slice(-2);
  }

  /** 微信号 / 通用 ID：保留首 2 尾 2 */
  function maskHandle(v) {
    var s = String(v || '');
    if (s.length <= 4) return s.charAt(0) + stars(s.length - 1);
    return s.slice(0, 2) + stars(Math.min(6, s.length - 4)) + s.slice(-2);
  }

  /** 身份证：110101********1234 */
  function maskIdCard(v) {
    var s = String(v || '').toUpperCase().replace(/\s/g, '');
    if (s.length < 10) return stars(s.length);
    return s.slice(0, 6) + '********' + s.slice(-4);
  }

  /** 张三 -> 张*，欧阳娜娜 -> 欧***（只留姓） */
  function maskName(v) {
    var s = String(v || '');
    if (!s) return '';
    return s.charAt(0) + stars(s.length - 1);
  }

  /** abc.def@gmail.com -> ab***@gmail.com */
  function maskEmail(v) {
    var s = String(v || '');
    var at = s.indexOf('@');
    if (at < 1) return maskHandle(s);
    var user = s.slice(0, at);
    return user.slice(0, Math.min(2, user.length)) + '***' + s.slice(at);
  }

  /**
   * URL：保留协议与顶级域，主机名中间打码，路径一律隐藏。
   * https://refund-taobao-kefu.top/app/download?id=9 -> https://re***fu.top/***
   */
  function maskUrl(v) {
    var s = String(v || '').trim();
    var m = s.match(/^((?:https?:)?\/\/)?([^\/?#:]+)(:\d+)?([\/?#].*)?$/i);
    if (!m) return '***';
    var proto = m[1] || '';
    var host = m[2] || '';
    if (/^www\./i.test(host)) { proto += host.slice(0, 4); host = host.slice(4); }
    var hasPath = !!(m[4] && m[4].length > 1);
    var labels = host.split('.');
    var tld = labels.length > 1 ? labels.pop() : '';
    var rest = labels.join('.');
    var maskedRest;
    if (/^\d+(\.\d+){2}$/.test(rest)) { // IPv4 去掉了最后一段作为 "tld"
      maskedRest = rest.split('.')[0] + '.*.*';
    } else if (rest.length <= 4) {
      maskedRest = rest.charAt(0) + '***';
    } else {
      maskedRest = rest.slice(0, 2) + '***' + rest.slice(-2);
    }
    return proto + maskedRest + (tld ? '.' + tld : '') + (hasPath ? '/***' : '');
  }

  var MASKERS = {
    bank_card: maskBankCard,
    phone: maskPhone,
    hotline: maskPhone,
    crypto_btc: maskCrypto,
    crypto_eth: maskCrypto,
    crypto_tron: maskCrypto,
    url: maskUrl,
    qq: maskQQ,
    wechat: maskHandle,
    alipay: function (v) { return /@/.test(v) ? maskEmail(v) : (/^\d{11}$/.test(digitsOnly(v)) ? maskPhone(v) : maskHandle(v)); },
    email: maskEmail,
    id_card: maskIdCard,
    name: maskName
  };

  /** 按情报类型脱敏；未知类型保守地全部打码 */
  function mask(type, value) {
    var fn = MASKERS[type];
    if (fn) return fn(value);
    return maskHandle(value);
  }

  // ---- 验证码类短数字（#33）：规则见 core/extractors.json 的 redact.otp ----
  var OTP = null;
  function otpRules() {
    if (OTP !== null) return OTP;
    var C = core && core();
    var o = C && C.redact && C.redact.otp;
    if (!o) return (OTP = false);
    var D = o.digit, S = o.sep;
    OTP = {
      o: o,
      kw: new RegExp(o.keyword, 'g' + (o.keywordFlags || '')),
      run: new RegExp(D + '(?:' + S + '{0,' + o.maxSep + '}' + D + ')*', 'g'),
      digit: new RegExp(D, 'g'),
      join: new RegExp(o.join),
      breaks: new RegExp(o.breaks, 'g'),
      gapBlock: new RegExp(o.gapBlock),
      edge: new RegExp(o.edge),
      blockBefore: new RegExp(o.blockBefore),
      unitAfter: new RegExp(o.unitAfter),
      segJoin: new RegExp(o.segJoin || '^$')
    };
    return OTP;
  }

  function countOf(re, s) { re.lastIndex = 0; var m = s.match(re); return m ? m.length : 0; }

  /**
   * 找出文本里按上下文判定为验证码的数字串：[{start, end, masked}]（start/end 为 UTF-16 下标）。
   * 只在验证码 / 动态码 / 校验码 / 短信码 / 确认码 / OTP 等关键词附近、4–8 位时才算；
   * 手机号、卡号（位数超出）、金额、尾号、订单号、与关键词无关的数字都不算。
   */
  function findOtpSpans(text) {
    var R = otpRules();
    if (!R) return [];
    return findOtp(R, String(text || ''), []);
  }

  // bounds：拼接文本里各分段的接缝位置（#92），接缝两侧的数字串之间只有 segJoin 时可连成一串
  function findOtp(R, s, bounds) {
    var o = R.o, kws = [], m;
    R.kw.lastIndex = 0;
    while ((m = R.kw.exec(s))) { kws.push([m.index, m.index + m[0].length]); if (!m[0].length) R.kw.lastIndex++; }
    if (!kws.length) return [];
    var runs = [];
    R.run.lastIndex = 0;
    while ((m = R.run.exec(s))) runs.push({ start: m.index, end: m.index + m[0].length, n: countOf(R.digit, m[0]) });
    // 两段都不超过 joinPartMax 位、中间只有「，」「、」时连成一串（「4 7 2，9 1 5」）
    var groups = [];
    runs.forEach(function (r) {
      var g = groups[groups.length - 1];
      var gap = g ? s.slice(g.end, r.start) : '';
      var seam = g && bounds.some(function (b) { return g.end <= b && b <= r.start; });
      if (g && g.n + r.n <= o.maxLen && ((g.last <= o.joinPartMax && r.n <= o.joinPartMax && R.join.test(gap)) || (seam && R.segJoin.test(gap)))) {
        g.end = r.end; g.n += r.n; g.last = r.n;
      } else groups.push({ start: r.start, end: r.end, n: r.n, last: r.n });
    });
    // 超过 maxLen 位时只接受空白隔开的两段、每段 minLen–maxLen 位（重复报码「472915 472915」）；
    // 手机号（3-4-4）、卡号（4 段以上）不在此列，由实体规则负责
    function repeated(g) {
      var parts = s.slice(g.start, g.end).split(/\s+/);
      return parts.length === 2 && parts.every(function (p) { var n = countOf(R.digit, p); return n >= o.minLen && n <= o.maxLen; });
    }
    var out = [];
    groups.forEach(function (g) {
      if (g.n < o.minLen) return;
      if (g.n > o.maxLen && !repeated(g)) return;
      if ((g.start > 0 && R.edge.test(s.charAt(g.start - 1))) || (g.end < s.length && R.edge.test(s.charAt(g.end)))) return;
      if (R.blockBefore.test(s.slice(Math.max(0, g.start - o.blockBeforeChars), g.start))) return;
      if (R.unitAfter.test(s.slice(g.end))) return;
      var near = kws.some(function (k) {
        var gap;
        if (k[1] <= g.start) { if (g.start - k[1] > o.after) return false; gap = s.slice(k[1], g.start); }
        else if (k[0] >= g.end) { if (k[0] - g.end > o.before) return false; gap = s.slice(g.end, k[0]); }
        else return false;
        return !R.gapBlock.test(gap) && countOf(R.breaks, gap) <= o.maxBreaks;
      });
      if (!near) return;
      R.digit.lastIndex = 0;
      out.push({ start: g.start, end: g.end, masked: s.slice(g.start, g.end).replace(R.digit, '*') });
    });
    return out;
  }

  /**
   * 跨 ASR 分段找验证码（#92）：texts 是同一通电话、同一说话方按时间排的连续分段。
   * 以每段为中心、连同前后各 window（默认 redact.otp.segWindow）段用 segJoiner 拼接，按 findOtpSpans 的同一套规则
   * 再找一遍，命中的数字串按分段切开映射回窗口里的各段（各窗口结果取并集：第 i 段的结果只取决于前后各 2×window 段）。返回与 texts 等长的数组，每项是该段的 [{start, end, masked}]（段内下标，已合并）。
   * 建议对逐段 redactText 之后的文本调用（打码值紧挨 * 不会被当成验证码）。
   */
  function findOtpSpansSegments(texts, window) {
    var segs = (texts || []).map(function (t) { return t == null ? '' : String(t); });
    var R = otpRules();
    var hits = segs.map(function () { return []; });
    if (!R || !segs.length) return hits;
    var o = R.o;
    var w = Math.max(0, parseInt(window == null ? (o.segWindow == null ? 2 : o.segWindow) : window, 10) || 0);
    var joiner = o.segJoiner == null ? ' ' : o.segJoiner;
    var seen = {};
    for (var c = 0; c < segs.length; c++) {
      var lo = Math.max(0, c - w), hi = Math.min(segs.length, c + w + 1);
      if (seen[lo + ',' + hi]) continue;
      seen[lo + ',' + hi] = true;
      var idx = [], offs = [], bounds = [], pos = 0;
      for (var i = lo; i < hi; i++) idx.push(i);
      idx.forEach(function (i, k) {
        if (k) { bounds.push(pos); pos += joiner.length; bounds.push(pos); }
        offs.push(pos);
        pos += segs[i].length;
      });
      var joined = idx.map(function (i) { return segs[i]; }).join(joiner);
      findOtp(R, joined, bounds).forEach(function (sp) {
        idx.forEach(function (i, k) {
          var a = Math.max(sp.start, offs[k]), b = Math.min(sp.end, offs[k] + segs[i].length);
          if (a < b) hits[i].push([a - offs[k], b - offs[k]]);
        });
      });
    }
    return hits.map(function (hs, i) {
      hs.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1]; });
      var merged = [];
      hs.forEach(function (h) {
        var t = merged[merged.length - 1];
        if (t && h[0] <= t[1]) t[1] = Math.max(t[1], h[1]);
        else merged.push([h[0], h[1]]);
      });
      return merged.map(function (h) {
        R.digit.lastIndex = 0;
        return { start: h[0], end: h[1], masked: segs[i].slice(h[0], h[1]).replace(R.digit, '*') };
      });
    });
  }

  /** 跨分段验证码判断看前后几段（redact.otp.segWindow，#92） */
  function otpSegWindow() {
    var R = otpRules();
    return R ? (R.o.segWindow == null ? 2 : R.o.segWindow) : 0;
  }

  /** 把 findOtpSpansSegments 命中的数字换成 *（长度不变）后返回各段文本（#92）；可重复调用。 */
  function redactOtpSegments(texts, window) {
    var segs = (texts || []).map(function (t) { return t == null ? '' : String(t); });
    var spans = findOtpSpansSegments(segs, window);
    return segs.map(function (s, i) {
      spans[i].slice().sort(function (a, b) { return b.start - a.start; }).forEach(function (p) {
        s = s.slice(0, p.start) + p.masked + s.slice(p.end);
      });
      return s;
    });
  }

  // ---- 卡号片段、人设侧兜底、两边说话人（#120）：规则见 core/extractors.json 的 redact.card / redact.persona ----
  var CN_DIGIT = { '零': '0', '〇': '0', '一': '1', '幺': '1', '二': '2', '两': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9' };
  function asciiDigits(s) {
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i), cc = s.charCodeAt(i);
      if (cc >= 0xFF10 && cc <= 0xFF19) out += String.fromCharCode(cc - 0xFEE0);
      else if (CN_DIGIT[ch]) out += CN_DIGIT[ch];
      else if (ch >= '0' && ch <= '9') out += ch;
    }
    return out;
  }

  var CARD = null;
  function cardRules() {
    if (CARD !== null) return CARD;
    var C = core && core();
    var red = (C && C.redact) || {};
    var c = red.card, o = red.otp;
    if (!c || !o) return (CARD = false);
    CARD = {
      c: c,
      kw: new RegExp(c.keyword, 'g'),
      run: new RegExp(o.digit + '(?:' + o.sep + '{0,' + o.maxSep + '}' + o.digit + ')*', 'g'),
      digit: new RegExp(o.digit, 'g'),
      edge: new RegExp(o.edge),
      prefixAfter: new RegExp(c.prefixAfter),
      strongBin: new RegExp(c.strongBin),
      notCard: new RegExp(c.notCard || '(?!)'),
      tailBefore: new RegExp(c.tailBefore),
      tailBlock: new RegExp(c.tailBlock)
    };
    return CARD;
  }

  function starDigits(re, s) { re.lastIndex = 0; return s.replace(re, '*'); }

  /** 卡号片段（「6222开头」「尾号0123」，卡号语境下）：[{start, end, masked}]，数字全部换成 * */
  function findCardSpans(text) {
    var R = cardRules();
    if (!R) return [];
    var s = String(text || ''), c = R.c, kws = [], m;
    R.kw.lastIndex = 0;
    while ((m = R.kw.exec(s))) { kws.push([m.index, m.index + m[0].length]); if (!m[0].length) R.kw.lastIndex++; }
    function kwNear(a, b) {
      return kws.some(function (k) {
        return (k[1] <= a && a - k[1] <= c.window) || (k[0] >= b && k[0] - b <= c.window) || (k[0] < b && a < k[1]);
      });
    }
    var runs = [];
    R.run.lastIndex = 0;
    while ((m = R.run.exec(s))) {
      var a = m.index, b = a + m[0].length;
      if ((a > 0 && R.edge.test(s.charAt(a - 1))) || (b < s.length && R.edge.test(s.charAt(b)))) continue;
      runs.push([a, b, countOf(R.digit, m[0])]);
    }
    var prefixes = [], tails = [];
    runs.forEach(function (r) {
      if (r[2] >= c.minLen && r[2] <= c.maxLen && R.prefixAfter.test(s.slice(r[1])) && !R.notCard.test(asciiDigits(s.slice(r[0], r[1])))) {
        var strong = r[2] >= c.strongMinLen && R.strongBin.test(asciiDigits(s.slice(r[0], r[1])));
        if (strong || kwNear(r[0], r[1])) prefixes.push([r[0], r[1]]);
      }
    });
    runs.forEach(function (r) {
      if (r[2] < c.minLen || r[2] > c.tailMaxLen) return;
      var lo = Math.max(0, r[0] - c.tailBeforeChars);
      var tm = R.tailBefore.exec(s.slice(lo, r[0]));
      if (!tm) return;
      var t0 = lo + tm.index;
      if (R.tailBlock.test(s.slice(Math.max(0, t0 - c.tailBlockChars), t0))) return;
      var nearPrefix = prefixes.some(function (p) { return Math.abs(r[0] - p[1]) <= c.window || Math.abs(p[0] - r[1]) <= c.window; });
      if (kwNear(r[0], r[1]) || nearPrefix) tails.push([r[0], r[1]]);
    });
    var seen = {}, all = [];
    prefixes.concat(tails).forEach(function (x) { var k = x[0] + ',' + x[1]; if (!seen[k]) { seen[k] = 1; all.push(x); } });
    all.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1]; });
    return all.map(function (x) { return { start: x[0], end: x[1], masked: starDigits(R.digit, s.slice(x[0], x[1])) }; });
  }

  /** 卡号片段跨分段打码（窗口同 redact.otp.segWindow） */
  function redactCardSegments(texts, window) {
    var segs = (texts || []).map(function (t) { return t == null ? '' : String(t); });
    var R = cardRules(), O = otpRules();
    if (!R || !O || !segs.length) return segs;
    var w = Math.max(0, parseInt(window == null ? (O.o.segWindow == null ? 2 : O.o.segWindow) : window, 10) || 0);
    var joiner = O.o.segJoiner == null ? ' ' : O.o.segJoiner;
    var hits = segs.map(function () { return []; });
    for (var c = 0; c < segs.length; c++) {
      var idx = [], offs = [], pos = 0;
      for (var i = Math.max(0, c - w); i < Math.min(segs.length, c + w + 1); i++) idx.push(i);
      idx.forEach(function (i, k) { if (k) pos += joiner.length; offs.push(pos); pos += segs[i].length; });
      findCardSpans(idx.map(function (i) { return segs[i]; }).join(joiner)).forEach(function (sp) {
        idx.forEach(function (i, k) {
          var a = Math.max(sp.start, offs[k]), b = Math.min(sp.end, offs[k] + segs[i].length);
          if (a < b) hits[i].push([a - offs[k], b - offs[k]]);
        });
      });
    }
    return segs.map(function (s, i) {
      hits[i].forEach(function (h) { s = s.slice(0, h[0]) + starDigits(R.digit, s.slice(h[0], h[1])) + s.slice(h[1]); });
      return s;
    });
  }

  var PERSONA = null;
  function personaRules() {
    if (PERSONA !== null) return PERSONA;
    var C = core && core();
    var red = (C && C.redact) || {};
    var p = red.persona, o = red.otp;
    if (!p || !o) return (PERSONA = false);
    PERSONA = { p: p, digit: new RegExp(o.digit, 'g'), run: new RegExp(o.digit + '(?:' + p.sep + '{0,' + p.maxSep + '}' + o.digit + ')*', 'g') };
    return PERSONA;
  }

  /** 人设侧兜底（redact.persona）：连续 minRun 位及以上的逐位数字换成 *（长度不变，可重复执行） */
  function redactPersona(text) {
    var s = text == null ? '' : String(text);
    var R = personaRules();
    if (!R) return s;
    return s.replace(R.run, function (m) { return countOf(R.digit, m) >= R.p.minRun ? starDigits(R.digit, m) : m; });
  }

  /** 两边说话人合在一起打码（#120，见 redact.dialogComment）：role 为 'scammer' 的是骗子侧，其余都算人设侧 */
  function redactDialogSegments(texts, roles, window) {
    var out = (texts || []).map(function (t) { return t == null ? '' : String(t); });
    var side = out.map(function (_, i) { return (roles || [])[i] === 'scammer' ? 'scammer' : 'persona'; });
    ['scammer', 'persona'].forEach(function (who) {
      var idx = [];
      side.forEach(function (x, i) { if (x === who) idx.push(i); });
      redactOtpSegments(idx.map(function (i) { return out[i]; }), window).forEach(function (t, k) { out[idx[k]] = t; });
    });
    out = redactOtpSegments(out, window);
    // 一方报数字、另一方说验证码且中间隔着别的话（「验证码多少」「是…47」「后面呢」「29」）：另一方的分段只留验证码关键词
    var R = otpRules();
    if (R) {
      ['scammer', 'persona'].forEach(function (who) {
        var view = out.map(function (t, i) {
          if (side[i] === who) return t;
          R.kw.lastIndex = 0;
          return (t.match(R.kw) || []).join(' ');
        });
        redactOtpSegments(view, window).forEach(function (t, i) { if (side[i] === who) out[i] = t; });
      });
    }
    out = redactCardSegments(out, window);
    return out.map(function (t, i) { return side[i] === 'persona' ? redactPersona(t) : t; });
  }

  // ---- 拆字报姓（#139）：规则见 core/extractors.json 的 nameRules.split，与 redact.py 共用 ----
  var SPLIT = null;
  function splitRules() {
    if (SPLIT !== null) return SPLIT;
    var C = core && core();
    var nr = C && C.nameRules;
    var sp = nr && nr.split;
    if (!sp || !sp.spellings || !sp.spellings.length) return (SPLIT = false);
    function esc(x) { return x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    var alts = sp.spellings.slice().sort(function (a, b) { return b.length - a.length; });
    SPLIT = {
      sp: sp,
      re: new RegExp('(' + alts.map(function (x) { return esc(x.slice(0, -1)) + (sp.link || '') + esc(x.slice(-1)); }).join('|') + ')', 'g'),
      sep: new RegExp('^(?:' + (sp.sep || '') + ')'),
      stop: new RegExp(sp.givenStop),
      notNames: nr.notNames ? new RegExp(nr.notNames) : null
    };
    return SPLIT;
  }

  // ---- 逐字解释名字（#158）：规则见 core/extractors.json 的 nameRules.explain，与 redact.py 共用 ----
  var EXPLAIN = null;
  function explainRules() {
    if (EXPLAIN !== null) return EXPLAIN;
    var C = core && core();
    var ex = C && C.nameRules && C.nameRules.explain;
    if (!ex || !ex.link) return (EXPLAIN = false);
    EXPLAIN = {
      ex: ex,
      han: new RegExp('^' + ex.han + '$'),
      link: new RegExp('(?:' + ex.link + ')(' + ex.han + ')', 'y'),
      tail: new RegExp('(?:' + (ex.tail || '') + ')', 'y'),
      stop: new RegExp(ex.wordStop || '(?!)'),
      tailWords: new RegExp('^(?:' + (ex.tailWords || '(?!)') + ')'), // #206「伟大的伟对吧」
      particle: new RegExp('^(?:' + (ex.particle || '(?!)') + ')$'),
      sep: new RegExp('^(?:' + (ex.sep || '') + ')$'),
      gap: new RegExp(ex.anchorGap)
    };
    return EXPLAIN;
  }

  /**
   * 逐字解释（「伟大的伟，明天的明」「伟是伟大的伟」）：[{start, end, x, keep}]，按 start 升序、互不重叠。
   * head：这一段连同前面的「就是」「是」从哪里开始（只用来判断相邻，不打码「就是」本身）。
   * keep：被解释的是姓（相邻拆字报姓的姓或已提取姓名的姓），这一段不打码。
   */
  function explainUnits(s, ents) {
    var E = explainRules();
    if (!E) return [];
    var ex = E.ex;
    var wmin = ex.wordMin || 2, wmax = ex.wordMax || 4;
    var leads = ex.leads || [], strong = ex.strongLeads || [];
    var cands = [];
    for (var i = 0; i < s.length; i++) {
      E.link.lastIndex = i;
      var m = E.link.exec(s);
      if (!m) continue;
      var x = m[1];
      var wstart = -1;
      for (var L = 1; L <= wmax && i - L >= 0; L++) {
        var c = s.charAt(i - L);
        if (!E.han.test(c) || E.stop.test(c)) break;
        if (L >= wmin && s.slice(i - L, i).indexOf(x) >= 0) { wstart = i - L; break; }
      }
      if (wstart < 0) continue;
      var end = i + m[0].length;
      E.tail.lastIndex = end;
      var t = E.tail.exec(s);
      if (t) end += t[0].length;
      var start = wstart, head = wstart, st = false;
      for (var k = 0; k < leads.length; k++) {
        var ld = leads[k];
        if (wstart < ld.length || s.slice(wstart - ld.length, wstart) !== ld) continue;
        var b = wstart - ld.length;
        head = b;
        if (b >= 1 && s.charAt(b - 1) === x) { start = head = b - 1; st = true; }
        else if (b >= 2 && s.slice(b - 2, b) === x + '字') { start = head = b - 2; st = true; }
        else if (strong.indexOf(ld) >= 0) st = true;
        break;
      }
      cands.push({ start: start, head: head, wstart: wstart, end: end, x: x, strong: st });
    }
    var heads = {};
    cands.forEach(function (c) { heads[c.head] = 1; heads[c.wstart] = 1; });
    var units = [];
    cands.filter(function (c) {
      var n = s.charAt(c.end);
      return c.end >= s.length || !E.han.test(n) || E.particle.test(n) || heads[c.end] === 1 || E.tailWords.test(s.slice(c.end));
    }).sort(function (a, b) { return a.start - b.start || a.end - b.end; }).forEach(function (c) {
      if (!units.length || units[units.length - 1].end <= c.start) units.push(c);
    });
    if (!units.length) return [];
    var anchors = [];
    var R = splitRules();
    if (R) {
      var sm;
      R.re.lastIndex = 0;
      while ((sm = R.re.exec(s))) anchors.push({ end: sm.index + sm[0].length, sur: sm[1].slice(-1) });
    }
    var surAll = {};
    (ents || []).forEach(function (e) {
      if (typeof e.start !== 'number' || e.type !== 'name' || !e.value) return;
      anchors.push({ end: e.end, sur: String(e.value).charAt(0) });
      surAll[String(e.value).charAt(0)] = 1;
    });
    var out = [];
    var chain = [];
    function flush() {
      if (!chain.length) return;
      var first = chain[0].head;
      var sur = {};
      Object.keys(surAll).forEach(function (k) { sur[k] = 1; });
      var anchored = false;
      anchors.forEach(function (a) {
        if (a.end <= first && E.gap.test(s.slice(a.end, first))) { anchored = true; sur[a.sur] = 1; }
      });
      if (chain.length >= 2 || anchored || chain.some(function (c) { return c.strong; })) {
        chain.forEach(function (c) { out.push({ start: c.start, end: c.end, x: c.x, keep: sur[c.x] === 1 }); });
      }
      chain = [];
    }
    units.forEach(function (u) {
      if (chain.length && !E.sep.test(s.slice(chain[chain.length - 1].end, u.head))) flush();
      chain.push(u);
    });
    flush();
    return out;
  }

  /**
   * 拆字报姓（「弓长张，三丰」「木子李四」）后紧跟的名：[{start, end, masked}]，名换成等长的 *。
   * entities：extract() 的结果；同姓的已提取姓名决定名的长度，与敏感实体重叠的位置不再重复给出。
   * 逐字解释（「伟大的伟，明天的明」，#158）整段一并给出（含被解释的字），见 explainUnits。
   * 拆字说法以外单独出现的名（「三丰」）不在这里处理。
   */
  function findNameSpans(text, entities) {
    var s = String(text || '');
    var R = splitRules();
    if (!R) return [];
    var ents = (entities || []).filter(function (e) { return typeof e.start === 'number'; });
    var claimed = ents.filter(function (e) { return e.sensitive !== false; }).map(function (e) { return [e.start, e.end]; });
    var names = ents.filter(function (e) { return e.type === 'name' && String(e.value || '').length >= 2; })
      .map(function (e) { return String(e.value); });
    var max = R.sp.givenMax == null ? 2 : R.sp.givenMax;
    // 逐字解释（#158）：拆字报姓后紧跟逐字解释时不再往后数字打码，整段解释由下面统一打码
    var units = explainUnits(s, ents);
    var out = [];
    var m;
    R.re.lastIndex = 0;
    while ((m = R.re.exec(s))) {
      var sur = m[1].slice(-1);
      var after = m.index + m[0].length;
      var pos = after + R.sep.exec(s.slice(after))[0].length;
      if (units.some(function (u) { return u.start <= pos && pos < u.end; })) continue;
      var given = '';
      for (var k = 0; k < names.length; k++) {
        var n = names[k];
        if (n.charAt(0) === sur && s.substr(pos, n.length - 1) === n.slice(1)) { given = n.slice(1); break; }
      }
      if (!given) {
        while (given.length < max && pos + given.length < s.length && !R.stop.test(s.charAt(pos + given.length)) &&
          !units.some(function (u) { return u.start === pos + given.length; })) {
          given += s.charAt(pos + given.length);
        }
        if (given && R.notNames && R.notNames.test(given)) given = '';
      }
      var end = pos + given.length;
      if (!given || claimed.some(function (c) { return c[0] < end && pos < c[1]; })) continue;
      claimed.push([pos, end]);
      out.push({ start: pos, end: end, masked: stars(given.length) });
    }
    var ex = (explainRules() || {}).ex || {};
    units.forEach(function (u) {
      if (u.keep || claimed.some(function (c) { return c[0] < u.end && u.start < c[1]; })) return;
      var glue = claimed.some(function (c) { return c[1] === u.start; }) ? (ex.joiner || '') : '';
      claimed.push([u.start, u.end]);
      out.push({ start: u.start, end: u.end, masked: glue + stars(u.end - u.start) });
    });
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }

  /**
   * 将一段文本中的敏感片段替换成脱敏结果。
   * entities: extractors.extract() 返回的数组（含 start/end/type/value）；
   * 另外按上下文给验证码类短数字打码（与实体重叠的交给实体自己的规则）。
   */
  function redactText(text, entities) {
    var s = String(text || '');
    var list = (entities || [])
      .filter(function (e) { return typeof e.start === 'number' && e.sensitive !== false; })
      .map(function (e) { return { start: e.start, end: e.end, masked: e.masked || mask(e.type, e.value) }; });
    var all = (entities || []).filter(function (e) { return typeof e.start === 'number'; });
    // 拆字报姓后的名（#139）与逐字解释（#158）
    findNameSpans(s, all).forEach(function (n) { list.push(n); all.push({ start: n.start, end: n.end }); });
    findOtpSpans(s).forEach(function (p) {
      var hit = all.some(function (e) { return e.start < p.end && p.start < e.end; });
      if (!hit) list.push(p);
    });
    if (!list.length) return s;
    list.sort(function (a, b) { return b.start - a.start; });
    list.forEach(function (e) {
      s = s.slice(0, e.start) + e.masked + s.slice(e.end);
    });
    return s;
  }

  return {
    mask: mask,
    redactText: redactText,
    findNameSpans: findNameSpans,
    explainUnits: explainUnits,
    findOtpSpans: findOtpSpans,
    findOtpSpansSegments: findOtpSpansSegments,
    redactOtpSegments: redactOtpSegments,
    otpSegWindow: otpSegWindow,
    findCardSpans: findCardSpans,
    redactCardSegments: redactCardSegments,
    redactPersona: redactPersona,
    redactDialogSegments: redactDialogSegments,
    maskBankCard: maskBankCard,
    formatCardGroups: formatCardGroups,
    maskPhone: maskPhone,
    maskCrypto: maskCrypto,
    maskQQ: maskQQ,
    maskHandle: maskHandle,
    maskIdCard: maskIdCard,
    maskName: maskName,
    maskEmail: maskEmail,
    maskUrl: maskUrl
  };
});
