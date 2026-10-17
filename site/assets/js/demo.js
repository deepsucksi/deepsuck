/*!
 * DeepSuck — demo.js：沙盒演示页 UI（访客扮演骗子）。
 * URL 参数（便于截图/自动演示）：?scenario=police&persona=li&autoplay=4&fast=1&summary=1
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
 */
(function () {
  'use strict';
  var D = window.DeepSuck;
  var $ = function (id) { return document.getElementById(id); };
  var params = new URLSearchParams(location.search);
  var FAST = params.get('fast') === '1';
  // 公开实时服务（见 live-config.js）；为空时沿用同源 api/（npm start 自托管）
  var LIVE = String((window.DEEPSUCK_LIVE && window.DEEPSUCK_LIVE.api) || '').replace(/\/+$/, '');
  var API = LIVE ? LIVE + '/api/' : 'api/';

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
    return m ? m + ' 分 ' + s + ' 秒' : s + ' 秒';
  }
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.style.display = 'block';
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.style.display = 'none'; }, 3200);
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, FAST ? 0 : ms); }); }

  /* ---------- 选择器 ---------- */
  function renderOptions() {
    $('scenarioOpts').innerHTML = D.scenarios.SCENARIOS.map(function (s) {
      return '<button class="opt' + (s.id === state.scenario ? ' on' : '') + '" data-sc="' + s.id + '">' + s.icon + ' ' + esc(s.title) + '</button>';
    }).join('');
    $('personaOpts').innerHTML = D.personas.PERSONAS.map(function (p) {
      return '<button class="opt' + (p.id === state.persona ? ' on' : '') + '" data-pe="' + p.id + '">' + p.avatar + ' ' + esc(p.name) + '<small>' + esc(p.tagline) + '</small></button>';
    }).join('');
    var sc = D.scenarios.BY_ID[state.scenario];
    $('samples').innerHTML = '<span class="note" style="flex:none;align-self:center">样例：</span>' + sc.samples.map(function (l, i) {
      return '<button data-sample="' + i + '" title="' + esc(l) + '">' + (i + 1) + '. ' + esc(l) + '</button>';
    }).join('');
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
    var p = state.session.persona;
    $('botAvatar').textContent = p.avatar;
    $('botName').textContent = p.name;
    $('botTag').textContent = p.tagline;
    $('msgs').innerHTML = '';
    $('liveDot').textContent = '● 进行中'; $('liveDot').style.color = 'var(--green)';
    $('input').disabled = false; $('sendBtn').disabled = false;
    renderOptions(); renderPanel();
    var gen = state.gen;
    var opening = state.session.opening();
    state.queue = showBot(opening, gen);
    clearInterval(state.timer);
    state.timer = setInterval(renderStats, 1000);
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

  function addMsg(role, html, metaHtml) {
    var p = state.session.persona;
    var el = document.createElement('div');
    el.className = 'msg ' + role;
    el.innerHTML = '<div class="av">' + (role === 'bot' ? p.avatar : '🕵️') + '</div><div><div class="bub">' + html + '</div>' +
      (metaHtml ? '<div class="meta">' + metaHtml + '</div>' : '') + '</div>';
    $('msgs').appendChild(el);
    $('msgs').scrollTop = $('msgs').scrollHeight;
    return el;
  }

  function showBot(msg, gen) {
    var typing = addMsg('bot', '<span class="dots"><span></span><span></span><span></span></span> ' + esc(state.session.persona.name) + ' 正在输入…');
    typing.classList.add('typing');
    return sleep(state.session.typingDelay(msg.text)).then(function () {
      typing.remove();
      if (gen !== state.gen) return;
      var intentLabel = { opening: '开场', ask_repeat: '请求重复', misunderstand: '故意误解', tech_trouble: '假装技术故障', slow_walk: '拖延', otp_stall: '验证码拖延',
        elicit_account: '诱导暴露账户', elicit_wallet: '诱导暴露钱包', elicit_contact: '诱导留联系方式', elicit_url: '诱导发链接', confirm_intel: '复述并追问',
        fake_progress: '假装转账受阻', scared: '装害怕', secrecy: '假意保密', greedy: '装心动', romance: '周旋示好', info_stall: '拒给个人信息', urgency_stall: '反催促', generic: '附和',
        verify_identity: '反向核验身份', task_stall: '刷单周旋', loan_stall: '贷款周旋', campus_stall: '校园贷周旋' }[msg.intent] || msg.intent;
      addMsg('bot', esc(msg.text), '<span class="note">策略：' + esc(intentLabel) + (msg.engine ? ' · ' + esc(msg.engine) : '') + '</span>');
      renderPanel();
    });
  }

  function send(text) {
    text = String(text || '').trim();
    if (!text || !state.session || state.session.endedAt) return;
    var gen = state.gen;
    var s = state.session;
    var a = s.ingest(text);
    var meta = a.tactics.map(function (t) { return '<span class="tag">' + esc(t.label) + '</span>'; }).join('') +
      (a.newIntel.length ? '<span class="tag amber">+' + a.newIntel.length + ' 条情报</span>' : '');
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
      toast('大模型调用失败，已回退到规则引擎：' + String(e.message).slice(0, 60));
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
        if (state.session === s) { renderPanel(); if ($('summaryModal').classList.contains('open')) openSummary(); }
      });
    });
  }
  var BL_TEXT = { hit: '⚠ 命中公开黑名单', clean: '✓ 未命中黑名单', unavailable: '黑名单暂不可用', pending: '比对黑名单中…' };
  var BL_SHORT = { hit: '⚠ 黑名单', clean: '✓ 未命中黑名单', unavailable: '黑名单不可用', pending: '比对中…' };
  function blBadge(b, compact) {
    if (!b) return '';
    var title = b.status === 'hit' ? '来源：' + (b.sources || []).join('、') + (b.how === 'parent' ? '（父域名命中）' : '') + ' · 仅供参考，不能作为认定依据'
      : b.status === 'clean' ? '已比对公开黑名单，未命中（不代表安全）' : '';
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
      return '<div class="intel-item' + (freshSet[i.type + i.masked] ? ' new' : '') + (i.blocklist && i.blocklist.status === 'hit' ? ' hit' : '') + '"><span class="t">' + esc(i.label) + '</span><span class="v">' + esc(i.masked) +
        (i.meta && i.meta.bank ? ' <span class="note">' + esc(i.meta.bank) + '</span>' : '') + (i.blocklist ? '<br>' + blBadge(i.blocklist, true) : '') + '</span></div>';
    }).join('') : '<div class="empty">等待骗子露出马脚……</div>';
    var tl = s.tacticList();
    $('tacticList').innerHTML = tl.length ? tl.map(function (t) {
      return '<span class="tag">' + esc(t.label) + (t.count > 1 ? ' ×' + t.count : '') + '</span>';
    }).join('') : '<span class="empty">暂无</span>';
    $('engineLabel').textContent = '引擎：' + ({ rule: '规则引擎（本地）', proxy: '大模型 · 本地代理', direct: '大模型 · 直连 ' + state.direct.model }[state.engine]);
  }

  /* ---------- 看板 ---------- */
  var TYPE_ICON = { bank_card: '💳', phone: '📞', crypto_btc: '₿', crypto_eth: '⟠', crypto_tron: '🔺', url: '🔗', email: '✉️', qq: '🐧', wechat: '💬', alipay: '🅰️', id_card: '🪪', name: '👤' };

  function openSummary() {
    var s = state.session;
    s.end();
    state.gen++; // 取消尚未显示的回复
    clearInterval(state.timer);
    renderStats();
    $('liveDot').textContent = '■ 已结束'; $('liveDot').style.color = 'var(--dim)';
    $('input').disabled = true; $('sendBtn').disabled = true;
    var r = s.report();
    var st = r.stats;
    $('sumSub').textContent = r.session.scenario.title + ' · ' + r.session.persona.name + ' · 引擎 ' + r.session.engine;
    $('dashStats').innerHTML = [
      ['估算骗子耗时', fmtHuman(st.estimatedScammerSeconds)], ['实际对话时长', fmtHuman(st.wallClockSeconds)],
      ['消息数', st.messages + '（骗子 ' + st.scammerMessages + '）'], ['情报条数', st.intelCount], ['黑名单命中', r.intel.filter(function (i) { return i.blocklist && i.blocklist.status === 'hit'; }).length], ['风险评分', st.riskScore + '/100']
    ].map(function (x) { return '<div class="stat"><div class="v" style="font-size:18px">' + esc(x[1]) + '</div><div class="k">' + esc(x[0]) + '</div></div>'; }).join('');

    $('dashIntel').innerHTML = r.intel.length ? r.intel.map(function (i) {
      var m = [];
      if (i.meta.bank) m.push('开户行：' + i.meta.bank);
      if (i.meta.digits) m.push(i.meta.digits + ' 位' + (i.meta.luhn ? ' · Luhn 校验通过' : ' · Luhn 未通过'));
      if (i.meta.chain) m.push('链：' + i.meta.chain);
      if (i.meta.kind) m.push({ mobile: '手机', hotline: '400/800 热线', landline: '座机' }[i.meta.kind]);
      m.push('首次出现：第 ' + i.firstSeenTurn + ' 轮' + (i.count > 1 ? ' · 重复 ' + i.count + ' 次' : ''));
      return '<div class="icard' + (i.blocklist && i.blocklist.status === 'hit' ? ' hit' : '') + '"><div class="h"><span>' + (TYPE_ICON[i.type] || '•') + ' ' + esc(i.label) + '</span><span class="tag amber">已脱敏</span></div>' +
        '<div class="val">' + esc(i.masked) + '</div><div class="m">' + esc(m.join(' · ')) + '</div>' + (i.blocklist ? '<div class="m">' + blBadge(i.blocklist) + '</div>' : '') + '</div>';
    }).join('') : '<div class="empty">本次对话未提取到账户/地址类情报。试试样例台词中带卡号、钱包地址的句子。</div>';

    var ctx = [];
    Object.keys(r.context).forEach(function (type) {
      var lbl = D.extractors.LABELS[type] || type;
      Object.keys(r.context[type]).forEach(function (v) { ctx.push('<span class="tag amber">' + esc(lbl) + '：' + esc(v) + '</span>'); });
    });
    $('dashContext').innerHTML = ctx.join('') || '<span class="empty">无</span>';

    var max = Math.max.apply(null, [1].concat(r.tactics.map(function (t) { return t.count; })));
    $('dashTactics').innerHTML = r.tactics.length ? r.tactics.map(function (t) {
      return '<div class="bar"><span class="l">' + esc(t.label) + '</span><span class="track"><i style="width:' + Math.round(100 * t.count / max) + '%"></i></span><span class="c">' + t.count + '</span></div>';
    }).join('') : '<div class="empty">未识别到典型话术</div>';

    var t0 = s.startedAt;
    $('dashTranscript').innerHTML = r.transcript.map(function (m) {
      var sec = Math.round((Date.parse(m.at) - t0) / 1000);
      return '<div class="line"><span class="tm">+' + fmt(sec) + '</span><span class="r ' + (m.role === 'bot' ? 'b' : 's') + '">' +
        (m.role === 'bot' ? s.persona.avatar + ' ' + esc(s.persona.name) : '🕵️ 骗子') + '</span>' + esc(m.text) + '</div>';
    }).join('');
    $('submitBox').hidden = true;
    $('summaryModal').classList.add('open');
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
    toast('已导出脱敏情报报告');
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
      $('submitText').value = '本次对话没有提取到可收录的情报（电话、钱包地址、网址、APP、收款账户）。';
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
    (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(function () { toast('已复制，可粘贴到 GitHub 情报提交模板'); },
      function () { $('submitText').select(); toast('请手动复制（Ctrl/⌘+C）'); });
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
    $('settingsModal').classList.add('open');
  }
  function saveSettings() {
    var eng = (document.querySelector('input[name=engine]:checked') || {}).value || 'rule';
    state.direct.baseUrl = $('cfgBase').value.trim() || D.llm.DEFAULTS.baseUrl;
    state.direct.model = $('cfgModel').value.trim() || D.llm.DEFAULTS.model;
    state.direct.apiKey = $('cfgKey').value.trim();
    if (eng === 'proxy' && !state.proxyOk) { toast('未检测到已配置的本地代理（npm start + .env），仍使用规则引擎'); eng = 'rule'; }
    if (eng === 'direct' && !state.direct.apiKey) { toast('请先填写 API Key'); return; }
    state.engine = eng;
    try {
      if ($('cfgRemember').checked) localStorage.setItem('deepsuck.llm', JSON.stringify({ engine: eng, baseUrl: state.direct.baseUrl, model: state.direct.model, apiKey: state.direct.apiKey }));
      else localStorage.removeItem('deepsuck.llm');
    } catch (e) {}
    $('settingsModal').classList.remove('open');
    state.session.engineName = engineName();
    renderPanel();
    toast('已切换：' + $('engineLabel').textContent);
  }
  function probeProxy() {
    if (location.protocol === 'file:' && !LIVE) { $('proxyStatus').textContent = '本地文件模式，无代理'; return; }
    fetch(API + 'health', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j && LIVE && $('liveVoiceLink')) { $('liveVoiceLink').href = LIVE + '/'; $('liveVoiceLink').hidden = false; }
      if (j && j.llmConfigured && j.budget && j.budget.exhausted) {
        $('proxyStatus').textContent = '代理在线，但今日大模型体验额度已用完（使用规则引擎）';
      } else if (j && j.llmConfigured) {
        state.proxyOk = true;
        $('proxyStatus').textContent = '✓ 已检测到代理：' + j.model + ' @ ' + j.provider;
        if (!localStorage.getItem('deepsuck.llm') && !FAST) { state.engine = 'proxy'; state.session.engineName = engineName(); renderPanel(); toast('检测到已配置的大模型代理，已切换到 ' + j.model); }
      } else if (j) {
        $('proxyStatus').textContent = '代理在线，但未配置 API Key（编辑 .env 中的 DASHSCOPE_API_KEY）';
      } else throw new Error();
    }).catch(function () { $('proxyStatus').textContent = '未检测到代理（纯静态托管时正常）。运行 npm start 可启用。'; });
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
  $('sumNew').addEventListener('click', function () { $('summaryModal').classList.remove('open'); newSession(); });
  $('sumClose').addEventListener('click', function () { $('summaryModal').classList.remove('open'); });
  $('settingsBtn').addEventListener('click', openSettings);
  $('setClose').addEventListener('click', function () { $('settingsModal').classList.remove('open'); });
  $('setSave').addEventListener('click', saveSettings);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { $('summaryModal').classList.remove('open'); $('settingsModal').classList.remove('open'); }
  });

  loadSettings();
  if (!D.scenarios.BY_ID[state.scenario]) state.scenario = 'refund';
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
