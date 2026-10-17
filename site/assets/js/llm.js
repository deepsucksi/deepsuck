/*!
 * DeepSuck — llm.js
 * 可选的大模型引擎（默认关闭）。兼容 OpenAI Chat Completions 协议，默认指向阿里云百炼 DashScope：
 *   https://dashscope.aliyuncs.com/compatible-mode/v1  （模型 qwen-plus）
 * 两种接入方式：
 *   1) proxy  —— 推荐。浏览器调用本项目自带的 server（/api/chat），API Key 只保存在服务器 .env 中；
 *   2) direct —— 浏览器直连（Key 存在本机浏览器，仅适合本地自用；部分服务商不支持跨域）。
 * 隐私：发送给大模型的对话记录在本地已脱敏；模型输出也会再经过安全过滤与脱敏。
 * 任何失败都会自动回退到规则引擎。
 * Apache-2.0 · 非官方项目，与 DeepSeek 无关
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

  var INTENT_HINTS = {
    opening: '自然开场，表现出好奇或困惑',
    ask_repeat: '假装没听清，请对方重复',
    misunderstand: '故意误解对方意思',
    tech_trouble: '假装手机/网络出了技术故障',
    slow_walk: '找借口拖延（去拿东西、做家务等）',
    otp_stall: '假装找不到/念错验证码，绝不给出任何真实或看似真实的验证码',
    elicit_account: '假装愿意配合，请对方把收款卡号、户名、开户行写清楚',
    elicit_wallet: '请对方发送钱包地址和链类型',
    elicit_contact: '请对方留下电话/微信/QQ',
    elicit_url: '请对方发送下载链接或网址',
    confirm_intel: '复述刚拿到的信息（只能用已打码的形式），并追问下一项信息',
    fake_progress: '假装正在转账但遇到各种阻碍',
    scared: '表现害怕、慌张，但并不真的照做',
    secrecy: '答应保密但话里透着犹豫',
    greedy: '表现心动，追问平台名称与操作细节',
    romance: '礼貌回应示好，把话题引向对方身份与平台',
    info_stall: '找借口不提供个人信息',
    urgency_stall: '表示自己慢，不要催',
    generic: '附和并让对方继续说',
    verify_identity: '对自称熟人/领导的对方提出只有真熟人才知道的问题，或坚持要电话/当面核实',
    task_stall: '假装笨手笨脚地做任务、纠结小额佣金，追问平台名称与收款账户，绝不真正垫付',
    loan_stall: '对"先交钱后放款""刷流水"表示困惑，追问机构名称、资质与收款账户',
    campus_stall: '假装搞不清各种网贷平台和额度，拖延并追问对方所谓的"核查账户"'
  };

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
      '4. 对话中出现的 * 号或 ... 是已脱敏的信息，复述时保持打码形式。'
    ].join('\n');
  }

  /** 将会话转为 OpenAI messages（transcript 中的 text 必须已脱敏） */
  function buildMessages(opts) {
    var persona = D.personas.BY_ID[opts.persona] || D.personas.PERSONAS[0];
    var scenario = D.scenarios.BY_ID[opts.scenario] || D.scenarios.SCENARIOS[0];
    var msgs = [{ role: 'system', content: systemPrompt(persona, scenario, opts.hint, opts.missing) }];
    (opts.transcript || []).slice(-16).forEach(function (m) {
      var text = String(m.text || '').slice(0, 600);
      text = D.redact.redactText(text, D.extractors.extractSensitive(text)); // 双保险
      msgs.push({ role: m.role === 'bot' ? 'assistant' : 'user', content: text });
    });
    return msgs;
  }

  /** 模型输出安全过滤：去掉长数字串（防止"编造验证码/卡号"）、脱敏、截断 */
  function sanitizeReply(text) {
    var s = String(text || '').replace(/^["“\s]+|["”\s]+$/g, '');
    s = s.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    s = D.redact.redactText(s, D.extractors.extractSensitive(s));
    s = s.replace(/(?<![\d*])\d{5,}(?![\d*])/g, '……');
    if (s.length > 160) s = s.slice(0, 160) + '……';
    return s;
  }

  function withTimeout(ms) {
    if (typeof AbortController === 'undefined') return {};
    var c = new AbortController();
    setTimeout(function () { c.abort(); }, ms);
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
    chatCompletions: chatCompletions, viaProxy: viaProxy
  };
});
