'use strict';
// #173（含 #181）：对方没报过的号码、户名，人设提示词里不出现“那个号”“那个名字”，也不加〔〕代称条款。
// #172：逐字解释整段打成纯星号（「弓长张，****」「伟是****」）念成“那个名字”，打码号码仍念“那个号”。
// 用例 tests/fixtures/unsaid_refs.json 与 python/tests/test_unsaid_refs.py、voice/tests/test_unsaid_refs.py 共用；
// #172 用 tests/fixtures/redact.json 的 charExplain，Python 端 deepsuck.refs 逐字一致。
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../site/assets/js/llm.js');
const P = require('../site/assets/js/personas.js');
const E = require('../site/assets/js/engine.js');
const F = require('./fixtures/unsaid_refs.json');
const RX = require('./fixtures/redact.json');

const FORBID = { 那个号: 'number', 那个名字: 'name' };
const forbidden = (sp, refs) => Object.keys(FORBID).filter((w) => !refs.includes(FORBID[w]) && sp.includes(w));

test('三端共用：对方报过的代称种类', () => {
  for (const c of F.cases) assert.deepEqual(Object.keys(L.heardRefs(c.heard)).sort(), c.refs.slice().sort(), c.id);
});

test('离线提示词：对方没报过号码 / 户名时不出现“那个号”“那个名字”，没报过任何代称时不加代称条款', () => {
  for (const c of F.cases) {
    for (const hint of F.hints) {
      const msgs = L.buildMessages({ persona: c.persona, scenario: 'police', hint, missing: c.goals,
        transcript: c.heard.map((t) => ({ role: 'scammer', text: t })) });
      const sp = msgs[0].content;
      assert.deepEqual(forbidden(sp, c.refs), [], c.id + ' / ' + hint + '\n' + sp);
      assert.ok(sp.includes(P.UNSAID_REFS.rule), c.id);
      if (!c.refs.length) assert.ok(!/〔|括起来/.test(sp), c.id + ' / ' + hint);
      else for (const k of c.refs) assert.ok(sp.includes('〔' + P.UNSAID_REFS.phrase[k] + '〕'), c.id + ' ' + k);
      assert.ok(!/对方已经提到、但还没说清楚/.test(sp), sp); // 原来这句让模型以为对方报过户名
    }
  }
});

test('代称条款只举出现过的那种说法，不写死“那个号”', () => {
  const sp = L.systemPrompt(P.BY_ID.lin, null, 'generic', [], ['点这个链接 bi***tc.top 按提示操作。']);
  assert.ok(sp.includes('〔你发的那个网址〕') && !sp.includes('那个号') && !sp.includes('那个名字'), sp);
});

test('姓名规则：报过名字时是原句，没报过时去掉举的说法', () => {
  const on = L.systemPrompt(P.BY_ID.wang, null, 'generic', [], ['收款人是张**，你先记一下。']);
  assert.ok(on.includes(P.NAME_RULE), on);
  const off = L.systemPrompt(P.BY_ID.wang, null, 'generic', [], ['你把钱转到国家安全账户']);
  assert.ok(off.includes('不复述对方说的任何人名（只说了姓的、打了星号的也算）。') && !off.includes('户名没记全'), off);
});

test('dropUnheard 去掉没报过的说法后标点通顺', () => {
  assert.equal(L.dropUnheard(P.NAME_RULE, {}), '不复述对方说的任何人名（只说了姓的、打了星号的也算）。');
  assert.equal(L.dropUnheard('都算；要提就说“你说的那个号”“那张卡”，最多含糊地说“好像是…开头的”', {}), '都算；最多含糊地说“好像是…开头的”');
  const ci = L.dropUnheard(P.INTENT_HINTS.confirm_intel, { url: 1 });
  assert.ok(ci.includes('只说姓氏或“你发的那个网址”') && !/那个号|那个名字|那张卡|[、或]；|，；/.test(ci), ci);
  for (const k of Object.keys(P.INTENT_HINTS)) if (k !== 'confirm_intel') assert.equal(L.dropUnheard(P.INTENT_HINTS[k], {}), P.INTENT_HINTS[k], k);
});

test('#172：charExplain 打码结果一律念“那个名字”，不念“那个号”', () => {
  const cases = RX.charExplain.filter((c) => c.expect === 'mask' && !c.xfail).map((c) => c.redacted).concat(['伟是****', '伟字是****', '就是****', '伟，****']);
  for (const t of cases) {
    for (const out of [L.speakMasked(t, false), L.sanitizeReply(t)]) {
      assert.ok(out.includes('那个名字') && !out.includes('那个号') && !/[*＊]/.test(out), t + ' → ' + out);
    }
  }
});

test('#172：打码号码仍念“那个号”', () => {
  for (const t of ['138****5678', '卡号 6222 **** **** 7890', '转到622202*********3445', '验证码是******', '尾号 ****']) {
    const out = L.speakMasked(t, false);
    assert.ok(out.includes('那个号') && !out.includes('那个名字'), t + ' → ' + out);
  }
});

test('规则引擎：对方没报号时回复里没有“那个号”“那个名字”', () => {
  for (const c of F.cases.filter((x) => !x.refs.length)) {
    for (let seed = 0; seed < 8; seed++) {
      let n = seed;
      const s = new E.Session({ scenario: 'police', persona: c.persona, rng: () => { n = (n * 9301 + 49297) % 233280; return n / 233280; }, now: () => 0 });
      for (const t of c.heard) {
        const text = s.ruleReply(s.ingest(t)).text;
        assert.deepEqual(forbidden(text, []), [], c.id + ' → ' + text);
      }
    }
  }
});
