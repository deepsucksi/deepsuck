/*!
 * DeepSuck — intel.js
 * 公开情报库的发布策略、条目校验、提交格式与 CSV 导出（浏览器与 Node 共用）。
 *
 * 发布策略（与 site/intel.html、docs/INTEL.md 一致）：
 *   完整公开：诈骗电话、加密货币钱包地址、诈骗网址/域名、APP/平台名称、话术/手法模式
 *   部分打码：银行卡号、收款户名/姓名、身份证号、支付宝/微信/QQ/邮箱等个人账号
 *     —— 很多"跑分卡/收款卡"属于被利用、被冒用的普通人，公开完整信息可能伤及无辜。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var R = isNode ? require('./redact.js') : root.DeepSuck.redact;
  var mod = factory(R);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.intel = mod; }
})(typeof self !== 'undefined' ? self : this, function (R) {
  'use strict';

  var SCHEMA = 'deepsuck.intel-library/v1';
  var SUBMISSION_SCHEMA = 'deepsuck.intel-submission/v1';

  // 情报库条目类型（比提取器类型更粗一层，便于检索）
  var TYPES = {
    phone: { label: '诈骗电话', policy: 'full', icon: '📞' },
    crypto_wallet: { label: '加密钱包地址', policy: 'full', icon: '🪙' },
    url: { label: '诈骗网址/域名', policy: 'full', icon: '🔗' },
    app: { label: 'APP/平台名称', policy: 'full', icon: '📱' },
    script: { label: '话术/手法', policy: 'full', icon: '🗣️' },
    bank_card: { label: '收款银行卡', policy: 'masked', icon: '💳' },
    account: { label: '支付宝/微信/QQ 等账号', policy: 'masked', icon: '💬' },
    name: { label: '收款户名/姓名', policy: 'masked', icon: '👤' },
    id_card: { label: '身份证号', policy: 'masked', icon: '🪪' }
  };

  // 提取器类型 -> 情报库类型
  var FROM_EXTRACTOR = {
    phone: 'phone', crypto_btc: 'crypto_wallet', crypto_eth: 'crypto_wallet', crypto_tron: 'crypto_wallet',
    url: 'url', app_name: 'app', bank_card: 'bank_card', alipay: 'account', wechat: 'account', qq: 'account',
    email: 'account', name: 'name', id_card: 'id_card'
  };
  var CHAIN = { crypto_btc: 'Bitcoin', crypto_eth: 'Ethereum/EVM', crypto_tron: 'TRON' };

  function libraryType(extractorType) { return FROM_EXTRACTOR[extractorType] || null; }
  function policyOf(libType) { return (TYPES[libType] || { policy: 'masked' }).policy; }

  /** 统一格式：电话去掉分隔符与 +86；URL 去掉尾部标点；其他原样 */
  function normalize(extractorType, raw) {
    var s = String(raw == null ? '' : raw).trim();
    if (extractorType === 'phone') {
      var d = s.replace(/\D/g, '');
      if (d.length === 13 && d.indexOf('86') === 0) d = d.slice(2);
      return d;
    }
    if (extractorType === 'url') return s.replace(/[.,;:!?'"）)\]。，；！？、]+$/, '');
    return s;
  }

  /**
   * 按发布策略生成公开值：full 类型返回规范化后的完整值，masked 类型返回 redact.js 打码结果。
   * 未知类型一律打码（保守）。
   */
  function publishValue(extractorType, raw) {
    var lt = libraryType(extractorType);
    if (lt && policyOf(lt) === 'full') return normalize(extractorType, raw);
    return R.mask(extractorType, raw);
  }

  var REQUIRED = ['id', 'type', 'value', 'scenario', 'firstSeen', 'source', 'status'];
  var STATUSES = ['active', 'disputed', 'removed'];
  var SOURCES = ['example', 'sandbox', 'community', 'honeypot', 'public-report'];

  /** 校验单条情报，返回错误数组（空数组表示通过） */
  function validateEntry(e) {
    var errs = [];
    if (!e || typeof e !== 'object') return ['不是对象'];
    REQUIRED.forEach(function (k) { if (e[k] == null || e[k] === '') errs.push('缺少字段 ' + k); });
    if (e.type && !TYPES[e.type]) errs.push('未知类型 ' + e.type);
    if (e.status && STATUSES.indexOf(e.status) < 0) errs.push('未知状态 ' + e.status);
    if (e.source && SOURCES.indexOf(e.source) < 0) errs.push('未知来源 ' + e.source);
    if (e.firstSeen && !/^\d{4}-\d{2}-\d{2}$/.test(e.firstSeen)) errs.push('firstSeen 须为 YYYY-MM-DD');
    if (e.type && TYPES[e.type] && TYPES[e.type].policy === 'masked' && e.value) {
      // 打码类型不得出现长串连续数字（防止误把完整卡号/身份证号提交进库）
      if (/\d{7,}/.test(String(e.value).replace(/\s/g, ' '))) errs.push('打码类型的 value 含有 7 位以上连续数字，疑似未脱敏');
      if (e.type === 'name' && !/\*/.test(e.value)) errs.push('姓名须打码（如 王*）');
    }
    if (e.source === 'example' && e.example !== true) errs.push('示例数据须标注 example: true');
    return errs;
  }

  function validateLibrary(lib) {
    var errs = [];
    if (!lib || lib.schema !== SCHEMA) errs.push('schema 应为 ' + SCHEMA);
    var ids = {};
    (lib && lib.entries || []).forEach(function (e, i) {
      validateEntry(e).forEach(function (m) { errs.push('#' + i + ' ' + (e && e.id) + ': ' + m); });
      if (e && e.id) { if (ids[e.id]) errs.push('重复 id ' + e.id); ids[e.id] = 1; }
    });
    return errs;
  }

  /** 过滤：q 关键字（匹配 value/notes/tags/scenario），type，scenario，status */
  function filterEntries(entries, f) {
    f = f || {};
    var q = String(f.q || '').trim().toLowerCase();
    var qDigits = q.replace(/[\s-]/g, '');
    return (entries || []).filter(function (e) {
      if (f.type && e.type !== f.type) return false;
      if (f.scenario && e.scenario !== f.scenario) return false;
      if (f.status && e.status !== f.status) return false;
      if (!f.status && e.status === 'removed') return false;
      if (!q) return true;
      var hay = [e.value, e.notes, e.scenario, e.chain, e.bank, (e.tactics || []).join(' '), (e.tags || []).join(' ')].join(' ').toLowerCase();
      if (hay.indexOf(q) >= 0) return true;
      return qDigits.length >= 4 && String(e.value || '').replace(/[\s-]/g, '').toLowerCase().indexOf(qDigits) >= 0;
    });
  }

  var CSV_COLS = ['id', 'example', 'type', 'value', 'chain', 'bank', 'scenario', 'tactics', 'firstSeen', 'lastSeen', 'reports', 'source', 'confidence', 'status', 'notes'];
  function csvCell(v) {
    if (v == null) return '';
    if (Array.isArray(v)) v = v.join('|');
    v = String(v);
    if (/^[=+\-@]/.test(v)) v = "'" + v; // 防 CSV 公式注入
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }
  function toCSV(entries) {
    var lines = [CSV_COLS.join(',')];
    (entries || []).forEach(function (e) { lines.push(CSV_COLS.map(function (c) { return csvCell(e[c]); }).join(',')); });
    return '\ufeff' + lines.join('\r\n') + '\r\n'; // BOM：Excel 正确识别 UTF-8 中文
  }

  /**
   * 由会话生成"情报库提交"内容（遵循发布策略）。
   * rawIntel: [{ type(提取器类型), raw, masked, meta, count }]
   */
  function buildSubmission(opts) {
    opts = opts || {};
    var indicators = (opts.rawIntel || []).map(function (i) {
      var lt = libraryType(i.type);
      if (!lt) return null;
      var o = { type: lt, value: publishValue(i.type, i.raw), policy: policyOf(lt), seen: i.count || 1 };
      if (CHAIN[i.type]) o.chain = CHAIN[i.type];
      if (i.meta && i.meta.bank) o.bank = i.meta.bank;
      if (i.meta && i.meta.kind) o.kind = i.meta.kind;
      return o;
    }).filter(Boolean);
    (opts.apps || []).forEach(function (a) { indicators.push({ type: 'app', value: a, policy: 'full', seen: 1 }); });
    return {
      schema: SUBMISSION_SCHEMA,
      scenario: opts.scenario || null,
      tactics: opts.tactics || [],
      indicators: indicators,
      note: '提交前请确认：以上信息来自你本人真实遇到的诈骗（沙盒虚构样例请勿提交）；银行卡、姓名、个人账号已按策略打码。'
    };
  }

  function submissionMarkdown(sub) {
    var lines = sub.indicators.map(function (i) {
      return '- ' + (TYPES[i.type] ? TYPES[i.type].label : i.type) + '：`' + i.value + '`' +
        (i.chain ? '（' + i.chain + '）' : '') + (i.bank ? '（' + i.bank + '）' : '') + (i.policy === 'masked' ? ' ［已打码］' : '');
    });
    return lines.join('\n');
  }

  return {
    SCHEMA: SCHEMA, SUBMISSION_SCHEMA: SUBMISSION_SCHEMA, TYPES: TYPES, STATUSES: STATUSES, SOURCES: SOURCES,
    libraryType: libraryType, policyOf: policyOf, normalize: normalize, publishValue: publishValue,
    validateEntry: validateEntry, validateLibrary: validateLibrary, filterEntries: filterEntries,
    toCSV: toCSV, CSV_COLS: CSV_COLS, buildSubmission: buildSubmission, submissionMarkdown: submissionMarkdown
  };
});
