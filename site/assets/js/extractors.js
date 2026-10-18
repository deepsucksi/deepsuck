/*!
 * DeepSuck — extractors.js
 * 情报提取器：从诈骗方消息中识别银行卡、手机号、钱包地址、URL、QQ/微信/支付宝等。
 * 所有敏感结果都附带 masked 字段（来自 redact.js），UI 与导出只能使用 masked。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var R = isNode ? require('./redact.js') : root.DeepSuck.redact;
  var N = isNode ? require('./normalize.js') : root.DeepSuck.normalize;
  var C = isNode ? require('../core/extractors.json') : root.DeepSuck.coreData.extractors;
  var B = isNode ? require('./cardbin.js') : root.DeepSuck.cardbin;
  var mod = factory(R, N, C, B);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.extractors = mod; }
})(typeof self !== 'undefined' ? self : this, function (R, N, C, B) {
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
  // ASR 数字规整（ITN）会把“张三”转成“张3”：单个阿拉伯数字还原为汉字（等长，脱敏区间不变）
  var NAME_DIGITS = '零一二三四五六七八九';
  function cleanName(n) {
    n = n.replace(/[0-9]/g, function (d) { return NAME_DIGITS.charAt(+d); });
    if (NOT_NAMES.test(n)) return null;
    var cut = n.search(/[开卡银账的是在和与就吧了啊呢哦，电手微那呃嗯合你我他她这打转加对说哈]/);
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
      var meta = { digits: d.length, luhn: luhn(d), unionpay: /^62/.test(d), bank: bank };
      // 本地 BIN 表（hexindai/bcbc，MIT）：只记录发卡行与卡种，不记录 BIN 数字本身（避免比打码值多暴露两位）
      var bin = B ? B.lookup(d) : null;
      if (bin) {
        meta.issuer = { bank: bin.bank, bankCode: bin.bankCode, cardType: bin.cardType, cardTypeName: bin.cardTypeName, lengthOk: bin.lengthOk };
        if (!bank) { meta.bank = bin.bank; meta.bankFrom = 'bin'; }
      }
      return meta;
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

  // ---- 跨回合拼接 ----
  var ST = C.stitch || {};
  var SEP_CLS = '[' + C.obfuscation.digitJoin.separators.replace(/[\]\\^\-]/g, '\\$&').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t') + ']';
  var FRAG = '[0-9](?:' + SEP_CLS + '{0,3}[0-9])*';
  var RE_TAIL = new RegExp('(' + FRAG + ')(' + (ST.tailFiller || '$').replace(/\$$/, '') + ')$');
  var RE_HEAD = new RegExp('(' + (ST.headFiller || '^').replace(/^\^/, '') + ')(' + FRAG + ')');
  var RE_TAIL_ONLY = new RegExp('^' + (ST.tailFiller || '$'));
  var RE_UNIT = new RegExp(C.obfuscation.digitJoin.unitAfter);
  var RE_BANK_CTX = new RegExp(ST.bankContext || '卡号');
  var RE_PHONE_CTX = new RegExp(ST.phoneContext || '电话');

  var RE_BLOCK_BEFORE = ST.blockBefore ? new RegExp(ST.blockBefore) : null;
  var RE_BLOCK_AFTER = ST.blockAfter ? new RegExp(ST.blockAfter) : null;
  var NUMERALS = C.obfuscation.numerals;
  var RE_NUMERAL_CHAR = new RegExp('[' + Object.keys(NUMERALS).join('') + ']', 'g');

  function round2(x) { return Math.round(x * 100) / 100; }

  /** 一个回合的首/尾数字片段（规范化文本坐标 + 原文坐标），被单回合提取认领过的片段不参与拼接 */
  function fragments(raw) {
    var norm = N.normalize(raw), ents = extractSensitive(raw);
    // 片段可能短于 numeralRunMin（“二二三三”），这里把中文数字逐字换成阿拉伯数字（等长，坐标不变）
    var s = norm.text.replace(RE_NUMERAL_CHAR, function (c) { return NUMERALS[c]; });
    function free(a, b) {
      var sp = norm.span(a, b);
      return !ents.some(function (e) { return e.start < sp[1] && e.end > sp[0]; });
    }
    function mk(a, b, extra) {
      var sp = norm.span(a, b);
      var o = { start: sp[0], end: sp[1], digits: s.slice(a, b).replace(/[^0-9]/g, ''), ns: a, ne: b };
      for (var k in extra) o[k] = extra[k];
      return o;
    }
    var out = { text: s, ents: ents, head: null, tail: null };
    var t = RE_TAIL.exec(s);
    if (t) {
      var a = t.index, b = a + t[1].length;
      if (free(a, b) && !(RE_BLOCK_BEFORE && RE_BLOCK_BEFORE.test(s.slice(Math.max(0, a - 16), a)))) out.tail = mk(a, b, { before: s.slice(Math.max(0, a - 16), a) });
    }
    var h = RE_HEAD.exec(s);
    if (h && h.index === 0) {
      var a2 = h[1].length, b2 = a2 + h[2].length, rest = s.slice(b2);
      if (free(a2, b2) && !RE_UNIT.test(rest) && !(RE_BLOCK_AFTER && RE_BLOCK_AFTER.test(rest))) out.head = mk(a2, b2, { only: RE_TAIL_ONLY.test(rest) });
    }
    if (out.tail && RE_UNIT.test(s.slice(out.tail.ne))) out.tail = null;
    return out;
  }

  function score(d, ctx) {
    var kind = N.plausibleNumber(d);
    if (!kind) return null;
    if (kind === 'phone') return { type: 'phone', conf: round2(0.6 + (RE_PHONE_CTX.test(ctx) ? 0.3 : 0)), meta: { kind: 'mobile' } };
    var bin = B ? B.lookup(d) : null, lu = luhn(d);
    var conf = 0.3 + (lu ? 0.3 : 0) + (bin ? 0.2 : 0) + (bin && bin.lengthOk ? 0.1 : 0) + (/^62/.test(d) ? 0.1 : 0) + (RE_BANK_CTX.test(ctx) ? 0.2 : 0);
    var meta = { digits: d.length, luhn: lu, unionpay: /^62/.test(d), bank: null };
    for (var i = 0; i < BANKS.length; i++) if (ctx.indexOf(BANKS[i]) >= 0) { meta.bank = BANKS[i]; break; }
    if (bin) {
      meta.issuer = { bank: bin.bank, bankCode: bin.bankCode, cardType: bin.cardType, cardTypeName: bin.cardTypeName, lengthOk: bin.lengthOk };
      if (!meta.bank) { meta.bank = bin.bank; meta.bankFrom = 'bin'; }
    }
    return { type: 'bank_card', conf: round2(Math.min(1, conf)), meta: meta };
  }

  /**
   * stitch(turns, opts) -> StitchedEntity[]
   * turns：同一说话方相邻回合的原文（按时间顺序）。把上一回合末尾的数字片段与下一回合开头的数字片段拼接后校验，
   * 用于语音回合被切断（卡号念到一半停顿）。返回 { type, label, value, masked, sensitive, confidence, turns:[i..j],
   * parts:[{turn, start, end, masked}]（原文坐标与该片段应显示的打码文本）, meta: {..., stitched: true} }。
   * 任一片段本身已被单回合提取认领、拼接结果与窗口内已有情报相同、或置信度低于 minConfidence 时不输出。
   */
  function stitch(turns, opts) {
    opts = opts || {};
    var W = opts.window || ST.window || 3, minConf = opts.minConfidence != null ? opts.minConfidence : (ST.minConfidence || 0.5);
    var F = (turns || []).map(function (t) { return fragments(String(t == null ? '' : t)); });
    var out = [], seen = {};
    F.forEach(function (f) { f.ents.forEach(function (e) { seen[e.type + '|' + String(e.value).replace(/[^0-9A-Za-z]/g, '').toLowerCase()] = 1; }); });
    for (var i = 0; i < F.length; i++) {
      var tail = F[i].tail;
      if (!tail || tail.digits.length < 3) continue;
      var parts = [{ turn: i, f: tail }], d = tail.digits, best = null;
      for (var j = i + 1; j < F.length && j < i + W; j++) {
        var h = F[j].head;
        if (!h || (j > i + 1 && !parts[parts.length - 1].f.only)) break;
        if (j > i + 1 && !F[j - 1].head) break;
        parts.push({ turn: j, f: h });
        d += h.digits;
        if (d.length > 19) break;
        var sc = score(d, tail.before + F[i].text.slice(tail.ns, tail.ne));
        if (sc && sc.conf >= minConf && (!best || sc.conf > best.sc.conf || (sc.conf === best.sc.conf && d.length > best.d.length))) best = { sc: sc, d: d, parts: parts.slice() };
      }
      if (!best) continue;
      var key = best.sc.type + '|' + best.d;
      if (seen[key]) continue;
      seen[key] = 1;
      var masked = R.mask(best.sc.type, best.d), off = 0, same = masked.length === best.d.length;
      var meta = best.sc.meta; meta.stitched = true;
      out.push({
        type: best.sc.type, label: LABELS[best.sc.type], value: best.d, masked: masked, sensitive: true, confidence: best.sc.conf,
        turns: best.parts.map(function (p) { return p.turn; }),
        parts: best.parts.map(function (p) {
          var n = p.f.digits.length, m = same ? masked.slice(off, off + n) : new Array(n + 1).join('*');
          off += n;
          return { turn: p.turn, start: p.f.start, end: p.f.end, masked: m };
        }),
        meta: meta
      });
      i = best.parts[best.parts.length - 1].turn - 1; // 已用掉的回合不再作为起点
    }
    return out;
  }

  /** 只取敏感情报（账户/地址/联系方式等） */
  function extractSensitive(text) {
    return extract(text).filter(function (e) { return e.sensitive; });
  }

  return { extract: extract, extractSensitive: extractSensitive, stitch: stitch, STITCH: ST, luhn: luhn, LABELS: LABELS, BANKS: BANKS, CHANNELS: CHANNELS, RE: RE, normalize: N.normalize };
});
