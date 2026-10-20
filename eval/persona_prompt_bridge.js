// #194：eval/llm_scammer.py --responder llm 用的提示词桥。按行读 JSON 请求、按行写 JSON 结果（不联网、不读 Key）。
//   node eval/persona_prompt_bridge.js <assets 目录>
// <assets 目录> 下是 js/ 和 core/（当前检出的 site/assets，或 git archive 从某个 ref 解出来的副本），
// 人设系统提示词、对话历史的代称替换都直接调用那份 llm.js（buildMessages / systemPrompt），不另写一份。
// 请求：{ op: 'web' | 'parts' | 'probe', persona, scenario, hint, missing, transcript }
//   web   → { messages }：与网页 buildMessages 完全相同（系统提示词每轮重算，历史只留最近 16 条）；
//   parts → { system, history }：本轮系统提示词（按行拆开）+ 全部历史（逐条过 buildMessages 的同一套代称替换，不截断）；
//   probe → { fixed }：本人设系统提示词里不随轮次变的行号（heard 给几段对方的话，几组差别很大的输入下逐行比较）。
'use strict';
const path = require('path');
const readline = require('readline');
const dir = path.resolve(process.argv[2] || path.join(__dirname, '../site/assets'));
const L = require(path.join(dir, 'js/llm.js'));
const P = require(path.join(dir, 'js/personas.js'));

function persona(id) {
  const rid = P.resolveId ? P.resolveId(id) : id;
  return P.BY_ID[rid] || P.PERSONAS[0];
}

function lines(o) {
  return L.systemPrompt(persona(o.persona), null, o.hint, o.missing || [], o.heard || []).split('\n');
}


function handle(o) {
  if (o.op === 'web') return { messages: L.buildMessages(o) };
  if (o.op === 'parts') {
    const heard = (o.transcript || []).filter((m) => m.role !== 'bot').map((m) => String(m.text || '').slice(0, 600));
    const sys = L.systemPrompt(persona(o.persona), null, o.hint, o.missing || [], heard);
    const history = (o.transcript || []).map((m) => L.buildMessages({ persona: o.persona, scenario: o.scenario, transcript: [m] })[1]);
    return { system: sys.split('\n'), history: history };
  }
  if (o.op === 'probe') {
    const RICH = o.heard || [];
    const goals = ['bank', 'name', 'url', 'wallet', 'phone'];
    const variants = [
      lines({ persona: o.persona, hint: 'generic', missing: [], heard: [] }),
      lines({ persona: o.persona, hint: 'confirm_intel', missing: goals, heard: RICH }),
      lines({ persona: o.persona, hint: 'elicit_account', missing: ['bank'], heard: RICH.slice(0, 1) }),
      lines({ persona: o.persona, hint: 'ask_repeat', missing: goals, heard: RICH.slice(1) })
    ];
    const n = Math.min.apply(null, variants.map((v) => v.length));
    const fixed = [];
    for (let i = 0; i < n; i++) if (variants.every((v) => v[i] === variants[0][i])) fixed.push(i);
    return { fixed: fixed, lines: variants[0].length };
  }
  throw new Error('unknown op ' + o.op);
}

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  if (!line.trim()) return;
  let out;
  try { out = { ok: true, result: handle(JSON.parse(line)) }; } catch (e) { out = { ok: false, error: String(e && e.message || e) }; }
  process.stdout.write(JSON.stringify(out) + '\n');
});
