/*!
 * DeepSuck — extractors.js
 * 情报提取器：从诈骗方消息中识别银行卡、手机号、钱包地址、URL、QQ/微信/支付宝等。
 * 所有敏感结果都附带 masked 字段（来自 redact.js），UI 与导出只能使用 masked。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var R = isNode ? require('./redact.js') : root.DeepSuck.redact;
  var N = isNode ? require('./normalize.js') : root.DeepSuck.normalize;
  var C = isNode ? require('../core/extractors.json') : root.DeepSuck.coreData.extractors;
  var mod = factory(R, N, C);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.extractors = mod; }
})(typeof self !== 'undefined' ? self : this, function (R, N, C) {
  'use strict';

  // 规则数据（标签、银行、渠道、正则）统一维护在 site/assets/core/extractors.json，JS 与未来的 Python 实现共用
  var LABELS = C.labels;
  var BANKS = C.banks;
  var CHANNELS = C.channels;
  var RE = {};
  Object.keys(C.patterns).forEach(function (k) { RE[k] = new RegExp(C.patterns[k].source, C.patterns[k].flags); });

  function luhn(num) {
    var d = String(num).replace(/\D/g, '');
    var sum = 0, alt = false;
    for (var i = d.length - 1; i >= 0; i--) {
      var n = +d.charAt(i);
      if (alt) { n *= 2; if (n > 9) n -= 9; }
      sum += n; alt = !alt;
    }
    return d.length > 0 && sum % 10 === 0;
  }

  function overlaps(spans, s, e) {
    for (var i = 0; i < spans.length; i++) {
      if (s < spans[i][1] && e > spans[i][0]) return true;
    }
    return false;
  }

  function trimUrl(u) { return u.replace(/[.,;:!?'"）)\]]+$/, ''); }

  var NOT_NAMES = /^(?:姓名|是谁|写清|发我|多少|什么|哪个|一下|清楚)/;
  function cleanName(n) {
    if (NOT_NAMES.test(n)) return null;
    var cut = n.search(/[开卡银账的是在和与就吧了啊呢哦，]/);
    if (cut >= 2) n = n.slice(0, cut);
    return n.length >= 2 ? n : null;
  }

  /**
   * extract(text) -> Entity[]
   * Entity: { type, label, value, masked, start, end, sensitive, meta }
   * value 只保存在内存中，用于去重；任何展示/导出都应使用 masked。
   */
  function extract(text) {
    var raw = String(text || '');
    var norm = N.normalize(raw);
    var s = norm.text;
    var out = [];
    var claimed = [];

    function scan(re, type, opts) {
      opts = opts || {};
      re.lastIndex = 0;
      var m;
      while ((m = re.exec(s)) !== null) {
        var raw = opts.group ? m[opts.group] : m[0];
        if (!raw) continue;
        var start = opts.group ? m.index + m[0].lastIndexOf(raw) : m.index;
        if (opts.clean) {
          var c = opts.clean(raw, m, start);
          if (!c) continue;
          raw = c;
        }
        var end = start + raw.length;
        var sensitive = opts.sensitive !== false;
        if (sensitive && overlaps(claimed, start, end)) continue;
        if (!sensitive && opts.noOverlap && overlaps(claimed, start, end)) continue;
        var meta = opts.meta ? opts.meta(raw, m, start) : {};
        if (meta === false) continue;
        var t = opts.typeOf ? opts.typeOf(raw, meta) : type;
        out.push({
          type: t,
          label: LABELS[t] || t,
          value: raw,
          masked: sensitive ? R.mask(t, raw) : raw,
          start: start,
          end: end,
          sensitive: sensitive,
          meta: meta || {}
        });
        if (sensitive) claimed.push([start, end]);
      }
    }

    scan(RE.urlFull, 'url', { clean: trimUrl });
    scan(RE.alipay, 'alipay', { group: 1 });
    scan(RE.qq, 'qq', { group: 1 });
    scan(RE.wechat, 'wechat', { group: 1 });
    scan(RE.email, 'email');
    scan(RE.urlBare, 'url', { clean: trimUrl, meta: function (raw) {
      // 排除像 "1.5com" 这类误报：至少含一个字母的主机标签
      return /[a-z]/i.test(raw.split('.')[0]) ? { bare: true } : false;
    } });
    scan(RE.eth, 'crypto_eth', { meta: function () { return { chain: 'Ethereum/EVM' }; } });
    scan(RE.tron, 'crypto_tron', { meta: function () { return { chain: 'TRON' }; } });
    scan(RE.btc, 'crypto_btc', { meta: function () { return { chain: 'Bitcoin' }; } });
    scan(RE.idCard, 'id_card', { meta: function (raw, m, start) {
      var before = s.slice(Math.max(0, start - 12), start);
      var ctx = /身份证|证件号|身份号/.test(before);
      if (!ctx && /^62/.test(raw) && luhn(raw)) return false; // 更像 62 开头的银联卡
      return { context: ctx };
    } });
    scan(RE.bankCard, 'bank_card', { meta: function (raw, m, start) {
      var d = raw.replace(/\D/g, '');
      if (d.length < 16 || d.length > 19) return false;
      if (/^(\d)\1+$/.test(d)) return false;
      var ctx = s.slice(Math.max(0, start - 24), Math.min(s.length, start + raw.length + 24));
      var bank = null;
      for (var i = 0; i < BANKS.length; i++) { if (ctx.indexOf(BANKS[i]) >= 0) { bank = BANKS[i]; break; } }
      return { digits: d.length, luhn: luhn(d), unionpay: /^62/.test(d), bank: bank };
    } });
    scan(RE.hotline, 'phone', { meta: function () { return { kind: 'hotline' }; } });
    scan(RE.landline, 'phone', { meta: function () { return { kind: 'landline' }; } });
    scan(RE.mobile, 'phone', { meta: function () { return { kind: 'mobile' }; } });
    scan(RE.name, 'name', { group: 1, clean: cleanName });

    // 非敏感的上下文情报（不打码、不占用区间）
    scan(RE.amount, 'amount', { sensitive: false, noOverlap: true, meta: function (raw, m) {
      return { number: parseFloat(m[1]), unit: m[2] };
    } });
    scan(RE.appName, 'app_name', { group: 1, sensitive: false });
    var appSeen = {};
    out.forEach(function (e) { if (e.type === 'app_name') appSeen[e.value] = 1; });
    scan(RE.appQuoted, 'app_name', { group: 1, sensitive: false, clean: function (raw) { return appSeen[raw] ? null : raw; } });
    BANKS.forEach(function (b) {
      var i = s.indexOf(b);
      if (i >= 0) out.push({ type: 'bank_name', label: LABELS.bank_name, value: b, masked: b, start: i, end: i + b.length, sensitive: false, meta: {} });
    });
    var seenCh = {};
    CHANNELS.forEach(function (c) {
      var i = s.indexOf(c);
      var key = c.toLowerCase();
      if (i >= 0 && !seenCh[key]) {
        seenCh[key] = 1;
        out.push({ type: 'channel', label: LABELS.channel, value: c, masked: c, start: i, end: i + c.length, sensitive: false, meta: {} });
      }
    });

    if (norm.changed) {
      // 映射回原文位置（脱敏时替换原文片段）；value 保留规范化后的值，便于去重与比对
      out.forEach(function (e) {
        var sp = norm.span(e.start, e.end);
        if (e.sensitive === false) e.raw = raw.slice(sp[0], sp[1]);
        e.start = sp[0]; e.end = sp[1];
        if (e.sensitive) e.obfuscated = raw.slice(sp[0], sp[1]) !== e.value;
      });
    }
    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }

  /** 只取敏感情报（账户/地址/联系方式等） */
  function extractSensitive(text) {
    return extract(text).filter(function (e) { return e.sensitive; });
  }

  return { extract: extract, extractSensitive: extractSensitive, luhn: luhn, LABELS: LABELS, BANKS: BANKS, CHANNELS: CHANNELS, RE: RE, normalize: N.normalize };
});
