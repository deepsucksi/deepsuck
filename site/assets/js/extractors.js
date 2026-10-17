/*!
 * DeepSuck — extractors.js
 * 情报提取器：从诈骗方消息中识别银行卡、手机号、钱包地址、URL、QQ/微信/支付宝等。
 * 所有敏感结果都附带 masked 字段（来自 redact.js），UI 与导出只能使用 masked。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function (root, factory) {
  var R = (typeof module === 'object' && module.exports) ? require('./redact.js') : root.DeepSuck.redact;
  var mod = factory(R);
  if (typeof module === 'object' && module.exports) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.extractors = mod; }
})(typeof self !== 'undefined' ? self : this, function (R) {
  'use strict';

  var LABELS = {
    bank_card: '银行卡号',
    phone: '电话号码',
    crypto_btc: 'BTC 地址',
    crypto_eth: 'ETH/ERC20 地址',
    crypto_tron: 'TRON/TRC20 地址',
    url: '网址/域名',
    email: '邮箱',
    qq: 'QQ 号',
    wechat: '微信号',
    alipay: '支付宝账号',
    id_card: '身份证号',
    name: '收款户名',
    bank_name: '开户银行',
    amount: '涉及金额',
    channel: '支付/联络渠道',
    app_name: 'APP/平台名称'
  };

  var BANKS = ['工商银行', '工行', '建设银行', '建行', '农业银行', '农行', '中国银行', '中行', '交通银行', '交行',
    '招商银行', '招行', '邮储银行', '邮政储蓄', '浦发银行', '民生银行', '兴业银行', '光大银行', '中信银行',
    '华夏银行', '平安银行', '广发银行', '北京银行', '上海银行', '农商银行', '农村信用社', '信用社'];

  var CHANNELS = ['支付宝', '微信', '银行卡', 'USDT', '泰达币', '比特币', '以太坊', '数字人民币', '云闪付',
    'Telegram', 'telegram', '飞机', 'TG', '抖音', 'QQ', 'WhatsApp', 'Zoom', '腾讯会议'];

  // 统一的"字符边界"：避免从更长的字母数字串中截出一段
  var NB = '(?<![0-9A-Za-z])';
  var NA = '(?![0-9A-Za-z])';
  var URL_STOP = '\\s，。！？；、“”"\'<>（）()【】\\u4e00-\\u9fa5';
  var TLDS = 'com|cn|net|org|top|xyz|vip|cc|app|io|me|shop|site|online|club|info|link|live|pro|biz|tk|icu|work|fun|asia|hk|tw';

  var RE = {
    urlFull: new RegExp('(?:https?:\\/\\/|www\\.)[^' + URL_STOP + ']+', 'gi'),
    urlBare: new RegExp('(?<![@\\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+(?:' + TLDS + ')(?:\\/[^' + URL_STOP + ']*)?(?![\\w-])', 'gi'),
    email: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g,
    eth: new RegExp(NB + '0x[a-fA-F0-9]{40}' + NA, 'g'),
    tron: new RegExp(NB + 'T[1-9A-HJ-NP-Za-km-z]{33}' + NA, 'g'),
    btc: new RegExp(NB + '(?:bc1[ac-hj-np-z02-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})' + NA, 'g'),
    idCard: /(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![\dA-Za-z])/g,
    bankCard: /(?<![\dA-Za-z])\d{4}(?:[ -]?\d{4}){3}(?:[ -]?\d{1,3})?(?![\dA-Za-z])/g,
    alipay: /(?:支付宝|zfb|ZFB)(?:账号|账户|号)?\s*(?:是|为|叫)?\s*[:：]?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?:\+?86)?1[3-9]\d{9})(?!\d)/g,
    qq: /(?:QQ|qq|Qq|扣扣|企鹅)(?:号|群)?(?:码)?\s*(?:是|为|叫)?\s*[:：]?\s*([1-9]\d{4,11})(?!\d)/g,
    wechat: /(?:微信|VX|vx|Vx|V信|v信|wx|WX|薇信|威信|徽信)(?:号)?\s*(?:是|为|叫)?\s*[:：]?\s*([a-zA-Z][-_a-zA-Z0-9]{5,19})(?![-_a-zA-Z0-9])/g,
    hotline: /(?<!\d)(?:400|800)[\s-]?\d{3}[\s-]?\d{4}(?!\d)/g,
    landline: /(?<!\d)0\d{2,3}-\d{7,8}(?!\d)/g,
    mobile: /(?<!\d)(?:\+?86[\s-]?)?1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}(?!\d)/g,
    name: /(?:户名|收款人|开户名|收款户名|账户名|持卡人)\s*(?:是|为|叫)?\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})/g,
    amount: /(\d+(?:\.\d+)?)\s*(万元|万|元|块钱|块|USDT|U(?![A-Za-z])|美元)/g,
    appName: /(?:下载|安装|打开)(?:一个|一下|个)?[“"「『]?([\u4e00-\u9fa5A-Za-z0-9]{2,12}?)[”"」』]?(?:APP|app|App|软件|客户端)/g
  };

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
    var cut = n.search(/[开卡银账的是在和与，]/);
    if (cut >= 2) n = n.slice(0, cut);
    return n.length >= 2 ? n : null;
  }

  /**
   * extract(text) -> Entity[]
   * Entity: { type, label, value, masked, start, end, sensitive, meta }
   * value 只保存在内存中，用于去重；任何展示/导出都应使用 masked。
   */
  function extract(text) {
    var s = String(text || '');
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

    out.sort(function (a, b) { return a.start - b.start; });
    return out;
  }

  /** 只取敏感情报（账户/地址/联系方式等） */
  function extractSensitive(text) {
    return extract(text).filter(function (e) { return e.sensitive; });
  }

  return { extract: extract, extractSensitive: extractSensitive, luhn: luhn, LABELS: LABELS, BANKS: BANKS, RE: RE };
});
