/*!
 * DeepSuck — engine.js
 * 规则/模板人设引擎（默认引擎，纯浏览器运行，无需 API Key）。
 * Session 负责：接收骗子消息 → 提取情报 → 识别话术 → 选择拖延意图 → 生成人设回复 → 汇总报告。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
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
  var VERSION = '0.2.0';

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
    this.persona = D.personas.BY_ID[opts.persona] || D.personas.PERSONAS[0];
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
    function ok(i) { var it = list[i]; return typeof it === 'string' || (it.re && it.re.test(ctx)); }
    var avail = [], ctxHits = [];
    for (var i = 0; i < list.length; i++) {
      if (!ok(i)) continue;
      avail.push(i);
      if (used.indexOf(i) < 0 && typeof list[i] !== 'string') ctxHits.push(i);
    }
    if (!avail.length) { list = this.persona.templates.generic; return list[Math.floor(this.rng() * list.length)]; }
    var pool = ctxHits.length ? ctxHits : avail.filter(function (i) { return used.indexOf(i) < 0; });
    if (!pool.length) { used.length = 0; pool = avail; }
    var idx = pool[Math.floor(this.rng() * pool.length)];
    used.push(idx);
    var it = list[idx];
    return typeof it === 'string' ? it : it.t;
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

    this.estSeconds += 10 + Math.round(String(rawText).length * 0.6);
    var analysis = {
      turn: this.turn,
      redacted: redacted,
      tactics: tactics,
      newIntel: newIntel.map(function (i) { return { type: i.type, label: i.label, masked: i.masked }; }),
      entities: entities.map(function (e) { return { type: e.type, label: e.label, masked: e.masked, sensitive: e.sensitive }; })
    };
    this.messages.push({ role: 'scammer', text: redacted, t: this.now(), tactics: tactics.map(function (t) { return t.id; }), intel: analysis.newIntel });
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

  /** 规则引擎回复 */
  Session.prototype.ruleReply = function (analysis) {
    var intent = this.chooseIntent(analysis);
    this.lastIntent = intent;
    var vars = {};
    if (intent === 'confirm_intel') {
      vars.intel = analysis.newIntel.map(function (i) { return i.label + ' ' + i.masked; }).join('，');
      var missing = this.missingGoals();
      vars.ask = this.persona.asks[missing[0]] || this.persona.asks.none;
    }
    var text = this.fill(this.pick(intent, analysis.redacted), vars);
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
      return { type: i.type, label: i.label, masked: i.masked, meta: i.meta, count: i.count, firstSeenTurn: i.firstSeenTurn };
    });
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
      generator: 'DeepSuck ' + VERSION + ' (非官方项目，与 DeepSeek 无关)',
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
