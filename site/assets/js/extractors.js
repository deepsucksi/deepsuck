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
  var STOP = isNode ? require('../core/name_stopchars.json') : root.DeepSuck.coreData.name_stopchars;
  var B = isNode ? require('./cardbin.js') : root.DeepSuck.cardbin;
  var mod = factory(R, N, C, B, STOP);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.extractors = mod; }
})(typeof self !== 'undefined' ? self : this, function (R, N, C, B, STOP) {
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

  var NR = C.nameRules;
  var NOT_NAMES = new RegExp(NR.notNames);
  // #185 应答字、虚词共用字表（core/name_stopchars.json）：取到的名字以这些字开头时不算（「户名对得上就行」）
  // surname=false 的字一律不当名字开头；surname=true 的字可能是真姓，只有后面紧跟的文字匹配 after 时才放行，拿不准就照常当姓名
  var NAME_STOPCHARS = {};
  STOP.chars.forEach(function (r) { NAME_STOPCHARS[r.char] = r.surname ? new RegExp('^(?:' + r.after + ')') : null; });
  var NAME_STOPWORDS = (STOP.words || []).map(function (r) { return r.word; });
  function stopName(n, m, start) {
    if (NAME_STOPWORDS.some(function (w) { return n.indexOf(w) === 0; })) return true;
    var c = n.charAt(0);
    if (!Object.prototype.hasOwnProperty.call(NAME_STOPCHARS, c)) return false;
    var after = NAME_STOPCHARS[c];
    if (!after) return true;
    var rest = m && start != null ? m.input.slice(start + 1) : n.slice(1);
    return after.test(rest);
  }
  /** #201 人设侧共用（llm.js maskNames、engine.js vagueDigits）：打码姓名「c**」里星号前那个字 c 在共用字表里时，按字表判断它在
   *  rest（c 后面的文字，从星号起）前面算不算「不当姓」：surname=false → true；surname=true → rest 匹配 after 才 true，否则 false
   *  （拿不准就当姓名，照样换成「那个名字」）。c 不在字表里返回 null，由调用方按自己的 notSurname 判断。与 Python stop_surname 一致。 */
  function stopSurname(c, rest) {
    if (!Object.prototype.hasOwnProperty.call(NAME_STOPCHARS, c)) return null;
    var after = NAME_STOPCHARS[c];
    return !after || after.test(String(rest || ''));
  }
  /** #201：打码姓名正则（星号紧跟在姓 sur 后面）在 str 的 off 处匹配到 m 时，sur 是不是「不当姓」。复姓一律算姓；
   *  单字先查共用字表（stopSurname），不在表里的再看 fallback（personas.json 的 notSurname）。与 Python masked_lead_not_surname 一致。
   *  拿不准就当姓名：可能是真姓的字（surname=true）后面只跟 1–3 个星号时，正好是脱敏后的 2–4 字姓名（「户名有志强」→「户名有**」），
   *  不放行；4 个及以上星号（「我只有****块钱」）才按字表的 after 放行。 */
  var SHORT_STARS = /^[*＊]{1,3}(?![*＊])/;
  var MC = STOP.maskContext || {};
  var NUMBER_BEFORE = new RegExp(MC.numberBefore || '(?!)');
  var NOT_NAME_AFTER = new RegExp('^(?:' + (MC.notNameAfter || '(?!)') + ')');
  /** #206 第六条探针：str 里 pos 处开始的星号按上下文不当姓名（号码语境「验证码是***」「转到**」，或「我在***上班」）。与 Python stars_not_name 一致。 */
  var NAME_AFTER = new RegExp('^(?:' + (MC.nameAfter || '(?!)') + ')');
  var NAME_BEFORE = new RegExp(MC.nameBefore || '(?!)');
  /** #214 审查：str 里 pos 处开始的星号前面是「户名、收款人、名下、对方叫」或后面跟「名下、的卡、的账户」等，是姓名。与 Python stars_name 一致。 */
  function starsName(str, pos) { str = String(str); return NAME_BEFORE.test(str.slice(0, pos)) || NAME_AFTER.test(str.slice(pos)); }
  function starsNotName(str, pos) {
    str = String(str);
    if (starsName(str, pos)) return false; // #214：「转到**名下」「打到**的卡上」仍是姓名
    return NUMBER_BEFORE.test(str.slice(0, pos)) || NOT_NAME_AFTER.test(str.slice(pos));
  }
  function maskedLeadNotSurname(m, sur, off, str, fallback) {
    if (sur.length !== 1) return false;
    if (/[*＊][\u4e00-\u9fff]/.test(m)) return false; // #206 星号后面还跟着一个字（「对*明」「王*明」「转到*明」「卡号是*华」）：一律当姓名（宁可多遮），先于号码语境
    if (starsNotName(str, off + Math.max(m.search(/[*＊]/), 0))) return true; // #206 第六条探针：号码语境 / 「我在***上班」不当姓名，先于 SHORT_STARS 兜底
    var star = m.search(/[*＊]/);
    var rest = String(str).slice(off + (star < 0 ? m.length : star));
    var st = stopSurname(sur, rest);
    if (st === null) return String(fallback || '').indexOf(sur) >= 0;
    if (st && NAME_STOPCHARS[sur] && SHORT_STARS.test(rest)) return false;
    return st;
  }
  var NAME_BOUNDARY = new RegExp(NR.boundary);
  // ASR 数字规整（ITN）会把“张三”转成“张3”：单个阿拉伯数字还原为汉字（等长，脱敏区间不变）
  var NAME_DIGITS = '零一二三四五六七八九';
  var SPLIT_SPELLINGS = {};
  ((NR.split && NR.split.spellings) || []).forEach(function (x) { SPLIT_SPELLINGS[x] = true; });
  function cleanName(n, m, start) {
    n = n.replace(/[0-9]/g, function (d) { return NAME_DIGITS.charAt(+d); });
    if (NOT_NAMES.test(n) || stopName(n, m, start)) return null;
    if (SPLIT_SPELLINGS[n]) return null; // #206「收款人是弓长张，伟大的伟」：拆字说法本身不是姓名（姓留给拆字报姓规则，只露姓）
    var cut = n.search(/[开卡银账的是事在和与就吧了啊呢哦，电手微那呃嗯合你我找他她这打转加对说哈]|然后/);
    if (cut >= 2) n = n.slice(0, cut);
    // “户名周杰农业银行”（户名后的逗号被去掉）：第 3、4 个字起是银行名 / 开户行时截断
    if (m && start != null) {
      for (var k = 2; k <= 3; k++) {
        if (k < n.length && NAME_BOUNDARY.test(m.input.slice(start + k))) { n = n.slice(0, k); break; }
      }
    }
    return n.length >= 2 ? n : null;
  }
  /** 句中姓名（“钱转到李强的账户”）：必须以常见姓氏开头、不以称呼结尾，其余同 cleanName */
  function cleanNameMid(n, m, start) {
    if (!n || NR.surnames.indexOf(n[0]) < 0) return null;
    for (var i = 0; i < NR.titleSuffix.length; i++) {
      var t = NR.titleSuffix[i];
      if (n.length >= t.length && n.slice(n.length - t.length) === t) return null;
    }
    return cleanName(n, m, start);
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
    // 完整的 ETH / TRON 地址先认领：地址里常含 vx / VX 等字母组合，不能先被当成微信号截走（#8）
    scan(RE.eth, 'crypto_eth', { meta: function () { return { chain: 'Ethereum/EVM' }; } });
    scan(RE.tron, 'crypto_tron', { meta: function () { return { chain: 'TRON' }; } });
    scan(RE.alipay, 'alipay', { group: 1 });
    scan(RE.qq, 'qq', { group: 1 });
    scan(RE.wechat, 'wechat', { group: 1 });
    scan(RE.email, 'email');
    scan(RE.urlBare, 'url', { clean: trimUrl, meta: function (raw) {
      // 排除像 "1.5com" 这类误报：至少含一个字母的主机标签
      return /[a-z]/i.test(raw.split('.')[0]) ? { bare: true } : false;
    } });
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
    scan(RE.landline, 'phone', { meta: function (raw, m, start) {
      // 不带横杠的座机（多由断续报号拼接而来）：前面紧挨订单号 / 工号 / 验证码等词时不算电话
      if (raw.indexOf('-') < 0 && RE_BLOCK_BEFORE && RE_BLOCK_BEFORE.test(unblockTypos(s.slice(Math.max(0, start - 16), start)))) return false;
      return { kind: 'landline' };
    } });
    scan(RE.mobile, 'phone', { meta: function () { return { kind: 'mobile' }; } });
    scan(RE.name, 'name', { group: 1, clean: cleanName });
    scan(RE.nameMid, 'name', { group: 1, clean: cleanNameMid });
    // #216 P0：人设回复「对方叫李四是吧」「他叫王志强」——人称 + 叫 后面的姓名（必须以常见姓氏开头，规则同 nameMid）
    scan(RE.namePerson, 'name', { group: 1, clean: cleanNameMid });

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
  var FRAG = '[0-9](?:' + SEP_CLS + '{0,' + C.obfuscation.digitJoin.maxSep + '}[0-9])*';
  var RE_TAIL = new RegExp('(' + FRAG + ')(' + (ST.tailFiller || '$').replace(/\$$/, '') + ')$');
  var RE_HEAD = new RegExp('(' + (ST.headFiller || '^').replace(/^\^/, '') + ')(' + FRAG + ')');
  var RE_TAIL_ONLY = new RegExp('^' + (ST.tailFiller || '$'));
  var RE_UNIT = new RegExp(C.obfuscation.digitJoin.unitAfter);
  var RE_BANK_CTX = new RegExp(ST.bankContext || '卡号');
  var RE_PHONE_CTX = new RegExp(ST.phoneContext || '电话');

  var RE_BLOCK_BEFORE = ST.blockBefore ? new RegExp(ST.blockBefore) : null;
  var RE_BLOCK_AFTER = ST.blockAfter ? new RegExp(ST.blockAfter) : null;
  var BLOCK_TYPOS = (ST.blockTypos || {}).map || {};
  var BT_KEYS = Object.keys(BLOCK_TYPOS).sort(function (a, b) { return b.length - a.length || (a < b ? -1 : a > b ? 1 : 0); });
  var RE_BLOCK_TYPOS = BT_KEYS.length ? new RegExp(BT_KEYS.map(function (k) { return k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|'), 'g') : null;
  /** 屏蔽词的手写错字（房问号 / 工好）换回正写再判断（等长替换） */
  function unblockTypos(t) { return RE_BLOCK_TYPOS ? t.replace(RE_BLOCK_TYPOS, function (k) { return BLOCK_TYPOS[k]; }) : t; }
  // #8：钱包地址跨回合拼接（上一回合末尾 0x… / T… + 下一回合开头的十六进制 / Base58 片段）
  var WST = ST.wallet || null;
  var B58C = '1-9A-HJ-NP-Za-km-z';
  // 片段内部也可以带停顿分段（“0x2bc，9fff9efd…”“然后…sNoN，aNDswW，L63c”），每处分隔至多 maxSep 个
  var WCHUNKS = '[0-9A-Za-z]+(?:' + SEP_CLS + '{1,' + C.obfuscation.digitJoin.maxSep + '}[0-9A-Za-z]+)*';
  var RE_WTAIL = WST ? new RegExp('(?<![0-9A-Za-z])((?:0x|T)' + WCHUNKS + ')(' + (ST.tailFiller || '$').replace(/\$$/, '') + ')$') : null;
  var RE_WHEAD = WST ? new RegExp('^(' + (ST.headFiller || '^').replace(/^\^/, '') + ')(' + WCHUNKS + ')(?![0-9A-Za-z])') : null;
  var RE_PAUSE_END = /^[\s，,、]*(?:…|⋯|\.{2,})/;
  var RE_W_CTX = WST && WST.context ? new RegExp(WST.context) : null;
  var WALLET_TYPES = ['crypto_eth', 'crypto_tron', 'crypto_btc'];
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
    /**
     * #1：片段被单回合提取认成 16–18 位、不过 Luhn 的银行卡（多半是拆开的长卡号的一段）：允许参与拼接，结果过 Luhn 时取代它。
     * #8：断续报卡号时，后半段（“1776…1855…023”“1567…5024…481”）可能整段或部分被认成手机号 / 座机，同样处理（拼接时还要求有卡号上下文）；
     * 回合以停顿（…）收尾的 16–18 位卡号即使过 Luhn 也允许接上下一回合开头的 1–3 位，拼成 19 位且过 Luhn 时取代（weakLuhn）。
     */
    function weakCard(a, b, pauseAfter) {
      var sp = norm.span(a, b);
      var hit = ents.filter(function (e) { return e.start < sp[1] && e.end > sp[0]; });
      if (hit.length !== 1 || (hit[0].type !== 'bank_card' && hit[0].type !== 'phone')) return null;
      var d = s.slice(a, b).replace(/[^0-9]/g, ''), v = String(hit[0].value).replace(/[^0-9]/g, '');
      if (hit[0].type === 'phone') {
        var joined = v === d && !/[-. ]/.test(String(hit[0].value));
        return (v.length < d.length && d.indexOf(v) >= 0) || joined ? hit[0] : null;
      }
      if (v !== d || d.length > 18 || (luhn(d) && !pauseAfter)) return null;
      if (luhn(d)) { var o = {}; for (var k in hit[0]) o[k] = hit[0][k]; o.weakLuhn = true; return o; }
      return hit[0];
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
      var a = t.index, b = a + t[1].length, wk = free(a, b) ? null : weakCard(a, b, RE_PAUSE_END.test(s.slice(b)));
      if ((wk || free(a, b)) && !(RE_BLOCK_BEFORE && RE_BLOCK_BEFORE.test(unblockTypos(s.slice(Math.max(0, a - 16), a))))) {
        out.tail = mk(a, b, { before: s.slice(Math.max(0, a - 16), a) });
        if (wk) out.tail.weak = wk;
      }
    }
    var h = RE_HEAD.exec(s);
    if (h && h.index === 0) {
      var a2 = h[1].length, b2 = a2 + h[2].length, rest = s.slice(b2), wk2 = free(a2, b2) ? null : weakCard(a2, b2);
      if ((wk2 || free(a2, b2)) && !RE_UNIT.test(rest) && !(RE_BLOCK_AFTER && RE_BLOCK_AFTER.test(unblockTypos(rest)))) {
        out.head = mk(a2, b2, { only: RE_TAIL_ONLY.test(rest) });
        if (wk2) out.head.weak = wk2;
      }
    }
    if (out.tail && RE_UNIT.test(s.slice(out.tail.ne))) out.tail = null;
    out.wtail = out.whead = null;
    if (RE_WTAIL) {
      /** 片段里的字母数字段（原文坐标），拼接时按需要的长度取前缀 / 全部 */
      var chunks = function (a, b) {
        var res = [], re = /[0-9A-Za-z]+/g, g, sub = s.slice(a, b);
        while ((g = re.exec(sub)) !== null) res.push({ sp: norm.span(a + g.index, a + g.index + g[0].length), text: g[0] });
        return res;
      };
      var w = RE_WTAIL.exec(s);
      if (w) {
        var wa = w.index, ctx = s.slice(Math.max(0, wa - (WST.contextChars || 24)), wa);
        if (!RE_W_CTX || RE_W_CTX.test(ctx)) out.wtail = chunks(wa, wa + w[1].length);
      }
      var wh = RE_WHEAD.exec(s);
      if (wh) out.whead = chunks(wh[1].length, wh[1].length + wh[2].length);
    }
    return out;
  }

  function score(d, ctx) {
    var kind = N.plausibleNumber(d);
    if (!kind) return null;
    if (kind === 'phone') return { type: 'phone', conf: round2(0.6 + (RE_PHONE_CTX.test(ctx) ? 0.3 : 0)), meta: { kind: 'mobile' } };
    if (kind === 'landline' || kind === 'hotline') return { type: 'phone', conf: round2(0.3 + (RE_PHONE_CTX.test(ctx) ? 0.3 : 0)), meta: { kind: kind } };
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
        // 含被单回合认成卡号的片段：拼接结果必须是过 Luhn 的银行卡才取代它
        // （#8：含手机号段时另需卡号上下文，含过 Luhn 的段时须拼成 19 位）
        var weak = parts.filter(function (p) { return p.f.weak; }).map(function (p) { return p.f.weak; });
        if (sc && weak.length && !(sc.type === 'bank_card' && sc.meta.luhn
          && (!weak.some(function (x) { return x.type === 'phone'; }) || RE_BANK_CTX.test(tail.before + F[i].text.slice(tail.ns, tail.ne)))
          && (!weak.some(function (x) { return x.weakLuhn; }) || d.length === 19))) sc = null;
        if (sc && sc.conf >= minConf && (!best || sc.conf > best.sc.conf || (sc.conf === best.sc.conf && d.length > best.d.length))) best = { sc: sc, d: d, parts: parts.slice() };
      }
      if (!best) continue;
      var key = best.sc.type + '|' + best.d;
      if (seen[key]) continue;
      seen[key] = 1;
      var masked = R.mask(best.sc.type, best.d), off = 0, same = masked.length === best.d.length;
      var meta = best.sc.meta; meta.stitched = true;
      var sup = best.parts.filter(function (p) { return p.f.weak; }).map(function (p) {
        return { turn: p.turn, type: p.f.weak.type, value: p.f.weak.value, start: p.f.weak.start, end: p.f.weak.end };
      });
      var o = {
        type: best.sc.type, label: LABELS[best.sc.type], value: best.d, masked: masked, sensitive: true, confidence: best.sc.conf,
        turns: best.parts.map(function (p) { return p.turn; }),
        parts: best.parts.map(function (p) {
          var n = p.f.digits.length, m = same ? masked.slice(off, off + n) : new Array(n + 1).join('*');
          off += n;
          return { turn: p.turn, start: p.f.start, end: p.f.end, masked: m };
        }),
        meta: meta
      };
      if (sup.length) o.supersedes = sup;
      out.push(o);
      i = best.parts[best.parts.length - 1].turn - 1; // 已用掉的回合不再作为起点
    }
    return out.concat(stitchWallets(F, seen));
  }

  /** 取片段的全部（take 省略）或前若干个字符段，凑满 take 个字符；返回 { text, start, end, hit } 或 null（与 Python _wallet_part 一致） */
  function walletPart(chunks, ents, take) {
    var used = [], n = 0;
    for (var k = 0; k < chunks.length; k++) {
      if (take != null && n >= take) break;
      used.push(chunks[k]);
      n += chunks[k].text.length;
    }
    if (!used.length || (take != null && n !== take)) return null;
    var sa = used[0].sp[0], sb = used[used.length - 1].sp[1];
    var hit = ents.filter(function (e) { return e.start < sb && e.end > sa; });
    if (hit.some(function (e) { return WALLET_TYPES.indexOf(e.type) >= 0 || e.start < sa || e.end > sb; })) return null;
    return { text: used.map(function (c) { return c.text; }).join(''), start: sa, end: sb, hit: hit };
  }

  /**
   * #8：钱包地址拆进相邻两个回合（每段内部也可带停顿）。上一回合末尾片段 + 下一回合开头片段合计正好 0x+40 / T+33、字符集吻合、
   * 上一回合片段前有钱包上下文词才输出；被单回合误认成微信号等的部分由拼接结果取代（supersedes）。与 Python _stitch_wallets 一致。
   */
  function stitchWallets(F, seen) {
    var out = [];
    for (var i = 0; i + 1 < F.length; i++) {
      var tc = F[i].wtail, hc = F[i + 1].whead;
      if (!tc || !hc) continue;
      var tp = walletPart(tc, F[i].ents);
      if (!tp || tp.text.length < (WST.minTail || 4)) continue;
      var eth = tp.text.slice(0, 2) === '0x', need = (eth ? 42 : 34) - tp.text.length;
      if (need < (WST.minHead || 3)) continue;
      var hp = walletPart(hc, F[i + 1].ents, need);
      if (!hp) continue;
      var v = tp.text + hp.text, type = eth ? 'crypto_eth' : 'crypto_tron';
      if (!(eth ? /^[0-9a-fA-F]+$/.test(v.slice(2)) : new RegExp('^[' + B58C + ']+$').test(v))) continue;
      var key = type + '|' + v.toLowerCase();
      if (seen[key]) continue;
      seen[key] = 1;
      var masked = R.mask(type, v), same = masked.length === v.length, n0 = tp.text.length;
      var o = {
        type: type, label: LABELS[type], value: v, masked: masked, sensitive: true, confidence: 0.9, turns: [i, i + 1],
        parts: [{ turn: i, start: tp.start, end: tp.end, masked: same ? masked.slice(0, n0) : new Array(n0 + 1).join('*') },
          { turn: i + 1, start: hp.start, end: hp.end, masked: same ? masked.slice(n0) : new Array(hp.text.length + 1).join('*') }],
        meta: { chain: eth ? 'Ethereum/EVM' : 'TRON', stitched: true }
      };
      var sup = [];
      [[i, tp], [i + 1, hp]].forEach(function (x) {
        x[1].hit.forEach(function (e) { sup.push({ turn: x[0], type: e.type, value: e.value, start: e.start, end: e.end }); });
      });
      if (sup.length) o.supersedes = sup;
      out.push(o);
    }
    return out;
  }

  /** 只取敏感情报（账户/地址/联系方式等） */
  function extractSensitive(text) {
    return extract(text).filter(function (e) { return e.sensitive; });
  }

  return { extract: extract, extractSensitive: extractSensitive, stopSurname: stopSurname, maskedLeadNotSurname: maskedLeadNotSurname, starsNotName: starsNotName, starsName: starsName, stitch: stitch, STITCH: ST, luhn: luhn, LABELS: LABELS, BANKS: BANKS, CHANNELS: CHANNELS, RE: RE, normalize: N.normalize };
});
