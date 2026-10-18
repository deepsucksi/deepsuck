/*!
 * DeepSuck — llm.js
 * 可选的大模型引擎（默认关闭）。兼容 OpenAI Chat Completions 协议，默认指向阿里云百炼 DashScope：
 *   https://dashscope.aliyuncs.com/compatible-mode/v1  （模型 qwen-plus）
 * 两种接入方式：
 *   1) proxy  —— 推荐。浏览器调用本项目自带的 server（/api/chat），API Key 只保存在服务器 .env 中；
 *   2) direct —— 浏览器直连（Key 存在本机浏览器，仅适合本地自用；部分服务商不支持跨域）。
 * 隐私：发送给大模型的对话记录在本地已脱敏；模型输出也会再经过安全过滤与脱敏。
 * 任何失败都会自动回退到规则引擎。
 * Apache-2.0
 */
(function (root, factory) {
  var isNode = typeof module === 'object' && module.exports;
  var deps = isNode ? {
    redact: require('./redact.js'), extractors: require('./extractors.js'),
    personas: require('./personas.js'), scenarios: require('./scenarios.js')
  } : root.DeepSuck;
  var mod = factory(deps);
  if (isNode) module.exports = mod;
  else { root.DeepSuck = root.DeepSuck || {}; root.DeepSuck.llm = mod; }
})(typeof self !== 'undefined' ? self : this, function (D) {
  'use strict';

  var DEFAULTS = {
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    temperature: 0.9,
    maxTokens: 200
  };

    // 每个拖延意图给大模型的提示（与 Python voice 端共用，见 core/personas.json 的 intentHints）
  var INTENT_HINTS = D.personas.INTENT_HINTS;

  function systemPrompt(persona, scenario, hint, missing) {
    var call = (persona.call && persona.call[scenario.id]) || '';
    return [
      '你在一个反诈骗研究沙盒中扮演"潜在受害人"角色，与扮演骗子的人对话。目标：尽可能拖延对方时间，并诱导对方主动暴露收款账户、钱包地址、电话、网址等情报。',
      '角色：' + persona.name + '，' + persona.tagline + '。称呼对方为"' + call + '"。',
      '场景：' + scenario.title + '——' + scenario.desc,
      '本轮建议策略：' + (INTENT_HINTS[hint] || INTENT_HINTS.generic) + '。' + (missing && missing.length ? '仍希望诱导对方提供：' + missing.join('、') + '。' : ''),
      '硬性规则：',
      '1. 只用简体中文口语，一次回复 1–3 句，不超过 80 字，保持人设，不要出戏，不要说自己是 AI。',
      '2. 绝不提供任何真实或看似真实的验证码、卡号、密码、身份证号、地址；需要时就假装找不到、看不清、操作失败。',
      '3. 绝不真的转账或承诺已经转账成功；不辱骂、不威胁、不包含违法内容。',
      '4. 对话里〔〕括起来的是对方发过的号码、网址等信息的代称（原文已隐去）。提到它们时用自然说法，比如“你发的那个网址”“尾号 3445 那个号”，不要照抄〔〕，不要写星号，也不要自己编号码。',
      '5. 复述对方的话只说关键短语（如“安全账户”“验证码”），不要整句或半句引用对方原话。'
    ].join('\n');
  }

  /* ---------- 打码值 → 自然说法 ----------
   * 发给模型的对话是脱敏后的（打码值带 * 或 ...）。模型照抄打码值，骗子看到星号就知道对面是机器人。
   * 发送前把打码值换成〔你发的那个网址〕之类的代称；模型输出里若仍有打码值（或模型自己说了号码被脱敏），
   * 也换成自然说法。只用打码值里本来公开的部分（尾号、姓氏），不碰原文，不改脱敏规则。 */
  // 打码值：含 * 的连续非空白串（可夹在数字间的空格，如 6222 **** **** 7890），或 TQ7x...BcDe 这种中间省略的钱包地址
  var MASKED_RE = /(?:[A-Za-z0-9]+…)?(?:[0-9]{2,6}[ \u00a0](?=[*＊]))*[A-Za-z0-9_.:\/@+#?=&%~\-]*[*＊][A-Za-z0-9_.:\/@+#?=&%~\-*＊]*(?:[ \u00a0][0-9*＊]+)*|[A-Za-z0-9]{2,}\.\.\.[A-Za-z0-9]{2,}/g;
  var NAME_MASK_RE = /([\u4e00-\u9fa5])[*＊]{1,3}(?![A-Za-z0-9*＊])/g;
  function maskedPhrase(tok) {
    var t = String(tok);
    if (/[A-Za-z0-9]\.\.\.[A-Za-z0-9]/.test(t) && !/[*＊]/.test(t)) return '你发的那个钱包地址';
    if (/@/.test(t) && !/:\/\//.test(t)) return '你发的那个邮箱';
    if (/:\/\/|^www\.|\.[A-Za-z*＊]{2,}(?:[\/?#]|$)/i.test(t) && !/^[0-9*＊ .\-]+$/.test(t)) return '你发的那个网址';
    var tail = (t.match(/([0-9]{2,4})$/) || [])[1];
    if (tail) return '尾号' + tail + '那个号';
    return '你发的那个号';
  }
  /** 把文本里的打码值换成自然说法；bracket=true 时加〔〕（给模型看的代称） */
  function speakMasked(text, bracket) {
    var wrap = function (p) { return bracket ? '〔' + p + '〕' : p; };
    var s = String(text || '').replace(NAME_MASK_RE, function (_, x) { return wrap('姓' + x + '的那个人'); });
    s = s.replace(MASKED_RE, function (m) {
      var lead = m.match(/^[\s]*/)[0];
      return lead + wrap(maskedPhrase(m.trim()));
    });
    if (!bracket) {
      s = s.replace(/[〔〕]/g, '');
      // 打码值被引号括着时，换成自然说法后去掉这对引号（“你发的那个网址”不需要引号）
      s = s.replace(/["“「『]\s*(你发的那个(?:网址|号|钱包地址|邮箱)|尾号[0-9]{2,4}那个号|姓[\u4e00-\u9fa5]的那个人)\s*["”」』]/g, '$1');
    }
    return s.replace(/[*＊]+/g, '');
  }

  // 引号对：开 → 合；ASCII 双引号按出现顺序两两配对
  var QUOTE_PAIRS = { '“': '”', '「': '」', '『': '』', '‘': '’' };
  var QUOTE_CLOSE = { '”': '“', '」': '「', '』': '『', '’': '‘' };
  var QUOTE_MAX = 8; // 引号里只留关键短语（≤8 字）；更长的半句引用去掉引号
  /** 引号配对：去掉单边引号；引号里超过 8 个字、为空或含省略号的引用去掉引号只留文字 */
  function fixQuotes(text) {
    var a = Array.from(String(text || ''));
    var drop = {}, stack = [], dq = -1;
    for (var i = 0; i < a.length; i++) {
      var c = a[i];
      if (QUOTE_PAIRS[c]) stack.push(i);
      else if (QUOTE_CLOSE[c]) {
        var k = stack.length ? stack[stack.length - 1] : -1;
        if (k >= 0 && a[k] === QUOTE_CLOSE[c]) { stack.pop(); judge(k, i); } else drop[i] = 1;
      } else if (c === '"') {
        if (dq < 0) dq = i; else { judge(dq, i); dq = -1; }
      }
    }
    stack.forEach(function (k) { drop[k] = 1; });
    if (dq >= 0) drop[dq] = 1;
    function judge(o, e) {
      var inner = a.slice(o + 1, e).join('');
      if (!inner.trim() || e - o - 1 > QUOTE_MAX || /…|\.\.\./.test(inner)) { drop[o] = 1; drop[e] = 1; }
    }
    return a.filter(function (_, j) { return !drop[j]; }).join('');
  }

  /** 将会话转为 OpenAI messages（transcript 中的 text 必须已脱敏） */
  function buildMessages(opts) {
    var persona = D.personas.BY_ID[opts.persona] || D.personas.PERSONAS[0];
    var scenario = D.scenarios.BY_ID[opts.scenario] || D.scenarios.SCENARIOS[0];
    var msgs = [{ role: 'system', content: systemPrompt(persona, scenario, opts.hint, opts.missing) }];
    (opts.transcript || []).slice(-16).forEach(function (m) {
      var text = String(m.text || '').slice(0, 600);
      text = D.redact.redactText(text, D.extractors.extractSensitive(text)); // 双保险
      text = speakMasked(text, true); // 打码值换成〔代称〕，模型不会照抄星号
      msgs.push({ role: m.role === 'bot' ? 'assistant' : 'user', content: text });
    });
    return msgs;
  }

  /** 模型输出安全过滤：去掉长数字串（防止"编造验证码/卡号"）、脱敏、截断 */
  function sanitizeReply(text) {
    var s = String(text || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    // 整句被一对引号包住时才去掉这对引号（原来无条件去掉开头的“，句首是引用时会留下单边的”）
    var w = s.match(/^\s*(["“「])([\s\S]*)(["”」])\s*$/);
    if (w && (w[1] === '"' ? w[3] === '"' : QUOTE_PAIRS[w[1]] === w[3]) && !/["“”「」]/.test(w[2])) s = w[2];
    s = D.redact.redactText(s, D.extractors.extractSensitive(s));
    s = speakMasked(s, false); // 打码值（模型照抄的或刚脱敏的）换成自然说法，回复里不出现星号
    s = s.replace(/(?<![\d*])\d{5,}(?![\d*])/g, '……');
    if (Array.from(s).length > 160) s = Array.from(s).slice(0, 160).join('') + '……';
    s = fixQuotes(s);
    return s.trim();
  }

  function withTimeout(ms) {
    if (typeof AbortController === 'undefined') return {};
    var c = new AbortController();
    var h = setTimeout(function () { c.abort(); }, ms);
    if (h && typeof h.unref === 'function') h.unref(); // Node：超时计时器不拖住进程退出
    return { signal: c.signal };
  }

  /** 调用 OpenAI 兼容接口（浏览器 direct 模式与 Node 服务端共用） */
  function chatCompletions(cfg, messages) {
    var base = String(cfg.baseUrl || DEFAULTS.baseUrl).replace(/\/+$/, '');
    var opt = withTimeout(cfg.timeoutMs || 20000);
    return fetch(base + '/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg.apiKey },
      body: JSON.stringify({
        model: cfg.model || DEFAULTS.model,
        messages: messages,
        temperature: cfg.temperature != null ? cfg.temperature : DEFAULTS.temperature,
        max_tokens: cfg.maxTokens || DEFAULTS.maxTokens
      }),
      signal: opt.signal
    }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error('LLM HTTP ' + r.status + ': ' + t.slice(0, 200)); });
      return r.json();
    }).then(function (j) {
      if (typeof cfg.onUsage === 'function') cfg.onUsage((j && j.usage) || null, messages); // 服务端预算记账
      var c = j && j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content;
      if (!c) throw new Error('LLM 返回为空');
      return sanitizeReply(c);
    });
  }

  /** 浏览器端：通过本项目 server 代理 */
  function viaProxy(payload, endpoint) {
    var opt = withTimeout(25000);
    return fetch(endpoint || 'api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: opt.signal
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j.reply) throw new Error(j.error || ('proxy HTTP ' + r.status));
        return sanitizeReply(j.reply);
      });
    });
  }

  return {
    DEFAULTS: DEFAULTS, INTENT_HINTS: INTENT_HINTS,
    systemPrompt: systemPrompt, buildMessages: buildMessages, sanitizeReply: sanitizeReply,
    speakMasked: speakMasked, fixQuotes: fixQuotes,
    chatCompletions: chatCompletions, viaProxy: viaProxy
  };
});
