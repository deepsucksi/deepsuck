/*!
 * DeepSuck — demo.js：沙盒演示页 UI（访客扮演骗子）。
 * URL 参数（便于截图/自动演示）：?scenario=police&persona=zheng&autoplay=4&fast=1&summary=1
 * Apache-2.0
 */
(function () {
  'use strict';
  var D = window.DeepSuck;
  var $ = function (id) { return document.getElementById(id); };
  // 界面文案按语言取值（i18n.js）；人设台词、骗子样例与对话记录属演示语料，英文版保留中文（data-i18n-keep="dialogue"）
  var I = window.DeepSuckI18n || { L: function (zh) { return zh; }, tr: function (x) { return x; }, trParts: function (x) { return x; } };
  var L = I.L, tr = I.tr;
  var params = new URLSearchParams(location.search);
  var FAST = params.get('fast') === '1';
  // 公开实时服务（见 live-config.js）；为空时沿用同源 api/（npm start 自托管）
  var LIVE = String((window.DEEPSUCK_LIVE && window.DEEPSUCK_LIVE.api) || '').replace(/\/+$/, '');
  var API = LIVE ? LIVE + '/api/' : 'api/';
  // 只有配置了实时服务（live-config.js 的 api）或由 npm start 托管（server 注入 local=true）时才探测后端；
  // 纯静态托管不发任何 api 请求。?proxy=1 可强制探测（例如自己用 Nginx 反代了 server/）。
  var HAS_BACKEND = !!LIVE || !!(window.DEEPSUCK_LIVE && window.DEEPSUCK_LIVE.local) || params.get('proxy') === '1';

  var state = {
    scenario: params.get('scenario') || 'refund',
    persona: params.get('persona') || 'wang',
    session: null,
    queue: Promise.resolve(),
    gen: 0,
    engine: 'rule',
    proxyOk: false,
    direct: { baseUrl: D.llm.DEFAULTS.baseUrl, model: D.llm.DEFAULTS.model, apiKey: '' },
    timer: null
  };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  }
  function fmt(sec) {
    sec = Math.max(0, Math.round(sec));
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }
  function fmtHuman(sec) {
    sec = Math.round(sec);
    var m = Math.floor(sec / 60), s = sec % 60;
    return m ? m + L(' 分 ', ' min ') + s + L(' 秒', ' s') : s + L(' 秒', ' s');
  }
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.style.display = 'block';
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.style.display = 'none'; }, 3200);
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, FAST ? 0 : ms); }); }

  /* ---------- 选择器 ---------- */
  function renderOptions() {
    $('scenarioOpts').innerHTML = D.scenarios.SCENARIOS.map(function (s) {
      return '<button class="opt' + (s.id === state.scenario ? ' on' : '') + '" data-sc="' + s.id + '">' + esc(tr(s.title)) + '</button>';
    }).join('');
    $('personaOpts').innerHTML = D.personas.PERSONAS.map(function (p) {
      return '<button class="opt' + (p.id === state.persona ? ' on' : '') + '" data-pe="' + p.id + '">' + esc(p.no + ' ' + tr(p.name)) + '<small>' + esc(tr(p.role)) + '</small></button>';
    }).join('');
    var sc = D.scenarios.BY_ID[state.scenario];
    $('samples').innerHTML = '<span class="note" style="flex:none;align-self:center">' + L('样例：', 'Samples:') + '</span>' + sc.samples.map(function (l, i) {
      var src = (sc.sampleSources || [])[i];
      return '<button data-sample="' + i + '" data-i18n-keep="dialogue" title="' + esc(l) + (src ? '\n' + L('来源：', 'Source: ') + esc(tr(src.label)) : '') + '">' + (i + 1) + '. ' + esc(l) + '</button>';
    }).join('');
    renderSampleSources(sc);
  }
  /* 样例出处：按 label 汇总条数，有公开链接的挂链接（数据见 scenarios.json 的 sampleSources[]） */
  function renderSampleSources(sc) {
    var el = $('sampleSrc');
    if (!el) return;
    var list = sc.sampleSources || [], order = [], by = {};
    list.forEach(function (x) {
      if (!x || !x.label) return;
      if (!by[x.label]) { by[x.label] = { n: 0, url: '' }; order.push(x.label); }
      by[x.label].n++;
      if (!by[x.label].url && /^https:\/\//.test(x.url || '') && x.sourceType !== 'awareness') by[x.label].url = x.url;
    });
    el.innerHTML = order.length ? L('本场景样例：', 'Samples in this scenario: ') + order.map(function (k) {
      var t = esc(tr(k));
      if (by[k].url) t = '<a href="' + esc(by[k].url) + '" target="_blank" rel="noopener noreferrer">' + t + '</a>';
      return t + ' ' + by[k].n + L(' 条', '');
    }).join(L('，', '; ')) + L('。', '.') : '';
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-sc],[data-pe],[data-sample]');
    if (!b) return;
    if (b.dataset.sc) { state.scenario = b.dataset.sc; newSession(); }
    else if (b.dataset.pe) { state.persona = b.dataset.pe; newSession(); }
    else if (b.dataset.sample != null) {
      var line = D.scenarios.BY_ID[state.scenario].samples[+b.dataset.sample];
      send(line);
    }
  });

  /* ---------- 会话 ---------- */
  function newSession() {
    state.gen++;
    state.queue = Promise.resolve();
    state.session = new D.engine.Session({ scenario: state.scenario, persona: state.persona, engine: engineName() });
    renderHeader();
    $('msgs').innerHTML = '';
    $('liveDot').textContent = L('进行中', 'In progress'); $('liveDot').style.color = 'var(--accent)';
    $('input').disabled = false; $('sendBtn').disabled = false;
    renderOptions(); renderPanel();
    var gen = state.gen;
    var opening = state.session.opening();
    state.queue = showBot(opening, gen);
    clearInterval(state.timer);
    state.timer = setInterval(renderStats, 1000);
  }

  function renderHeader() {
    var p = state.session.persona;
    $('botAvatar').textContent = tr(p.avatar);
    $('botName').textContent = tr(p.name);
    $('botTag').textContent = tr(p.name) + L('：', ': ') + tr(p.tagline);
    $('scLabel').textContent = tr(state.session.scenario.title);
  }

  function engineName() {
    if (state.engine === 'proxy') return 'llm-proxy';
    if (state.engine === 'direct') return 'llm-direct:' + state.direct.model;
    return 'rule';
  }

  function highlight(text, intel) {
    var h = esc(text);
    (intel || []).forEach(function (i) {
      var m = esc(i.masked);
      h = h.split(m).join('<mark class="intel">' + m + '</mark>');
    });
    return h;
  }

  // metaHtml 可以是函数（按当前语言生成），切换语言时 relabelMsgs 重新调用
  function addMsg(role, html, metaHtml) {
    var p = state.session.persona;
    var el = document.createElement('div');
    el.className = 'msg ' + role;
    var meta = typeof metaHtml === 'function' ? metaHtml() : metaHtml;
    el.innerHTML = '<div class="av">' + esc(tr(role === 'bot' ? p.avatar : '骗')) + '</div><div><div class="bub" data-i18n-keep="dialogue">' + html + '</div>' +
      (meta ? '<div class="meta">' + meta + '</div>' : '') + '</div>';
    el._avatar = role === 'bot' ? p.avatar : '骗';
    if (typeof metaHtml === 'function') el._meta = metaHtml;
    $('msgs').appendChild(el);
    $('msgs').scrollTop = $('msgs').scrollHeight;
    return el;
  }

  function showBot(msg, gen) {
    var typing = addMsg('bot', '<span class="dots"><span></span><span></span><span></span></span> ' + esc(tr(state.session.persona.name)) + L(' 正在输入…', ' is typing…'));
    typing.classList.add('typing');
    return sleep(state.session.typingDelay(msg.text)).then(function () {
      typing.remove();
      if (gen !== state.gen) return;
      var intentLabel = function () { return I.isEn && I.isEn() ? { opening: 'Opening', ask_repeat: 'Asks to repeat', misunderstand: 'Deliberate misunderstanding', tech_trouble: 'Fakes tech trouble', slow_walk: 'Stalling', otp_stall: 'OTP stalling',
        elicit_account: 'Draws out an account', elicit_wallet: 'Draws out a wallet', elicit_contact: 'Draws out contact details', elicit_url: 'Draws out a link', confirm_intel: 'Repeats back and follows up',
        fake_progress: 'Fakes a failed transfer', scared: 'Acts scared', secrecy: 'Pretends to keep it secret', greedy: 'Acts tempted', romance: 'Plays along warmly', info_stall: 'Withholds personal info', urgency_stall: 'Pushes back on urgency', generic: 'Agrees along',
        verify_identity: 'Verifies their identity', task_stall: 'Task-scam stalling', loan_stall: 'Loan-scam stalling', campus_stall: 'Campus-loan stalling' }[msg.intent] || msg.intent : { opening: '开场', ask_repeat: '请求重复', misunderstand: '故意误解', tech_trouble: '假装技术故障', slow_walk: '拖延', otp_stall: '验证码拖延',
        elicit_account: '诱导暴露账户', elicit_wallet: '诱导暴露钱包', elicit_contact: '诱导留联系方式', elicit_url: '诱导发链接', confirm_intel: '复述并追问',
        fake_progress: '假装转账受阻', scared: '装害怕', secrecy: '假意保密', greedy: '装心动', romance: '周旋示好', info_stall: '拒给个人信息', urgency_stall: '反催促', generic: '附和',
        verify_identity: '反向核验身份', task_stall: '刷单周旋', loan_stall: '贷款周旋', campus_stall: '校园贷周旋' }[msg.intent] || msg.intent; };
      addMsg('bot', esc(msg.text), function () { return '<span class="note">' + L('策略：', 'Strategy: ') + esc(intentLabel()) + (msg.engine ? ' · ' + esc(tr(msg.engine)) : '') + '</span>'; });
      renderPanel();
    });
  }

  function send(text) {
    text = String(text || '').trim();
    if (!text || !state.session || state.session.endedAt) return;
    var gen = state.gen;
    var s = state.session;
    var a = s.ingest(text);
    var meta = function () {
      return a.tactics.map(function (t) { return '<span class="tag">' + esc(tr(t.label)) + '</span>'; }).join('') +
        (a.newIntel.length ? '<span class="tag amber">+' + a.newIntel.length + L(' 条情报', ' intel') + '</span>' : '');
    };
    addMsg('scammer', highlight(a.redacted, a.newIntel), meta);
    renderPanel(a.newIntel);
    checkBlocklists(s);
    state.queue = state.queue.then(function () {
      if (gen !== state.gen || s.endedAt) return;
      return produceReply(s, a).then(function (msg) { if (msg) return showBot(msg, gen); });
    });
    return state.queue;
  }

  function produceReply(s, a) {
    if (state.engine === 'rule') return Promise.resolve(s.ruleReply(a));
    var hint = s.chooseIntent(a);
    var payload = {
      persona: s.persona.id, scenario: s.scenario.id, hint: hint, missing: s.missingGoals(),
      transcript: s.messages.map(function (m) { return { role: m.role, text: m.text }; })
    };
    var call = state.engine === 'proxy'
      ? D.llm.viaProxy(payload, API + 'chat')
      : D.llm.chatCompletions(state.direct, D.llm.buildMessages(payload));
    return call.then(function (reply) {
      var m = s.recordBot(reply, hint); m.engine = '大模型'; return m;
    }).catch(function (e) {
      console.warn(e);
      toast(L('大模型调用失败，已回退到规则引擎：', 'LLM call failed; fell back to the rule engine: ') + String(e.message).slice(0, 60));
      var m = s.ruleReply(a); m.engine = '规则回退'; return m;
    });
  }

  /* ---------- 黑名单比对（网址 / 钱包；本地分片 + 运行时公开列表，仅供参考） ---------- */
  var BL = D.blocklist ? D.blocklist.createClient({ base: 'data/blocklist/' }) : null;
  function checkBlocklists(s) {
    if (!BL) return;
    s.pendingBlocklist().forEach(function (p) {
      s.annotate(p.key, { status: 'pending' });
      BL.check(p.type, p.raw).then(function (r) {
        if (r.status === 'skip') r = { status: 'unavailable' };
        s.annotate(p.key, r);
        if (state.session === s) { renderPanel(); if ($('summaryModal').open) openSummary(); }
      });
    });
  }
  function blBadge(b, compact) {
    if (!b) return '';
    var BL_TEXT = { hit: L('命中公开黑名单', 'On a public blocklist'), clean: L('未命中黑名单', 'Not on blocklists'), unavailable: L('黑名单暂不可用', 'Blocklists temporarily unavailable'), pending: L('比对黑名单中…', 'Checking blocklists…') };
    var BL_SHORT = { hit: L('命中黑名单', 'On blocklist'), clean: L('未命中黑名单', 'Not on blocklists'), unavailable: L('黑名单不可用', 'Blocklists unavailable'), pending: L('比对中…', 'Checking…') };
    var title = b.status === 'hit' ? L('来源：', 'Sources: ') + (b.sources || []).join(L('、', ', ')) + (b.how === 'parent' ? L('（父域名命中）', ' (parent domain matched)') : '') + L(' · 仅供参考，不能作为认定依据', ' · For reference only, not proof')
      : b.status === 'clean' ? L('已比对公开黑名单，未命中（不代表安全）', 'Checked against public blocklists, no match (does not mean safe)') : '';
    return '<span class="bl ' + b.status + '" title="' + esc(title) + '">' + esc((compact ? BL_SHORT : BL_TEXT)[b.status] || b.status) +
      (b.status === 'hit' ? ' · ' + esc((b.sources || []).join(' / ')) : '') + '</span>';
  }

  /* ---------- 侧栏 ---------- */
  function renderStats() {
    if (!state.session) return;
    var st = state.session.stats();
    $('stWall').textContent = fmt(st.wallClockSeconds);
    $('stEst').textContent = fmt(st.estimatedScammerSeconds);
    $('stMsgs').textContent = st.messages;
    $('stIntel').textContent = st.intelCount;
    $('stRisk').textContent = st.riskScore;
    $('riskBar').style.width = st.riskScore + '%';
  }
  function renderPanel(fresh) {
    var s = state.session;
    renderStats();
    var freshSet = {};
    (fresh || []).forEach(function (i) { freshSet[i.type + i.masked] = 1; });
    var list = s.intelList();
    $('intelList').innerHTML = list.length ? list.map(function (i) {
      return '<div class="intel-item' + (freshSet[i.type + i.masked] ? ' new' : '') + (i.blocklist && i.blocklist.status === 'hit' ? ' hit' : '') + '"><span class="t">' + esc(tr(i.label)) + '</span><span class="v"><span data-i18n-keep="intel-data">' + esc(i.masked) + '</span>' +
        (i.meta && i.meta.bank ? ' <span class="note" data-i18n-keep="intel-data">' + esc(i.meta.bank) + '</span>' : '') + (i.blocklist ? '<br>' + blBadge(i.blocklist, true) : '') + '</span></div>';
    }).join('') : '<div class="empty">' + L('等待骗子露出马脚……', 'Waiting for the scammer to slip up…') + '</div>';
    var tl = s.tacticList();
    $('tacticList').innerHTML = tl.length ? tl.map(function (t) {
      return '<span class="tag">' + esc(tr(t.label)) + (t.count > 1 ? ' ×' + t.count : '') + '</span>';
    }).join('') : '<span class="empty">' + L('暂无', 'None yet') + '</span>';
    $('engineLabel').textContent = L('引擎：', 'Engine: ') + ({ rule: L('规则引擎（本地）', 'Rule engine (local)'), proxy: LIVE ? L('大模型 · 在线服务', 'LLM · online service') : L('大模型 · 本地代理', 'LLM · local proxy'), direct: L('大模型 · 直连 ', 'LLM · direct ') + state.direct.model }[state.engine]);
    $('engineLabel').setAttribute('data-short', state.engine === 'rule' ? L('规则', 'Rules') : L('大模型', 'LLM'));
    $('engineLabel').classList.toggle('is-llm', state.engine !== 'rule');
  }

  /* ---------- 弹窗 ---------- */
  function openDialog(id) {
    var d = $(id);
    if (d.open) return;
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
  }
  function closeDialog(id) {
    var d = $(id);
    if (!d.open) return;
    if (typeof d.close === 'function') d.close(); else d.removeAttribute('open');
  }

  /* ---------- 看板 ---------- */
  function openSummary() {
    var s = state.session;
    s.end();
    state.gen++; // 取消尚未显示的回复
    clearInterval(state.timer);
    renderStats();
    $('liveDot').textContent = L('已结束', 'Ended'); $('liveDot').style.color = 'var(--dim)';
    $('input').disabled = true; $('sendBtn').disabled = true;
    var r = s.report();
    var st = r.stats;
    var engLabel = r.session.engine === 'rule' ? L('规则引擎', 'Rule engine') : /^llm/.test(r.session.engine) ? L('大模型', 'LLM') : r.session.engine;
    $('sumSub').textContent = tr(r.session.scenario.title) + ' · ' + tr(r.session.persona.name) + ' · ' + engLabel;
    $('dashStats').innerHTML = [
      [L('估算骗子耗时', 'Estimated scammer time'), fmtHuman(st.estimatedScammerSeconds)], [L('实际对话时长', 'Actual chat duration'), fmtHuman(st.wallClockSeconds)],
      [L('消息数', 'Messages'), st.messages + L('（骗子 ', ' (scammer ') + st.scammerMessages + L('）', ')')], [L('情报条数', 'Intel items'), st.intelCount], [L('黑名单命中', 'Blocklist hits'), r.intel.filter(function (i) { return i.blocklist && i.blocklist.status === 'hit'; }).length], [L('风险评分', 'Risk score'), st.riskScore + '/100']
    ].map(function (x) { return '<div class="stat"><div class="v" style="font-size:18px">' + esc(x[1]) + '</div><div class="k">' + esc(x[0]) + '</div></div>'; }).join('');

    $('dashIntel').innerHTML = r.intel.length ? r.intel.map(function (i) {
      var m = [];
      // m 里是已转义的 HTML 片段；开户行名称是情报数据，原样保留
      if (i.meta.bank) m.push(esc(L('开户行：', 'Bank: ')) + '<span data-i18n-keep="intel-data">' + esc(i.meta.bank) + '</span>' + esc(i.meta.bankFrom === 'bin' ? L('（BIN 推断）', ' (inferred from BIN)') : ''));
      if (i.meta.issuer) m.push(esc(tr(i.meta.issuer.cardTypeName) + (i.meta.issuer.lengthOk ? '' : L(' · 卡号长度与 BIN 不符', ' · card length does not match BIN'))));
      if (i.meta.digits) m.push(esc(i.meta.digits + L(' 位', ' digits') + (i.meta.luhn ? L(' · Luhn 校验通过', ' · Luhn check passed') : L(' · Luhn 未通过', ' · Luhn check failed'))));
      if (i.meta.chain) m.push(esc(L('链：', 'Chain: ') + i.meta.chain));
      if (i.meta.kind) m.push(esc({ mobile: L('手机', 'Mobile'), hotline: L('400/800 热线', '400/800 hotline'), landline: L('座机', 'Landline') }[i.meta.kind]));
      m.push(esc(L('首次出现：第 ', 'First seen: turn ') + i.firstSeenTurn + L(' 轮', '') + (i.count > 1 ? L(' · 重复 ', ' · repeated ') + i.count + L(' 次', ' times') : '')));
      return '<div class="icard' + (i.blocklist && i.blocklist.status === 'hit' ? ' hit' : '') + '"><div class="h"><span>' + esc(tr(i.label)) + '</span><span class="tag amber">' + L('已脱敏', 'Masked') + '</span></div>' +
        '<div class="val" data-i18n-keep="intel-data">' + esc(i.masked) + '</div><div class="m">' + m.join(' · ') + '</div>' + (i.blocklist ? '<div class="m">' + blBadge(i.blocklist) + '</div>' : '') + '</div>';
    }).join('') : '<div class="empty">' + L('本次对话未提取到账户/地址类情报。试试样例台词中带卡号、钱包地址的句子。', 'No account or address intel was extracted from this chat. Try the sample lines that contain card numbers or wallet addresses.') + '</div>';

    var ctx = [];
    Object.keys(r.context).forEach(function (type) {
      var lbl = tr(D.extractors.LABELS[type] || type);
      Object.keys(r.context[type]).forEach(function (v) { ctx.push('<span class="tag amber">' + esc(lbl) + L('：', ': ') + '<span data-i18n-keep="intel-data">' + esc(v) + '</span></span>'); });
    });
    $('dashContext').innerHTML = ctx.join('') || '<span class="empty">' + L('无', 'None') + '</span>';

    var max = Math.max.apply(null, [1].concat(r.tactics.map(function (t) { return t.count; })));
    $('dashTactics').innerHTML = r.tactics.length ? r.tactics.map(function (t) {
      return '<div class="bar"><span class="l">' + esc(tr(t.label)) + '</span><span class="track"><i style="width:' + Math.round(100 * t.count / max) + '%"></i></span><span class="c">' + t.count + '</span></div>';
    }).join('') : '<div class="empty">' + L('未识别到典型话术', 'No typical tactics detected') + '</div>';

    var t0 = s.startedAt;
    $('dashTranscript').innerHTML = r.transcript.map(function (m) {
      var sec = Math.round((Date.parse(m.at) - t0) / 1000);
      return '<div class="line"><span class="tm">+' + fmt(sec) + '</span><span class="r ' + (m.role === 'bot' ? 'b' : 's') + '">' +
        (m.role === 'bot' ? esc(tr(s.persona.name)) : L('骗子', 'Scammer')) + '</span><span data-i18n-keep="dialogue">' + esc(m.text) + '</span></div>';
    }).join('');
    $('submitBox').hidden = true;
    openDialog('summaryModal');
    if (params.get('submit') === '1') openSubmit();
  }

  function exportJSON() {
    var r = state.session.report();
    var blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'deepsuck-intel-' + r.session.scenario.id + '-' + r.generatedAt.replace(/[:.]/g, '-') + '.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
    toast(L('已导出脱敏情报报告', 'Masked intel report exported'));
  }

  /* ---------- 提交到情报库 ---------- */
  var SCENARIO_OPTION = { refund: '冒充客服 · 退款理赔', police: '冒充公检法 · 安全账户', pig: '杀猪盘 · 投资/感情', task: '刷单返利 · 做任务赚佣金',
    loan: '虚假贷款 · 征信修复', boss: '冒充领导/熟人 · 借钱转账', campus: '注销校园贷 · 清空网贷额度' };
  function openSubmit() {
    var s = state.session;
    var sub = s.submission();
    var box = $('submitBox');
    if (!sub.indicators.length) {
      box.hidden = false;
      $('submitText').value = L('本次对话没有提取到可收录的情报（电话、钱包地址、网址、APP、收款账户）。', 'No publishable intel (phones, wallet addresses, URLs, apps, receiving accounts) was extracted from this chat.');
      $('submitOpen').style.display = 'none';
      return;
    }
    var md = D.intel.submissionMarkdown(sub);
    $('submitText').value = md + '\n\n话术标签：' + sub.tactics.join(', ');
    var q = new URLSearchParams({
      template: 'intel-submission.yml',
      title: '[情报提交] ' + s.scenario.title,
      indicators: md,
      tactics: sub.tactics.join(', ')
    });
    if (SCENARIO_OPTION[s.scenario.id]) q.set('scenario', SCENARIO_OPTION[s.scenario.id]);
    $('submitOpen').href = 'https://github.com/deepsucksi/deepsuck/issues/new?' + q.toString();
    $('submitOpen').style.display = '';
    box.hidden = false;
    box.scrollIntoView({ behavior: FAST ? 'auto' : 'smooth', block: 'nearest' });
  }
  function copySubmit() {
    var v = $('submitText').value;
    (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(function () { toast(L('已复制，可粘贴到 GitHub 情报提交模板', 'Copied; paste it into the GitHub intel submission template')); },
      function () { $('submitText').select(); toast(L('请手动复制（Ctrl/Cmd+C）', 'Please copy manually (Ctrl/Cmd+C)')); });
  }

  /* ---------- 设置 ---------- */
  function loadSettings() {
    try {
      var saved = JSON.parse(localStorage.getItem('deepsuck.llm') || 'null');
      if (saved) { state.direct = Object.assign(state.direct, saved); state.engine = saved.engine || 'rule'; }
    } catch (e) {}
    if (state.engine === 'direct' && !state.direct.apiKey) state.engine = 'rule';
  }
  function openSettings() {
    document.querySelectorAll('input[name=engine]').forEach(function (r) { r.checked = r.value === state.engine; });
    $('cfgBase').value = state.direct.baseUrl; $('cfgModel').value = state.direct.model; $('cfgKey').value = state.direct.apiKey || '';
    openDialog('settingsModal');
  }
  function saveSettings() {
    var eng = (document.querySelector('input[name=engine]:checked') || {}).value || 'rule';
    state.direct.baseUrl = $('cfgBase').value.trim() || D.llm.DEFAULTS.baseUrl;
    state.direct.model = $('cfgModel').value.trim() || D.llm.DEFAULTS.model;
    state.direct.apiKey = $('cfgKey').value.trim();
    if (eng === 'proxy' && !state.proxyOk) { toast(L('未检测到已配置的本地代理（npm start + .env），仍使用规则引擎', 'No configured local proxy detected (npm start + .env); still using the rule engine')); eng = 'rule'; }
    if (eng === 'direct' && !state.direct.apiKey) { toast(L('请先填写 API Key', 'Please enter an API key first')); return; }
    state.engine = eng;
    try {
      if ($('cfgRemember').checked) localStorage.setItem('deepsuck.llm', JSON.stringify({ engine: eng, baseUrl: state.direct.baseUrl, model: state.direct.model, apiKey: state.direct.apiKey }));
      else localStorage.removeItem('deepsuck.llm');
    } catch (e) {}
    closeDialog('settingsModal');
    state.session.engineName = engineName();
    renderPanel();
    toast(L('已切换：', 'Switched: ') + $('engineLabel').textContent);
  }
  var proxyStatus = null; // 返回当前语言文案的函数，切换语言时重渲染
  function setProxyStatus(fn) { proxyStatus = fn; $('proxyStatus').textContent = fn(); }
  function probeProxy() {
    if (!HAS_BACKEND) { setProxyStatus(function () { return L('纯静态托管，未配置后端（使用规则引擎）。自托管运行 npm start 即可启用。', 'Static hosting with no backend configured (using the rule engine). Run npm start when self-hosting to enable it.'); }); return; }
    fetch(API + 'health', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j && LIVE) document.querySelectorAll('[data-live-voice]').forEach(function (a) { a.href = LIVE + '/'; a.hidden = false; });
      if (j && j.llmConfigured && j.budget && j.budget.exhausted) {
        setProxyStatus(function () { return L('代理在线，但今日大模型体验额度已用完（使用规则引擎）', 'Proxy online, but today\'s LLM trial quota is used up (using the rule engine)'); });
      } else if (j && j.llmConfigured) {
        state.proxyOk = true;
        setProxyStatus(function () { return L('已检测到代理：', 'Proxy detected: ') + j.model + ' @ ' + j.provider; });
        if (!localStorage.getItem('deepsuck.llm') && !FAST) { state.engine = 'proxy'; state.session.engineName = engineName(); renderPanel(); toast(L('检测到已配置的大模型代理，已切换到 ', 'Configured LLM proxy detected; switched to ') + j.model); }
      } else if (j) {
        setProxyStatus(function () { return L('代理在线，但未配置 API Key（编辑 .env 中的 LLM_API_KEY，见 docs/QUICKSTART.md）', 'Proxy online, but no API key configured (set LLM_API_KEY in .env; see docs/QUICKSTART.md)'); });
      } else throw new Error();
    }).catch(function () { setProxyStatus(function () { return L('未检测到代理（纯静态托管时正常）。运行 npm start 可启用。', 'No proxy detected (normal for static hosting). Run npm start to enable it.'); }); });
  }

  /* ---------- 绑定 ---------- */
  $('sendBtn').addEventListener('click', function () { var v = $('input').value; $('input').value = ''; send(v); });
  $('input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('sendBtn').click(); }
  });
  $('endBtn').addEventListener('click', openSummary);
  $('exportBtn').addEventListener('click', exportJSON);
  $('sumExport').addEventListener('click', exportJSON);
  $('sumSubmit').addEventListener('click', openSubmit);
  $('submitCopy').addEventListener('click', copySubmit);
  $('resetBtn').addEventListener('click', newSession);
  $('sumNew').addEventListener('click', function () { closeDialog('summaryModal'); newSession(); });
  $('sumClose').addEventListener('click', function () { closeDialog('summaryModal'); });
  $('settingsBtn').addEventListener('click', openSettings);
  $('setClose').addEventListener('click', function () { closeDialog('settingsModal'); });
  $('setSave').addEventListener('click', saveSettings);
  // 原生 <dialog>：showModal() 自带焦点陷阱、Esc 关闭与背景 inert；点遮罩也可关闭
  ['summaryModal', 'settingsModal'].forEach(function (id) {
    $(id).addEventListener('click', function (e) { if (e.target === e.currentTarget) closeDialog(id); });
  });

  // 切换语言：重渲染界面文案；已有对话气泡（演示语料）不变
  document.addEventListener('deepsuck:languagechange', function () {
    if (!state.session) return;
    renderHeader(); renderOptions(); renderPanel();
    document.querySelectorAll('#msgs .msg').forEach(function (el) {
      var av = el.querySelector('.av'); if (av && el._avatar) av.textContent = tr(el._avatar);
      var m = el.querySelector('.meta'); if (m && el._meta) m.innerHTML = el._meta();
    });
    $('liveDot').textContent = state.session.endedAt ? L('已结束', 'Ended') : L('进行中', 'In progress');
    if (proxyStatus) $('proxyStatus').textContent = proxyStatus();
    if ($('summaryModal').open) openSummary();
  });

  loadSettings();
  if (!D.scenarios.BY_ID[state.scenario]) state.scenario = 'refund';
  state.persona = D.personas.resolveId(state.persona);
  if (!D.personas.BY_ID[state.persona]) state.persona = 'wang';
  newSession();
  probeProxy();

  // 自动演示：依次发送前 N 条样例台词
  var auto = parseInt(params.get('autoplay') || '0', 10);
  if (auto > 0) {
    var lines = D.scenarios.BY_ID[state.scenario].samples.slice(0, auto);
    var chain = state.queue;
    lines.forEach(function (l) { chain = chain.then(function () { return sleep(400); }).then(function () { return send(l); }); });
    chain.then(function () { document.body.setAttribute('data-autoplay-done', '1'); if (params.get('summary') === '1') openSummary(); });
  }
})();
