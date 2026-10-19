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
    findOtpSpans: findOtpSpans,
    findOtpSpansSegments: findOtpSpansSegments,
    redactOtpSegments: redactOtpSegments,
    otpSegWindow: otpSegWindow,
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
