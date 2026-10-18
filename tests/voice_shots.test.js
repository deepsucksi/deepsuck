'use strict';
// 语音线少样本例句（personas.json 人设下的 voiceShots / voiceStyle）：结构与口语化约束。
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../site/assets/core/personas.json');
const S = require('../site/assets/core/scenarios.json');

const BOOKISH = /订单|正规|专员|核实|确认|平台|操作|流程/;
const BANNED = /[!！]|哎哟|哎呀|老花|孙子|耳朵|耳背|听不清|大点声|岁|年纪|一把年纪/;
const MAIN = ['refund', 'police', 'task', 'pig', 'loan'];
// 王阿姨是已批准的质量线；小陈妈妈、郑老板照同一标准写（#11）。有 voiceShots 的人设都按这套约束检查。
const REQUIRED = ['wang', 'chen', 'zheng'];
const withShots = () => C.personas.filter((p) => p.voiceShots !== undefined);

test('voiceShots：王阿姨、小陈妈妈、郑老板必有；每项是骗子一句加人设一句，场景合法', () => {
  for (const id of REQUIRED) {
    const p = C.personas.find((x) => x.id === id);
    assert.ok(Array.isArray(p.voiceShots) && p.voiceShots.length, id + '.voiceShots');
  }
  const ids = new Set(S.scenarios.map((s) => s.id));
  for (const p of C.personas) {
    if (p.voiceShots === undefined) continue;
    for (const it of p.voiceShots) {
      assert.equal(typeof it.scammer, 'string'); assert.ok(it.scammer.trim());
      assert.equal(typeof it.reply, 'string'); assert.ok(it.reply.trim());
      if (it.scenario !== undefined) assert.ok(ids.has(it.scenario), it.scenario);
    }
  }
  for (const p of withShots()) for (const sc of MAIN) {
    const n = p.voiceShots.filter((x) => x.scenario === sc).length;
    assert.ok(n >= 3 && n <= 5, `${p.id} ${sc}: ${n}`);
  }
});

test('voiceShots：回话短、口语、不用书面词，不提年龄/小道具/感叹号，不编号码（每个有 voiceShots 的人设）', () => {
  for (const wang of withShots()) {
  for (const { reply } of wang.voiceShots) {
    assert.ok(reply.replace(/[，。？…、\s]/g, '').length <= 24, reply);
    assert.ok(!BOOKISH.test(reply), '书面词：' + reply);
    assert.ok(!BANNED.test(reply), reply);
    assert.ok(!/\d{3,}|[*＊]/.test(reply), reply);
  }
  const n = wang.voiceShots.length;
  assert.ok(wang.voiceShots.filter((x) => /？/.test(x.reply)).length >= n * 0.6, '多反问');
  const broken = wang.voiceShots.filter((x) => /…/.test(x.reply)).length;
  assert.ok(broken >= n * 0.3 && broken <= n * 0.75, `约一半带断续（…）：${broken}/${n}`);
  assert.ok(Array.isArray(wang.voiceStyle) && wang.voiceStyle.every((r) => typeof r === 'string' && !/[!！]/.test(r)));
  const rules = wang.voiceStyle.join('');
  for (const k of ['短句', '断断续续', '…', '反问', '不主动总结', '不替对方', '不提年龄', '不编小道具', '不用感叹号']) assert.ok(rules.includes(k), wang.id + ' ' + k);
  }
});
