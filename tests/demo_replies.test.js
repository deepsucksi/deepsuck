'use strict';
// 演示页回复回归：线上 demo（冒充客服·退款理赔、王阿姨、样例 1–3）第 3 条回复出现打码星号和单边引号。
// 根因：在线服务可用时演示页自动切到大模型；发给模型的对话是脱敏后的（网址带 *），提示词还要求“复述时保持打码形式”，
// 模型照抄了打码网址；sanitizeReply 又无条件去掉句首的“，留下单边的”。
const test = require('node:test');
const assert = require('node:assert/strict');
const E = require('../site/assets/js/engine.js');
const S = require('../site/assets/js/scenarios.js');
const P = require('../site/assets/js/personas.js');
const L = require('../site/assets/js/llm.js');
const H = require('../site/assets/js/humanize.js');
const SCRIPTS = require('../site/assets/core/scam_scripts.json');

const OPEN = { '“': '”', '「': '」', '『': '』', '‘': '’' };
const CLOSE = { '”': '“', '」': '「', '』': '『', '’': '‘' };
function quotesPaired(t) {
  const st = [];
  for (const c of Array.from(t)) {
    if (OPEN[c]) st.push(c);
    else if (CLOSE[c] && st.pop() !== CLOSE[c]) return false;
  }
  return !st.length && (t.match(/"/g) || []).length % 2 === 0;
}
function clean(t, where) {
  assert.ok(!/[*＊]/.test(t), `${where} 回复带打码星号: ${t}`);
  assert.ok(quotesPaired(t), `${where} 引号不配对: ${t}`);
}

test('演示复现场景（退款理赔 · 王阿姨 · 样例 1–3）：规则引擎回复无星号、引号配对', () => {
  const sc = S.BY_ID.refund;
  for (let seed = 1; seed <= 200; seed++) {
    const s = new E.Session({ scenario: 'refund', persona: 'wang', rng: H.mulberry32(seed) });
    clean(s.opening().text, 'opening');
    for (let i = 0; i < 3; i++) clean(s.ruleReply(s.ingest(sc.samples[i])).text, `seed ${seed} 样例 ${i + 1}`);
  }
});

test('演示复现场景走大模型路径（假模型照抄打码值）：发给模型的消息无星号，回复无星号、引号配对', async () => {
  const sc = S.BY_ID.refund;
  const realFetch = global.fetch;
  const sent = [];
  // 假模型：像线上那样照抄上一条骗子消息里的打码网址，句首带引用
  global.fetch = async (url, opt) => {
    const body = JSON.parse(opt.body);
    sent.push(body.messages);
    const last = body.messages[body.messages.length - 1].content;
    const m = last.match(/〔[^〕]+〕|https?:\/\/\S+/);
    const echo = m ? m[0] : 're…f***.example/***';
    const reply = `“安心退”？……只看清是"${echo}"——小伙子，你再念一遍后头那串？`;
    return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: reply } }] }) };
  };
  try {
    const s = new E.Session({ scenario: 'refund', persona: 'wang', rng: H.mulberry32(1) });
    s.opening();
    for (let i = 0; i < 3; i++) {
      const a = s.ingest(sc.samples[i]);
      const payload = { persona: 'wang', scenario: 'refund', hint: s.chooseIntent(a), missing: s.missingGoals(),
        transcript: s.messages.map((m) => ({ role: m.role, text: m.text })) };
      const reply = await L.chatCompletions({ baseUrl: 'http://fake', model: 'fake', apiKey: 'x' }, L.buildMessages(payload));
      const msg = s.recordBot(reply, payload.hint);
      clean(msg.text, `大模型 样例 ${i + 1}`);
    }
    for (const msgs of sent) for (const m of msgs.slice(1)) assert.ok(!/[*＊]/.test(m.content), '发给模型的消息仍带星号: ' + m.content);
    assert.ok(sent[1].some((m) => m.content.includes('〔你发的那个网址〕')), '网址应换成代称');
    // 模型直接照抄线上那条回复（服务端已去掉句首“的情况也覆盖）
    const live = '“安心退”？……只看清是"re…f***.example/***"——小伙子，你再念一遍后头那串？';
    for (const r of [live, live.slice(1)]) {
      const out = L.sanitizeReply(r);
      clean(out, 'sanitizeReply');
      assert.ok(out.includes('你发的那个网址'), out);
      assert.equal(L.sanitizeReply(out), out, '幂等（浏览器端会对代理返回再过一遍）');
    }
  } finally { global.fetch = realFetch; }
});

test('sanitizeReply / speakMasked：各类打码值换成自然说法，长引用去引号、单边引号删除', () => {
  const cases = [
    ['转到 621700*********0123，户名李**', /尾号0123那个号.*姓李的那个人/],
    ['打 139****2233 或者 QQ 28******10', /尾号2233那个号.*尾号10那个号/],
    ['地址 TQ7x...BcDe 对吧', /你发的那个钱包地址/],
    ['卡号 6222 **** **** 7890', /尾号7890那个号/],
    ['网址 www.go***ip.example ，打不开', /你发的那个网址/],
    ['你说“把钱转到国家安全账户核查一下”是啥意思', /^你说把钱转到国家安全账户核查一下是啥意思$/],
    ['你说的“安全账户”在哪', /“安全账户”/],
    ['安心退”？是这个吗', /^安心退？是这个吗$/]
  ];
  for (const [inp, re] of cases) { const out = L.sanitizeReply(inp); clean(out, inp); assert.match(out, re, inp + ' → ' + out); }
  assert.ok(!/保持打码形式/.test(L.systemPrompt(P.BY_ID.wang, S.BY_ID.refund, 'generic', [])));
});

test('全场景 × 全人设扫规则引擎输出：无星号、无单边引号', () => {
  const corpus = (SCRIPTS.entries || []).map((e) => e.text);
  let n = 0;
  for (const sc of S.SCENARIOS) for (const p of P.PERSONAS) for (let seed = 1; seed <= 8; seed++) {
    const s = new E.Session({ scenario: sc.id, persona: p.id, rng: H.mulberry32(seed) });
    clean(s.opening().text, `${sc.id}/${p.id} opening`);
    const lines = sc.samples.concat(corpus.filter((_, i) => i % 8 === seed - 1).slice(0, 20));
    for (const l of lines) { clean(s.ruleReply(s.ingest(l)).text, `${sc.id}/${p.id}/${seed}`); n++; }
  }
  assert.ok(n > 1000, String(n));
});

test('遗留修复：小林无“反诈课 PPT”句；李大爷 confirm_intel 后不紧接着要电话', () => {
  const C = require('../site/assets/core/personas.json');
  const lin = C.personas.find((p) => p.id === 'lin');
  for (const v of Object.values(lin.templates)) for (const t of v) assert.ok(!/反诈课|PPT/.test(typeof t === 'string' ? t : t.t));
  const phoneAsk = P.BY_ID.li.asks.phone;
  let confirms = 0;
  for (const sc of S.SCENARIOS) for (let seed = 1; seed <= 30; seed++) {
    const s = new E.Session({ scenario: sc.id, persona: 'li', rng: H.mulberry32(seed) });
    s.opening();
    for (const l of sc.samples) {
      const r = s.ruleReply(s.ingest(l));
      if (r.intent === 'confirm_intel') { confirms++; assert.ok(!r.text.includes(phoneAsk), r.text); }
    }
  }
  assert.ok(confirms > 20, String(confirms));
});

test('小林：无“反诈专员”句；说完“我在找”（re_ask）的下一轮不接切屏说法；其他人设没有 afterReAskAvoid', () => {
  const C = require('../site/assets/core/personas.json');
  const lin = C.personas.find((p) => p.id === 'lin');
  for (const v of Object.values(lin.templates)) for (const t of v) assert.ok(!/反诈/.test(typeof t === 'string' ? t : t.t));
  for (const t of lin.templates.re_ask) assert.ok(!/切出去|切回|切到|切屏/.test(typeof t === 'string' ? t : t.t));
  assert.deepEqual(C.personas.filter((p) => p.afterReAskAvoid).map((p) => p.id), ['lin']);
  const CUT = new RegExp(lin.afterReAskAvoid);
  let after = 0;
  for (const sc of S.SCENARIOS) for (let seed = 1; seed <= 40; seed++) {
    const s = new E.Session({ scenario: sc.id, persona: 'lin', rng: H.mulberry32(seed) });
    s.opening();
    let prev = null;
    const lines = sc.samples.concat(['验证码发我', '快点操作', '你切回来看一下页面', '验证码收到没有', '额度多少你说']);
    for (const l of lines.concat(lines)) {
      const r = s.ruleReply(s.ingest(l));
      if (prev === 're_ask') { after++; assert.ok(!CUT.test(r.text), r.text); }
      prev = r.intent;
    }
  }
  assert.ok(after > 20, String(after));
});
