/*!
 * DeepSuck — engine.js
 * 规则/模板人设引擎（默认引擎，纯浏览器运行，无需 API Key）。
 * Session 负责：接收骗子消息 → 提取情报 → 识别话术 → 选择拖延意图 → 生成人设回复 → 汇总报告。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var deps = isNode ? {
    redact: require('./redact.js'), extractors: require('./extractors.js'), tactics: require('./tactics.js'),
    personas: require('./personas.js'), scenarios: require('./scenarios.js'), intel: require('./intel.js')
  } : root.DeepSuck;
  var mod = factory(deps);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.engine = mod; }
})(typeof self !== 'undefined' ? self : this, function (D) {
  'use strict';

  var REPORT_SCHEMA = 'deepsuck.intel-report/v0.1';
  var VERSION = '0.4.0';

  function goalOf(type) {
    if (type === 'bank_card') return 'bank';
    if (/^crypto_/.test(type)) return 'wallet';
    if (type === 'phone' || type === 'qq' || type === 'wechat' || type === 'alipay' || type === 'email') return 'phone';
    if (type === 'url') return 'url';
    if (type === 'name') return 'name';
    return null;
  }

  // #114：从骗子原话里认场景（core/scenarios.json 的 heardCues，与 Python engine.py、voice/persona.py 同一词表）。
  // 规则回复里的称呼 {call} 只按骗子已经说出口的场景取，不按后台选的场景取。
  var HEARD = (D.scenarios && D.scenarios.HEARD_CUES) || {};
  var SCENE_CUES = {};
  Object.keys(HEARD.scenes || {}).forEach(function (k) { SCENE_CUES[k] = new RegExp(HEARD.scenes[k]); });
  var SCENE_IMPLIES = HEARD.implies || {};
  function scenesIn(text) {
    var t = String(text || '');
    return Object.keys(SCENE_CUES).filter(function (k) { return SCENE_CUES[k].test(t); });
  }
  /** 骗子说过的话里认出的场景，按第一次出现的先后；认出前一个场景时，implies 里的也算说过 */
  function heardScenes(texts) {
    var out = [];
    (texts || []).forEach(function (t) {
      t = String(t || '');
      scenesIn(t).sort(function (a, b) { return t.search(SCENE_CUES[a]) - t.search(SCENE_CUES[b]); }).forEach(function (k) {
        [k].concat(SCENE_IMPLIES[k] || []).forEach(function (x) { if (out.indexOf(x) < 0) out.push(x); });
      });
    });
    return out;
  }

  function Session(opts) {
    opts = opts || {};
    this.scenario = D.scenarios.BY_ID[opts.scenario] || D.scenarios.SCENARIOS[0];
    this.persona = D.personas.BY_ID[D.personas.resolveId ? D.personas.resolveId(opts.persona) : opts.persona] || D.personas.PERSONAS[0];
    this.rng = opts.rng || Math.random;
    this.now = opts.now || function () { return Date.now(); };
    this.engineName = opts.engine || 'rule';
    this.startedAt = this.now();
    this.endedAt = null;
    this.messages = [];      // { role: 'scammer'|'bot', text(已脱敏), t, intent?, tactics?, intel? }
    this.intel = {};         // key -> { type,label,masked,meta,count,firstSeenTurn }
    this.context = {};       // 非敏感上下文：金额、APP名、银行、渠道
    this.tacticCounts = {};
    this.used = {};          // 模板去重
    this.estSeconds = 0;     // 估算骗子耗费的时间
    this.turn = 0;
    this.asked = {}; // 本场已经索要过的情报目标（bank / url / phone / wallet / name）
    // 最近几个骗子回合的原文（只在内存里，用于跨回合拼接；不进 report）
    Object.defineProperty(this, 'recentTurns', { value: [], writable: true, enumerable: false });
    Object.defineProperty(this, 'recentPicks', { value: [], writable: true, enumerable: false }); // 近 RECENT_N 次选中的台词（近期去重）
    Object.defineProperty(this, 'intentHist', { value: {}, writable: true, enumerable: false }); // 每个意图最近选中的台词（自适应去重窗口）
    Object.defineProperty(this, 'lastNew', { value: [], writable: true, enumerable: false }); // 本回合新情报（含内存原值），用于自然复述
  }

  /**
   * 选模板：同一意图内不重复（用完一轮再重置）。
   * 模板可以是字符串，或 { t: '文本', re: /触发词/ } —— 后者只在骗子本轮消息命中 re 时可用，且优先使用，
   * 这样"卡号填错被冻结？"之类的接话不会在对方还没提到时冒出来。
   */
  Session.prototype.pick = function (intent, ctx) {
    var list = this.templateList(intent);
    ctx = String(ctx || '');
    var used = this.used[intent] = this.used[intent] || [];
    var avoid = this.avoidRe;
    function ok(i) {
      var it = list[i];
      if (avoid && avoid.test(typeof it === 'string' ? it : it.t)) return false;
      return typeof it === 'string' || (it.re && it.re.test(ctx));
    }
    var avail = [], ctxHits = [];
    for (var i = 0; i < list.length; i++) {
      if (!ok(i)) continue;
      avail.push(i);
      if (used.indexOf(i) < 0 && typeof list[i] !== 'string') ctxHits.push(i);
    }
    if (!avail.length) { list = this.persona.templates.generic; return list[Math.floor(this.rng() * list.length)]; }
    var recent = this.recentPicks;
    var hist = this.intentHist[intent] = this.intentHist[intent] || [];
    var w = Math.floor(avail.length / 2);
    var recentI = w > 0 ? hist.slice(-w) : [];
    function text(i) { var it = list[i]; return typeof it === 'string' ? it : it.t; }
    function fresh(i) { return recent.indexOf(text(i)) < 0 && recentI.indexOf(text(i)) < 0; }
    var unused = avail.filter(function (i) { return used.indexOf(i) < 0; });
    var pool = ctxHits.filter(fresh);
    if (!pool.length) pool = unused.filter(fresh);
    if (!pool.length) pool = ctxHits.length ? ctxHits : unused;
    if (!pool.length) { used.length = 0; pool = avail.filter(fresh); if (!pool.length) pool = avail; }
    var idx = pool[Math.floor(this.rng() * pool.length)];
    used.push(idx);
    var it = list[idx];
    recent.push(text(idx));
    while (recent.length > RECENT_N) recent.shift();
    hist.push(text(idx));
    while (hist.length > list.length) hist.shift();
    return typeof it === 'string' ? it : it.t;
  };

  // 拖延类意图的"兄弟"顺序：某个意图的台词用完时换一种拖法，而不是立刻重复同一句（评测发现重复是骗子起疑挂断的主因）
  // secrecy（被要求保密）与 loan_stall（贷款 / 征信类拖延）也在链上：语料版骗子会反复要求保密、反复催贷款手续，台词用完要换一种拖法
  var STALL_FAMILY = ['urgency_stall', 'tech_trouble', 'slow_walk', 'ask_repeat', 'misunderstand', 'info_stall', 'generic', 'secrecy', 'loan_stall', 'task_stall', 'campus_stall'];
  // 近期去重：近 RECENT_N 次选中的台词不再选（除非别无可选），跨意图生效；
  // 另外同一意图最近 floor(可用台词数 / 2) 次选过的也不选（池子越大窗口越大，用完一轮重置后不会马上回到刚说过的）
  var RECENT_N = 8;
  // 纯拖延意图：同一场不连续两轮都用纯拖延，第二轮换成"小步配合"（coop_step）——看起来在配合、卡在某一步、问具体操作
  var ELICIT_GOAL = { elicit_account: 'bank', elicit_url: 'url', elicit_contact: 'phone', elicit_wallet: 'wallet' };
  var PURE_STALL = ['otp_stall', 'urgency_stall', 'tech_trouble', 'slow_walk', 'ask_repeat', 'misunderstand', 'info_stall', 'generic'];
  var DIGIT_TYPES = ['bank_card', 'phone', 'alipay', 'qq'];
  /** 把尾号报错一位（让对方纠正）：末两位不同则对调，否则末位 +1 */
  // 人设回复发出前的过滤（#121 数字、#130 打码片段与叠词；与 python/deepsuck/engine.py 的 vague_digits 逐字一致）
  /* ---------- 跨轮去重（#153，配置 personas.json 的 tailDedupe；与 Python deepsuck.engine.dedupe_tail 逐字一致）---------- */
  var TD = D.personas.TAIL_DEDUPE;
  var TD_IGNORE = new RegExp('[' + TD.ignore.replace(/[\\\]\[^-]/g, '\\$&') + ']+', 'g');
  var TD_SENT = /[^。？！?!；;\n]+[。？！?!；;]*|[。？！?!；;]+/g;
  function tdNorm(s) { return String(s || '').replace(TD_IGNORE, ''); }
  function tdSplit(text) {
    var out = [];
    (String(text || '').match(TD_SENT) || []).forEach(function (x) {
      if (out.length && !tdNorm(x)) out[out.length - 1] += x;
      else if (tdNorm(x) || !out.length) out.push(x);
    });
    return out;
  }
  function tdHash(t) {
    var h = 0x811c9dc5;
    for (var i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h >>> 0;
  }
  /** 一条回复的尾句（最后一个有字的句子，带句末标点）；没有字时返回空串 */
  function tailSentence(text) {
    var parts = tdSplit(text).filter(function (x) { return tdNorm(x); });
    return parts.length ? parts[parts.length - 1].trim() : '';
  }
  /** 删完为空时的兜底：该人设 templates[fallback] 里已有台词（纯文本、不带 {变量}；#188 只用 fallbackPick 标了的），按原句哈希定起点依次挑整句和尾句都没说过的第一句 */
  function tdFallback(text, personaId, seen) {
    var p = personaId ? D.personas.BY_ID[D.personas.resolveId(personaId)] : null;
    var lst = (p && p.templates && p.templates[TD.fallback]) || [];
    // #188：fallbackPick 里标了的（不带具体场景、不带变量、最多一位数字）才用；没标或标空时回退到原来的整池
    var pick = (((TD.fallbackPick || {})[p && p.id]) || []).filter(function (i) { return i >= 0 && i < lst.length; }).map(function (i) { return lst[i]; });
    var pool = (pick.length ? pick : lst).filter(function (x) { return typeof x === 'string' && x.indexOf('{') < 0; });
    if (!pool.length) return '';
    var start = tdHash(tdNorm(text)) % pool.length;
    for (var i = 0; i < pool.length; i++) {
      var c = pool[(start + i) % pool.length];
      if (!seen[tdNorm(c)] && !seen[tdNorm(tailSentence(c))]) return c;
    }
    return '';
  }
  /** 跨轮去重（纯函数）：recentTails 是最近几轮人设回复的尾句（调用方维护）；当前尾句去掉标点后与其中之一相同就删掉这句，
   *  删完为空时从 personaId 这个人设已有的台词里确定性地挑一句最近几轮没说过的，不加新说法 */
  function dedupeTail(text, recentTails, personaId) {
    var s = String(text || '');
    var seen = {};
    (recentTails || []).slice(-TD.window).forEach(function (x) { var n = tdNorm(x); if (n) seen[n] = 1; });
    if (!Object.keys(seen).length) return s;
    for (;;) {
      var parts = tdSplit(s).filter(function (x) { return tdNorm(x); });
      if (!parts.length) return tdNorm(text) ? tdFallback(text, personaId, seen) : s;
      if (!seen[tdNorm(parts[parts.length - 1])]) return s;
      s = parts.slice(0, -1).join('').replace(/\s+$/, '');
    }
  }

  /* ---------- #187：不说成已经转账或答应去转（配置 personas.json 的 transferClaim；与 Python deepsuck.engine.hold_transfer 逐字一致，
   * 用例 tests/fixtures/transfer_claim.json）---------- */
  var TC = D.personas.TRANSFER_CLAIM;
  var tcEsc = function (x) { return x.replace(/[\\\]\[^\-]/g, '\\$&'); };
  var TC_TRIGGER = new RegExp(TC.trigger);
  var TC_QUOTE = new RegExp(TC.quote, 'g');
  var TC_SEG = new RegExp('[^' + tcEsc(TC.split) + ']+|[' + tcEsc(TC.split) + ']+', 'g');
  var TC_DONE = new RegExp(TC.done, 'g'), TC_COMMIT = new RegExp(TC.commit, 'g'), TC_RECEIPT = new RegExp(TC.receipt, 'g');
  var TC_RECEIPT_OBJ = new RegExp(TC.receiptObj), TC_NEG_PRE = new RegExp(TC.negPre), TC_NEG_POST = new RegExp(TC.negPost), TC_NAV_PRE = new RegExp(TC.navPre);
  var TC_NOT_VERB = new RegExp(TC.notVerb), TC_REPORT = new RegExp(TC.report), TC_COND = new RegExp(TC.cond);
  var TC_COND_POST = new RegExp(TC.condPost), TC_ASK = new RegExp(TC.ask);
  var TC_HOLD = '\uE010'; // 引号里的话挪开时的占位
  function tcHit(seg, pat, condPost) {
    pat.lastIndex = 0;
    var m;
    while ((m = pat.exec(seg))) {
      if (!m[0]) { pat.lastIndex++; continue; }
      var pre = seg.slice(0, m.index), post = seg.slice(m.index + m[0].length);
      if (!(TC_NEG_PRE.test(pre) || TC_NAV_PRE.test(pre) || TC_REPORT.test(pre) || TC_COND.test(pre) ||
        TC_NEG_POST.test(post) || TC_NOT_VERB.test(post) || (condPost && TC_COND_POST.test(post)))) return true;
    }
    return false;
  }
  /** 一个分句（引号里的话已挪开）是不是说成已经转了 / 答应去转（见 personas.json transferClaim.comment） */
  function transferClaim(seg, receiptOk) {
    if (receiptOk === undefined) receiptOk = true;
    if (TC_ASK.test(seg)) return false;
    if (tcHit(seg, TC_DONE, true) || tcHit(seg, TC_COMMIT, false)) return true;
    return !!receiptOk && tcHit(seg, TC_RECEIPT, false);
  }
  /** #187 发送前过滤（只用于大模型回复）：说成已经转账、问对方收没收到、答应马上去转的分句，整句换成拖延说法
   *  （transferClaim.stall，按原句字符码之和轮换；相邻的合并成一处，问号改句号）。否定、引述对方的话、假设、问细节不动。 */
  function holdTransfer(text) {
    var src = String(text == null ? '' : text);
    if (!src || !TC_TRIGGER.test(src)) return src;
    var quoted = [];
    var s = src.replace(TC_QUOTE, function (m) { quoted.push(m); return TC_HOLD; });
    var receiptOk = !TC_RECEIPT_OBJ.test(s);
    var segs = s.match(TC_SEG) || [];
    var h = 0;
    for (var ch of src) h += ch.codePointAt(0);
    var stall = TC.stall[h % TC.stall.length];
    var out = [], lastHit = false, changed = false;
    segs.forEach(function (seg) {
      if (TC.split.indexOf(seg[0]) >= 0) {
        if (lastHit && /[？?]/.test(seg)) seg = seg.replace(/[？?]/g, '。');
        out.push(seg);
        return;
      }
      if (transferClaim(seg, receiptOk)) {
        changed = true;
        if (lastHit) { // 和上一处命中的连着：去掉中间的标点，合并成一处
          while (out.length && TC.split.indexOf(out[out.length - 1][0]) >= 0) out.pop();
          return;
        }
        out.push(stall);
        lastHit = true;
      } else {
        out.push(seg);
        lastHit = false;
      }
    });
    if (!changed) return src;
    var r = out.join('');
    return quoted.length ? r.replace(/\uE010/g, function () { return quoted.shift(); }) : r;
  }

  var DE = D.personas.DIGIT_ECHO;
  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  var DD = '[' + DE.digits + ']';
  var DJ = '[' + DE.joiners + ']{0,2}';
  var DM = '[' + DE.digits + reEsc(DE.masks) + ']'; // 数字或打码星号
  var DRUN = '(?=' + DM + '*' + DD + ')' + DM + '(?:' + DJ + DM + '){' + (DE.minRun - 1) + ',}';
  var DRUN_D = DD + '(?:' + DJ + DM + '){' + (DE.minRun - 1) + ',}'; // 以数字开头的串（留第一位用）
  var TAILW = '(?:' + DE.tailWords.map(reEsc).join('|') + ')';
  var MONEYW = '(?:' + DE.moneyUnits.map(reEsc).join('|') + ')';
  var STAR = reEsc(DE.masks);
  function alt(xs) { return '(?:' + xs.slice().sort(function (a, b) { return b.length - a.length; }).map(reEsc).join('|') + ')'; }
  var HEDGE = alt(DE.hedges); // #167：数字串前的“好像是”“是”连同数字串一起换，不叠成“好像是好像是6开头的”
  var DIGIT_LEAD = new RegExp(HEDGE + '?(' + DRUN_D + ')' + DJ + '开头(?:的)?', 'g');
  var DIGIT_LEAD_AFTER = new RegExp('(' + alt(DE.leadWords) + ')(?:' + HEDGE + '|为)?' + DJ + '(' + DRUN_D + ')', 'g');
  var DIGIT_MONEY = new RegExp(DRUN + DJ + MONEYW, 'g');
  var DIGIT_PCT = new RegExp(DRUN + DJ + alt(DE.percentUnits), 'g'); // #167：60% → 一半
  var DIGIT_COUNT = new RegExp(DRUN + '(?=' + DJ + alt(DE.countUnits) + ')', 'g'); // #167：等我10分钟 → 等我几分钟
  // #167：不是号码的写法（TRC20）和汉字约数（两三天、一二十分钟）先挪开，过滤完原样放回
  var KEEP = new RegExp(alt(DE.keep) + '|(?<![' + DE.digits + '])' + alt(DE.approx.pairs) + '(?=[' + DE.approx.units + '])', 'g');
  var DIGIT_TAIL = new RegExp(TAILW + '(?:是|为)?' + DJ + DRUN, 'g');
  var DIGIT_RUN = new RegExp(DRUN, 'g');
  // 打码姓名（#130，与 voice/persona.py 的 _unmask_names 同一规则）：张**、王*明、欧阳**，前面的“姓”一并换掉
  // #157：拆字报姓的说法（耳东陈***）跟着打码姓名一起换掉；拆字说法读 extractors.json 的 nameRules.split（只读）
  var SPL = D.personas.SPLIT_NAME;
  var SPLIT_PRE = '(?:(?:' + SPL.spellings.slice().sort(function (a, b) { return b.length - a.length; })
    .map(function (x) { return reEsc(x.slice(0, -1)); }).join('|') + ')' + SPL.link + ')';
  var SPLIT_BEFORE_NAME = new RegExp(SPLIT_PRE + '(?=' + reEsc(DE.name) + ')', 'g');
  var NAME_MASK = new RegExp(SPLIT_PRE + '?(姓)?(' + DE.compoundSurnames.join('|') + '|[\u4e00-\u9fff])' +
    '(?:[' + STAR + '](?:(?![' + DE.nameTailStop + '])[\u4e00-\u9fff](?![' + STAR + ']))?(?![0-9A-Za-z' + STAR + '])|[' + STAR + ']{2,4}(?![0-9A-Za-z' + STAR + ']))', 'g');
  var OTHER_MASK = new RegExp('[A-Za-z0-9_.:/@\\-]*[' + STAR + ']+[A-Za-z0-9_.:/@\\-' + STAR + ']*', 'g');
  var LITERAL = DE.tail.map(function (p) { return [p, 'T']; }).concat(DE.other.map(function (p) { return [p, 'O']; }))
    .sort(function (x, y) { return y[0].length - x[0].length; });
  var HEARD = new RegExp(DE.heardAlready.map(reEsc).join('|'));
  var TOK = /\uE000([A-Za-z]+)([^\uE001]*)\uE001/;
  var SEPCH = ' \u3000…,，、.．·~～-—';
  var CLAUSE_END = '？?！!。；;，,…\n';
  var SEPCLS = SEPCH.replace(/[\]\\^-]/g, '\\$&'); // 字符类里用：- 要转义
  var MERGE_OT = new RegExp('\uE000[OT]\uE001(?:[' + SEPCLS + ']*\uE000[OT]\uE001)+', 'g');
  var MERGE_N = new RegExp('(\uE000(?:N|H)\uE001)(?:[' + SEPCLS + ']*\uE000(?:N|H)\uE001)+', 'g');
  var TRAIL = new RegExp('[' + (SEPCH + CLAUSE_END).replace(/[\]\\^-]/g, '\\$&') + ']+$');
  function tok(kind, arg) { return '\uE000' + kind + (arg || '') + '\uE001'; }
  /** 人设回复发出前的过滤：数字串 → 含糊说法（只留单个数字），打码片段 → “那个名字”“那个号”，叠在一起的“没听清”合并成一处。
   *  说法按原句字符码之和轮换。放在错别字扰动之后、语音合成之前。 */
  function vagueDigits(text) {
    if (!text) return text;
    var src = String(text);
    var h = 0;
    for (var ch of src) h += ch.codePointAt(0);
    var kept = [];
    var s = src.replace(KEEP, function (m) { kept.push(m); return '\uE002'; });
    var putBack = function (t) { return kept.length ? t.replace(/\uE002/g, function () { return kept.shift(); }) : t; };
    LITERAL.forEach(function (x) { s = s.split(x[0]).join(tok(x[1])); });
    s = s.replace(DIGIT_LEAD, function (m, run) { return tok('L', run.charAt(0)); })
      .replace(DIGIT_LEAD_AFTER, function (m, w, run) { return w + tok('A', run.charAt(0)); })
      .replace(DIGIT_TAIL, tok('T'))
      .replace(DIGIT_MONEY, tok('M'))
      .replace(DIGIT_PCT, DE.percent)
      .replace(DIGIT_COUNT, DE.count)
      .replace(DIGIT_RUN, tok('O'))
      .replace(SPLIT_BEFORE_NAME, '') // #157：上游已换成“那个名字”时去掉残留的拆字说法
      .replace(NAME_MASK, function (m, xing, sur) { return sur.length === 1 && DE.notSurname.indexOf(sur) >= 0 ? m : tok('N'); })
      .replace(OTHER_MASK, function (m) { return tok(m.indexOf('@') >= 0 ? 'E' : /[A-Za-z]{2,}\.|\.[A-Za-z]{2,}/.test(m) ? 'U' : 'H'); });
    if (s.indexOf('\uE000') < 0) return putBack(s);
    s = s.replace(MERGE_OT, function (m) { return tok(m.indexOf('\uE000T') >= 0 ? 'T' : 'O'); })
      .replace(MERGE_N, function (m, first) { return first; });
    var parts = s.split(TOK); // [文字, 类型, 参数, 文字, ...]
    var plain = parts.filter(function (_, i) { return i % 3 === 0; }).join('');
    var fullUsed = HEARD.test(plain);
    var out = [parts[0]];
    var n = 0;
    for (var i = 1; i < parts.length; i += 3) {
      var kind = parts[i], arg = parts[i + 1], after = parts[i + 2];
      var k = n++;
      var pick = function (lst) { return lst[(h + k) % lst.length]; };
      var prev = out[out.length - 1];
      if (kind === 'O' || kind === 'T') {
        if (!fullUsed) { out.push(pick(kind === 'T' ? DE.tail : DE.other)); fullUsed = true; }
        else if ((!after || CLAUSE_END.indexOf(after.charAt(0)) >= 0) && (!prev || (SEPCH + CLAUSE_END).indexOf(prev.charAt(prev.length - 1)) >= 0)) {
          out[out.length - 1] = prev.replace(TRAIL, ''); // 自成一个分句的多余一处：连前面的标点一起去掉
        } else out.push(pick(DE.short));
      } else if (kind === 'L') out.push(pick(DE.lead).split('{d}').join(arg) + '的');
      else if (kind === 'A') out.push(pick(DE.leadAfter).split('{d}').join(arg));
      else if (kind === 'M') out.push(pick(DE.money));
      else if (kind === 'N') out.push(DE.name);
      else out.push(kind === 'E' ? DE.maskEmail : kind === 'U' ? DE.maskUrl : DE.mask);
      out.push(after);
    }
    return putBack(out.join(''));
  }

  function wrongDigit(t) {
    var n = t.length;
    if (n >= 2 && t[n - 1] !== t[n - 2]) return t.slice(0, n - 2) + t[n - 1] + t[n - 2];
    return t.slice(0, n - 1) + String((Number(t[n - 1]) + 1) % 10);
  }

  /** 该意图的无条件台词是否都已用过（本轮） */
  Session.prototype.exhausted = function (intent) {
    var list = this.persona.templates[intent];
    if (!list) return true;
    var used = this.used[intent] || [];
    for (var i = 0; i < list.length; i++) if (typeof list[i] === 'string' && used.indexOf(i) < 0) return false;
    return true;
  };

  /** 拖延意图台词用完时，轮换到仍有新台词的兄弟意图 */
  Session.prototype.freshIntent = function (intent) {
    if (STALL_FAMILY.indexOf(intent) < 0 || !this.exhausted(intent)) return intent;
    var start = STALL_FAMILY.indexOf(intent);
    for (var k = 1; k < STALL_FAMILY.length; k++) {
      var alt = STALL_FAMILY[(start + k) % STALL_FAMILY.length];
      if (!this.exhausted(alt)) return alt;
    }
    return intent;
  };

  Session.prototype.templateList = function (intent) {
    return this.persona.templates[intent] || this.persona.templates.generic;
  };

  Session.prototype.heardScenes = function () {
    return heardScenes(this.messages.filter(function (m) { return m.role === 'scammer'; }).map(function (m) { return m.text; }));
  };

  /** 称呼：按骗子已经说出口的场景取（第一个有称呼的）；称呼本身会带出骗子没说的场景（例如“客服”“警官”）就不用 */
  Session.prototype.salutation = function () {
    var heard = this.heardScenes(), call = this.persona.call || {};
    for (var i = 0; i < heard.length; i++) {
      var c = call[heard[i]] || '';
      if (c && scenesIn(c).every(function (y) { return heard.indexOf(y) >= 0; })) return c;
    }
    return '';
  };

  Session.prototype.fill = function (tpl, vars) {
    var call = this.salutation();
    vars = vars || {};
    return tpl.replace(/\{(\w+)\}/g, function (_, k) {
      if (k === 'call') return call;
      return vars[k] != null ? vars[k] : '';
    }).replace(/\s+$/, '');
  };

  Session.prototype.haveGoal = function (goal) {
    var self = this;
    return Object.keys(this.intel).some(function (k) { return goalOf(self.intel[k].type) === goal; });
  };

  Session.prototype.missingGoals = function () {
    var self = this;
    return this.scenario.goals.filter(function (g) { return !self.haveGoal(g); });
  };

  /** 开场白 */
  Session.prototype.opening = function () {
    var list = this.persona.openings[this.scenario.id] || this.persona.templates.generic;
    var text = this.fill(list[Math.floor(this.rng() * list.length)]);
    return this.recordBot(text, 'opening');
  };

  /** 处理骗子消息：提取 + 分类，返回分析结果（不含原文） */
  Session.prototype.ingest = function (rawText) {
    var self = this;
    this.turn++;
    var entities = D.extractors.extract(rawText);
    var tactics = D.tactics.classify(rawText);
    var redacted = D.redact.redactText(rawText, entities);
    var newIntel = [];
    this.lastNew = newIntel;

    entities.forEach(function (e) {
      if (e.sensitive) {
        var key = e.type + '|' + String(e.value).replace(/[\s-]/g, '').toLowerCase();
        if (!self.intel[key]) {
          self.intel[key] = { type: e.type, label: e.label, masked: e.masked, meta: e.meta, count: 0, firstSeenTurn: self.turn };
          // 原始值只保存在内存里（不进 report），仅用于按发布策略生成"情报库提交"内容
          Object.defineProperty(self.intel[key], 'raw', { value: e.value, enumerable: false });
          newIntel.push(self.intel[key]);
        }
        self.intel[key].count++;
      } else {
        var bucket = self.context[e.type] = self.context[e.type] || {};
        bucket[e.value] = (bucket[e.value] || 0) + 1;
      }
    });
    tactics.forEach(function (t) { self.tacticCounts[t.id] = (self.tacticCounts[t.id] || 0) + 1; });

    // 跨回合拼接：语音回合被切断时，卡号 / 手机号会分在相邻两三句里
    var msgIndex = this.messages.length;
    var recent = this.recentTurns;
    recent.push({ raw: String(rawText == null ? '' : rawText), entities: entities, extra: [], msg: msgIndex });
    var W = (D.extractors.STITCH && D.extractors.STITCH.window) || 3;
    while (recent.length > W) recent.shift();
    var stitchedNow = [];
    if (recent.length > 1 && D.extractors.stitch) {
      D.extractors.stitch(recent.map(function (r) { return r.raw; })).forEach(function (e) {
        if (e.turns[e.turns.length - 1] !== recent.length - 1) return; // 只处理以本回合结尾的拼接
        var key = e.type + '|' + e.value;
        // #1：拼接结果取代被单回合误认成整卡的那一段（从情报与该回合的脱敏实体里去掉，避免重叠打码）
        (e.supersedes || []).forEach(function (sup) {
          var sk = sup.type + '|' + String(sup.value).replace(/[\s-]/g, '').toLowerCase();
          var old = self.intel[sk];
          if (old) {
            delete self.intel[sk];
            var ix = newIntel.indexOf(old);
            if (ix >= 0) newIntel.splice(ix, 1);
          }
          var ents = recent[sup.turn].entities;
          for (var q = ents.length - 1; q >= 0; q--) if (ents[q].type === sup.type && ents[q].start === sup.start && ents[q].end === sup.end) ents.splice(q, 1);
        });
        e.parts.forEach(function (p) { recent[p.turn].extra.push({ type: e.type, start: p.start, end: p.end, masked: p.masked, sensitive: true }); });
        e.parts.forEach(function (p) {
          var r = recent[p.turn];
          if (p.turn < recent.length - 1 && self.messages[r.msg]) self.messages[r.msg].text = D.redact.redactText(r.raw, r.entities.concat(r.extra));
        });
        stitchedNow.push(e);
        // #8：断续报卡号拆成三个回合时，前两回合先拼出一段 16–18 位（62 开头）的“卡号”，第三回合拼出完整卡号后撤掉那段前缀
        if (e.type === 'bank_card') {
          Object.keys(self.intel).forEach(function (pk) {
            var it = self.intel[pk], pv = String(it.raw == null ? '' : it.raw);
            if (pk !== key && it.type === 'bank_card' && it.meta && it.meta.stitched && pv.length < e.value.length && e.value.indexOf(pv) === 0) {
              delete self.intel[pk];
              var ix = newIntel.indexOf(it);
              if (ix >= 0) newIntel.splice(ix, 1);
            }
          });
        }
        if (!self.intel[key]) {
          self.intel[key] = { type: e.type, label: e.label, masked: e.masked, meta: e.meta, count: 0, firstSeenTurn: self.turn };
          Object.defineProperty(self.intel[key], 'raw', { value: e.value, enumerable: false });
          newIntel.push(self.intel[key]);
        }
        self.intel[key].count++;
      });
    }
    if (stitchedNow.length) redacted = D.redact.redactText(rawText, entities.concat(recent[recent.length - 1].extra));

    this.estSeconds += 10 + Math.round(String(rawText).length * 0.6);
    var analysis = {
      turn: this.turn,
      redacted: redacted,
      tactics: tactics,
      newIntel: newIntel.map(function (i) { return { type: i.type, label: i.label, masked: i.masked }; }),
      entities: entities.concat(stitchedNow).map(function (e) { return { type: e.type, label: e.label, masked: e.masked, sensitive: e.sensitive }; })
    };
    this.messages.push({ role: 'scammer', text: redacted, t: this.now(), tactics: tactics.map(function (t) { return t.id; }), intel: analysis.newIntel });
    // #92：验证码被 ASR 切成几段（「验证码是 38」「27 15」）时，和前几段对方的话连起来再判断一次，
    // 本段与前几段（已脱敏文本）里命中的数字一起补打码
    if (D.redact.redactOtpSegments) {
      var idx = [];
      this.messages.forEach(function (m, i) { if (m.role === 'scammer') idx.push(i); });
      idx = idx.slice(-(D.redact.otpSegWindow() + 1));
      if (idx.length > 1) {
        var fixed = D.redact.redactOtpSegments(idx.map(function (i) { return self.messages[i].text; }));
        idx.forEach(function (i, k) { self.messages[i].text = fixed[k]; });
        analysis.redacted = fixed[fixed.length - 1];
      }
    }
    // #120：两边说话人连起来再看一次（人设问验证码、对方下一句报数字；卡号前缀和尾号分在两句），只回写对方的话
    if (D.redact.redactDialogSegments) {
      var lo = Math.max(0, this.messages.length - (2 * D.redact.otpSegWindow() + 1));
      var win = this.messages.slice(lo);
      var both = D.redact.redactDialogSegments(win.map(function (m) { return m.text; }), win.map(function (m) { return m.role; }));
      win.forEach(function (m, k) { if (m.role === 'scammer') m.text = both[k]; });
      analysis.redacted = both[both.length - 1];
    }
    return analysis;
  };

  /** 选择拖延意图（可解释的优先级规则） */
  Session.prototype.chooseIntent = function (a) {
    var has = {};
    a.tactics.forEach(function (t) { has[t.id] = true; });
    var r = this.rng();
    if (a.newIntel.length) return 'confirm_intel';
    if (has.otp) return 'otp_stall';
    if (has.acquaintance && !has.transfer && (this.used.verify_count || 0) < 2) {
      this.used.verify_count = (this.used.verify_count || 0) + 1;
      return 'verify_identity';
    }
    if (has.safe_account || has.transfer) {
      if (has.crypto && !this.haveGoal('wallet')) return 'elicit_wallet';
      if (!this.haveGoal('bank') && !this.haveGoal('wallet')) return 'elicit_account';
      return 'fake_progress';
    }
    if (has.crypto && !this.haveGoal('wallet')) return 'elicit_wallet';
    if (has.app_download) return this.haveGoal('url') ? 'tech_trouble' : 'elicit_url';
    var flavor = has.task_rebate ? 'task_stall' : has.loan_fraud ? 'loan_stall' : has.campus_loan ? 'campus_stall' : null;
    if (flavor && this.lastIntent !== flavor) return flavor;
    if ((has.authority || has.threat) && !this.used.scared_once) { this.used.scared_once = true; return 'scared'; }
    if (has.secrecy) return 'secrecy';
    if (has.high_return) return this.haveGoal('url') ? 'greedy' : 'elicit_url';
    if (has.info_harvest) return 'info_stall';
    if (has.off_platform && !this.haveGoal('phone')) return 'elicit_contact';
    if (has.romance) return 'romance';
    if (has.urgency) return 'urgency_stall';
    if (has.threat || has.authority) return r < 0.5 ? 'ask_repeat' : 'misunderstand';
    // 无明显话术：交替拖延与诱导
    var missing = this.missingGoals();
    if (missing.length && this.turn % 3 === 0) {
      return { bank: 'elicit_account', wallet: 'elicit_wallet', phone: 'elicit_contact', url: 'elicit_url', name: 'elicit_account' }[missing[0]];
    }
    var stalls = ['ask_repeat', 'misunderstand', 'tech_trouble', 'slow_walk', 'generic'];
    return stalls[Math.floor(r * stalls.length)];
  };

  /**
   * 对骗子复述情报的说法：不念打码星号，只说姓氏 /“你说的那张卡”/“你发的那个网址”。
   * #121 起号码类一个数字都不复述（尾号、开头几位都不说）；说出来的最多是姓氏，对外的 transcript 不需要再打码。
   */
  Session.prototype.speakIntel = function (item) {
    var SP = D.personas.SPEAK_INTEL;
    var typ = item.type;
    var forms = SP[/^crypto_/.test(typ) ? 'crypto' : typ] || SP['default'];
    var f = forms[Math.floor(this.rng() * forms.length)];
    var masked = String(item.masked);
    var raw = item.raw == null ? '' : String(item.raw);
    var d = DIGIT_TYPES.indexOf(typ) >= 0 ? raw.replace(/[^0-9]/g, '') : raw;
    var t = '';
    [4, 2].some(function (k) { if (d.length > k && masked.slice(-k) === d.slice(-k) && masked.length >= k) { t = d.slice(-k); return true; } return false; });
    if (/[0-9]/.test(t)) t = ''; // #121：号码一个数字都不复述（尾号也不说），带 {t}/{x} 的说法退回“你说的那个…”
    var s = typ === 'name' && raw.slice(0, 1) && masked.indexOf(raw.slice(0, 1)) === 0 ? raw.slice(0, 1) : '';
    var isNum = /^[0-9]+$/.test(t);
    if (((f.indexOf('{t}') >= 0 || f.indexOf('{x}') >= 0) && !t) || (f.indexOf('{x}') >= 0 && !isNum) || (f.indexOf('{s}') >= 0 && !s)) f = SP['default'][0];
    return f.split('{t}').join(t).split('{x}').join(isNum ? wrongDigit(t) : t).split('{s}').join(s).split('{label}').join(item.label);
  };

  /** 规则引擎回复 */
  Session.prototype.ruleReply = function (analysis) {
    var self = this;
    var prevIntent = this.lastIntent;
    var intent = this.freshIntent(this.chooseIntent(analysis));
    if (PURE_STALL.indexOf(intent) >= 0 && PURE_STALL.indexOf(this.lastIntent) >= 0 && this.persona.templates.coop_step) intent = 'coop_step';
    // 同一场已经要过的情报不再直接索要，改成"我在找"（re_ask）
    var goal = ELICIT_GOAL[intent];
    if (goal) {
      if (this.asked[goal] && this.persona.templates.re_ask) intent = 're_ask';
      this.asked[goal] = true;
    }
    this.lastIntent = intent;
    var vars = {};
    if (intent === 'confirm_intel') {
      vars.intel = this.lastNew.map(function (i) { return self.speakIntel(i); }).join('，');
      var missing = this.missingGoals();
      var g0 = missing[0];
      // confirmAskSkip：复述完情报不紧接着要这些（如复述后马上要电话，会被骗子当成反套话），留给之后的 elicit_*
      var skip = (this.persona.confirmAskSkip || []).indexOf(g0) >= 0;
      vars.ask = (g0 && !skip && !this.asked[g0] && this.persona.asks[g0]) || this.persona.asks.none;
      if (g0 && !skip) this.asked[g0] = true;
    }
    // afterReAskAvoid：刚说完"我在找"（re_ask）的下一轮不接这些说法（如小林"切出去了"，连着说像找借口拖）
    var av = this.persona.afterReAskAvoid;
    this.avoidRe = av && prevIntent === 're_ask' ? new RegExp(av) : null;
    var text = this.fill(this.pick(intent, analysis.redacted), vars);
    this.avoidRe = null;
    return this.recordBot(text, intent);
  };

  /** 记录机器人回复（规则或 LLM 生成），返回消息对象 */
  Session.prototype.recordBot = function (text, intent) {
    text = vagueDigits(text); // #121、#167：规则和大模型的回复都不带连续 2 位及以上的数字
    var safe = D.redact.redactText(text, D.extractors.extractSensitive(text)); // 机器人输出同样脱敏
    var stall = D.personas.STALL_SECONDS[intent] || 30;
    this.estSeconds += stall + Math.round(safe.length * 0.12);
    var msg = { role: 'bot', text: safe, t: this.now(), intent: intent };
    this.messages.push(msg);
    return msg;
  };

  /** 打字延迟（毫秒），模拟人设打字速度 */
  Session.prototype.typingDelay = function (text) {
    return Math.min(6500, 700 + String(text).length * this.persona.msPerChar * (0.6 + this.rng() * 0.5));
  };

  Session.prototype.end = function () { if (!this.endedAt) this.endedAt = this.now(); };

  Session.prototype.stats = function () {
    var end = this.endedAt || this.now();
    return {
      messages: this.messages.length,
      scammerMessages: this.messages.filter(function (m) { return m.role === 'scammer'; }).length,
      botMessages: this.messages.filter(function (m) { return m.role === 'bot'; }).length,
      wallClockSeconds: Math.round((end - this.startedAt) / 1000),
      estimatedScammerSeconds: this.estSeconds,
      intelCount: Object.keys(this.intel).length,
      riskScore: D.tactics.riskScore(this.tacticCounts),
      tacticKinds: Object.keys(this.tacticCounts).length
    };
  };

  Session.prototype.intelList = function () {
    var self = this;
    return Object.keys(this.intel).map(function (k) {
      var i = self.intel[k];
      var o = { type: i.type, label: i.label, masked: i.masked, meta: i.meta, count: i.count, firstSeenTurn: i.firstSeenTurn };
      if (i.blocklist) o.blocklist = i.blocklist;
      return o;
    });
  };

  /** 待比对黑名单的情报（含内存中的原值，仅供 blocklist.js 本地/分片比对，不进入报告） */
  Session.prototype.pendingBlocklist = function () {
    var self = this;
    return Object.keys(this.intel).filter(function (k) {
      var i = self.intel[k];
      return !i.blocklist && (i.type === 'url' || i.type === 'email' || /^crypto_/.test(i.type));
    }).map(function (k) { return { key: k, type: self.intel[k].type, raw: self.intel[k].raw }; });
  };

  /** 记录黑名单比对结果（只保存状态与来源名，不含原值） */
  Session.prototype.annotate = function (key, r) {
    if (!this.intel[key]) return;
    var o = { status: r.status };
    if (r.how) o.how = r.how;
    if (r.sources) o.sources = r.sources;
    if (r.updated) o.updated = r.updated;
    this.intel[key].blocklist = o;
  };

  Session.prototype.tacticList = function () {
    var self = this;
    return Object.keys(this.tacticCounts).map(function (id) {
      var t = D.tactics.BY_ID[id];
      return { id: id, label: t ? t.label : id, count: self.tacticCounts[id] };
    }).sort(function (a, b) { return b.count - a.count; });
  };

  /** 生成脱敏情报报告（可直接 JSON 导出） */
  Session.prototype.report = function () {
    var st = this.stats();
    return {
      schema: REPORT_SCHEMA,
      generator: 'DeepSuck ' + VERSION,
      generatedAt: new Date(this.now()).toISOString(),
      disclaimer: '本报告由沙盒演示生成，所有敏感信息均已脱敏，仅用于防诈研究与教育，不得用于骚扰、报复或任何违法用途。',
      session: {
        scenario: { id: this.scenario.id, title: this.scenario.title },
        persona: { id: this.persona.id, name: this.persona.name },
        engine: this.engineName,
        startedAt: new Date(this.startedAt).toISOString(),
        endedAt: this.endedAt ? new Date(this.endedAt).toISOString() : null
      },
      stats: st,
      intel: this.intelList(),
      context: this.context,
      tactics: this.tacticList(),
      transcript: this.messages.map(function (m) {
        return { role: m.role, text: m.text, at: new Date(m.t).toISOString(), intent: m.intent, tactics: m.tactics };
      })
    };
  };

  /**
   * 生成"提交到公开情报库"的内容：按 intel.js 的发布策略——电话/钱包/网址/APP 完整，银行卡/姓名/个人账号打码。
   * 注意：与 report() 不同，这里会包含完整电话、钱包地址与网址（这正是公开情报库要收录的内容）。
   */
  Session.prototype.submission = function () {
    var self = this;
    if (!D.intel) throw new Error('intel.js 未加载');
    return D.intel.buildSubmission({
      scenario: this.scenario.id,
      tactics: this.tacticList().map(function (t) { return t.id; }),
      rawIntel: Object.keys(this.intel).map(function (k) { var i = self.intel[k]; return { type: i.type, raw: i.raw, masked: i.masked, meta: i.meta, count: i.count }; }),
      apps: Object.keys(this.context.app_name || {})
    });
  };

  return { Session: Session, goalOf: goalOf, scenesIn: scenesIn, heardScenes: heardScenes, REPORT_SCHEMA: REPORT_SCHEMA, VERSION: VERSION, vagueDigits: vagueDigits, dedupeTail: dedupeTail, tailSentence: tailSentence, holdTransfer: holdTransfer, transferClaim: transferClaim };
});
