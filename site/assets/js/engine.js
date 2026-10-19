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

  Session.prototype.fill = function (tpl, vars) {
    var call = this.persona.call[this.scenario.id] || '';
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
   * 对骗子复述情报的说法：不念打码星号，只说尾号 / 姓氏 /“你发的那个网址”，或把尾号报错一位让对方纠正。
   * 说出来的只是打码值里本来就公开的部分（尾号、姓氏），所以对外的 transcript 不需要再打码。
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
      // confirmAskSkip：复述完情报不紧接着要这些（如李大爷复述后马上要电话，会被当成反套话），留给之后的 elicit_*
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

  return { Session: Session, goalOf: goalOf, REPORT_SCHEMA: REPORT_SCHEMA, VERSION: VERSION };
});
