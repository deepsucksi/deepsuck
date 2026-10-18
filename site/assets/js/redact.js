/*!
 * DeepSuck — redact.js
 * 脱敏模块：所有对外展示 / 导出的情报都必须经过这里。
 * Apache-2.0
 */
(function (root, factory) {
  var mod = factory();
  if (typeof module === 'object' && module.exports) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.redact = mod; }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function digitsOnly(s) { return String(s || '').replace(/\D/g, ''); }

  function stars(n) { return new Array(Math.max(0, n) + 1).join('*'); }

  /** 6222 0212 3456 1234 -> 6222 **** **** 1234 */
  function maskBankCard(v) {
    var d = digitsOnly(v);
    if (d.length < 8) return stars(d.length);
    return d.slice(0, 4) + ' **** **** ' + d.slice(-4);
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

  /**
   * 将一段文本中的敏感片段替换成脱敏结果。
   * entities: extractors.extract() 返回的数组（含 start/end/type/value）
   */
  function redactText(text, entities) {
    var s = String(text || '');
    if (!entities || !entities.length) return s;
    var list = entities
      .filter(function (e) { return typeof e.start === 'number' && e.sensitive !== false; })
      .slice()
      .sort(function (a, b) { return b.start - a.start; });
    list.forEach(function (e) {
      s = s.slice(0, e.start) + (e.masked || mask(e.type, e.value)) + s.slice(e.end);
    });
    return s;
  }

  return {
    mask: mask,
    redactText: redactText,
    maskBankCard: maskBankCard,
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
