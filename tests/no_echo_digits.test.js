'use strict';
// #121：网页端回复发出前的数字过滤（engine.vagueDigits，recordBot 里调用），与 python/deepsuck/engine.py 的 vague_digits 一致。
const test = require('node:test');
const assert = require('node:assert');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const E = require('../site/assets/js/engine.js');
const L = require('../site/assets/js/llm.js');
const P = require('../site/assets/js/personas.js');
const S = require('../site/assets/js/scenarios.js');

const PROBES = ['嗯…验证码是472？', '6222开头…尾号0123对吧', '138开头…后面是零零幺三'];
const ECHO = /[0-9０-９零〇一幺二两三四五六七八九](?:[\s、,，\-*＊]{0,2}[0-9０-９零〇一幺二两三四五六七八九])+/g;
const echoes = (t) => String(t).match(ECHO) || [];

test('三句探针过滤后只剩含糊说法', () => {
  assert.deepEqual(PROBES.map(E.vagueDigits), ['嗯…验证码是那几个数没听清？', '好像是6开头的…后面几位没听清对吧', '好像是1开头的…后面几位没听清']);
});

test('各种写法的数字串都换掉，单个两个数字不动', () => {
  for (const t of ['验证码 4 7 2 9', '一三八 零零 幺三', '6二22开头的', '卡号 6222 **** **** 7890', '尾号 ****7890', '130****8600？尾号是8600？', '末尾０１２３', '我转了2000块']) {
    assert.deepEqual(echoes(E.vagueDigits(t)), [], t + ' → ' + E.vagueDigits(t));
  }
  for (const t of ['好像是6开头的', '分期是12期还是24期？', '两三百块', '等我一下']) assert.equal(E.vagueDigits(t), t);
});

test('与 Python 版逐字一致', () => {
  const cases = PROBES.concat(['验证码 4 7 2 9', '一三八 零零 幺三', '卡号 6222 **** **** 7890', '尾号是8600？', '我转了2000块', '138-0013', '好像是6开头的']);
  const py = execFileSync('python3', ['-c', 'import json,sys; from deepsuck.engine import vague_digits as v; print(json.dumps([v(t) for t in json.load(sys.stdin)], ensure_ascii=False))'],
    { cwd: path.join(__dirname, '..', 'python'), input: JSON.stringify(cases) }).toString();
  assert.deepEqual(cases.map(E.vagueDigits), JSON.parse(py));
});

test('recordBot：规则和大模型的回复都过滤', () => {
  const s = new E.Session({ scenario: 'police', persona: 'wang', rng: () => 0.3, now: () => 0 });
  for (const t of PROBES) assert.deepEqual(echoes(s.recordBot(t, 'coop_step').text), []);
});

test('复述情报不带任何数字', () => {
  for (const r of [0, 0.5, 0.99]) {
    const s = new E.Session({ scenario: 'refund', persona: 'lin', rng: () => r, now: () => 0 });
    const said = s.speakIntel({ type: 'bank_card', label: '银行卡号', masked: '622202*********3445', raw: '6222020200112233445' });
    assert.ok(!/[0-9]/.test(said), said);
  }
});

test('提示词：不复述数字，也不给号码举例', () => {
  const sp = L.systemPrompt(P.BY_ID.wang, S.BY_ID.police, 'coop_step', []);
  assert.ok(/不说任何数字串/.test(sp) && !/尾号 ?[0-9]/.test(sp), sp);
  assert.ok(!/后四位|报错一位/.test(P.INTENT_HINTS.confirm_intel));
  assert.equal(L.sanitizeReply('转到 621700*********0123'), '转到 你发的那个号');
});
