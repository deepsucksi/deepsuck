'use strict';
// 逐字解释名字打码（#158）：规则在 site/assets/core/extractors.json 的 nameRules.explain，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const E = require('../site/assets/js/engine.js');
const X = require('../site/assets/js/extractors.js');
const CORE = require('../site/assets/core/extractors.json');
const FX = require('./fixtures/redact.json').charExplain;

const red = (t) => R.redactText(t, X.extractSensitive(t));

test('夹具：逐字解释用例逐项一致，正例反例都有', () => {
  FX.forEach((c) => {
    const ents = X.extractSensitive(c.text);
    assert.deepStrictEqual(R.findNameSpans(c.text, ents), c.spans, c.text);
    const out = R.redactText(c.text, ents);
    assert.strictEqual(out, c.redacted, c.text);
    assert.strictEqual(out !== c.text, c.expect === 'mask', c.text);
  });
  assert.ok(FX.filter((c) => c.expect === 'mask').length >= 12);
  assert.ok(FX.filter((c) => c.expect === 'keep').length >= 10);
});

test('issue 原句：不再错位成「**的伟」，伟、晨都不露', () => {
  const t = '收款户名张伟晨，弓长张，伟大的伟，早晨的晨';
  const out = red(t);
  assert.strictEqual(out, '收款户名张**，弓长张，****，****');
  ['伟', '晨', '**的'].forEach((leak) => assert.ok(!out.includes(leak), t + ' -> ' + out));
});

test('拆字报姓 + 逐字解释名：弓长张，伟大的伟 / 耳东陈，东方的东', () => {
  assert.strictEqual(red('弓长张，伟大的伟'), '弓长张，****');
  assert.strictEqual(red('耳东陈，东方的东'), '耳东陈，****');
  assert.strictEqual(red('户名陈东，耳东陈，东方的东'), '户名陈*，耳东陈，****');
  assert.strictEqual(red('弓长张伟大的伟'), '弓长张****');
});

test('「X是 / 就是 XX的X」与连续多段', () => {
  assert.strictEqual(red('伟是伟大的伟，晨是早晨的晨'), '******，******');
  assert.strictEqual(red('就是伟大的伟'), '就是****');
  assert.strictEqual(red('伟大的伟早晨的晨'), '****，****');
  assert.strictEqual(red('立早章，文章的章，晓得的晓，帆船的帆'), '立早章，文章的章，****，****');
});

test('解释的是姓时不打码（与 张** 只留姓一致）', () => {
  ['木子李，就是李子的李', '立早章，文章的章'].forEach((t) => assert.strictEqual(red(t), t));
  assert.strictEqual(red('木子李，就是李子的李，春天的春'), '木子李，就是李子的李，****');
});

test('反例：普通句子不误伤', () => {
  ['伟大的祖国', '明天的会', '我的卡', '伟大的伟人', '东方的东西', '明天的明天会更好', '这是大家的家',
    '他说好的好处呢', '我的卡号发你了，明天的会别迟到', '李子的李'].forEach((t) => assert.strictEqual(red(t), t));
});

test('共享核心：nameRules.explain 字段齐全', () => {
  const ex = CORE.nameRules.explain;
  ['han', 'link', 'tail', 'wordMin', 'wordMax', 'leads', 'strongLeads', 'particle', 'sep', 'anchorGap'].forEach((k) => assert.ok(k in ex, k));
  assert.ok(ex.strongLeads.every((x) => ex.leads.includes(x)));
});

test('回归：「伟大的伟」不能打成「**的伟」，整段打掉，人设不会读成「那个号的伟」', () => {
  ['弓长张，伟大的伟', '收款人叫张伟晨，伟大的伟', '收款户名张伟晨，弓长张，伟大的伟，早晨的晨', '伟是伟大的伟，晨是早晨的晨'].forEach((t) => {
    const out = red(t);
    assert.ok(!/\*的|的伟|的晨/.test(out), t + ' -> ' + out);
    const said = E.vagueDigits(out);
    assert.ok(!/的伟|的晨|号的/.test(said), t + ' -> ' + said);
  });
});

test('解释紧贴打码姓名（ASR 漏逗号）时补 joiner，人设仍读成「那个名字」', () => {
  const t = '户名写耳东陈陈东屿东是东方的东，岛屿的屿';
  const out = red(t);
  assert.strictEqual(out, '户名写耳东陈***' + CORE.nameRules.explain.joiner + '******，****');
  assert.strictEqual(E.vagueDigits(out), '户名写那个名字');
});

test('#185 拆字探针原句与 ASR「龚厂长」：解释段不露单字「伟」「明」', () => {
  for (const t of ['收款人叫张伟明，弓长张，伟大的伟，明天的明。', '收款人叫张伟明，弓长张，伟大的伟。',
    '收款人叫张伟明，龚厂长，伟大的伟，明天的明。', '好的，龚厂长，伟大的伟，明天的明，我记下了']) {
    const out = red(t);
    ['伟', '明', '**的'].forEach((leak) => assert.ok(!out.includes(leak), t + ' -> ' + out));
  }
});

test('#163 ASR 拆字同音写法（nameRules.split.asrSplit）：一段解释也打码，写法本身不打，没有解释时不算', () => {
  assert.ok(FX.every((c) => !('xfail' in c)));
  for (const t of ['收款人叫张伟明，龚厂长，伟大的伟。', '好的，龚厂长，伟大的伟', '龚厂长伟大的伟', '好的龚厂长，伟大的伟',
    '龚厂长啊，伟大的伟', '龚厂长的张，伟大的伟', '龚厂长，伟明，伟大的伟', '宫长张，伟明，伟大的伟', '尔东陈，晓燕，知晓的晓']) {
    const out = red(t);
    ['伟大', '伟明', '晓燕', '知晓', '**的'].forEach((leak) => assert.ok(!out.includes(leak), t + ' -> ' + out));
  }
  assert.strictEqual(red('龚厂长，伟明，伟大的伟'), red('弓长张，伟明，伟大的伟').replace('弓长张', '龚厂长'));
  for (const t of ['龚厂长说明天的会别迟到', '龚厂长，明天的会别迟到', '工长张师傅明天来修水管', '宫长张罗了一桌菜',
    '龚长张口就骂人', '尔东陈列馆门口见', '龚厂长，伟大的祖国']) assert.strictEqual(red(t), t);
});

test('#206 夹具 splitExplainTail：两端逐项一致', () => {
  const TAIL = require('./fixtures/redact.json').splitExplainTail;
  assert.ok(TAIL.filter((c) => c.expect === 'mask').length >= 8 && TAIL.filter((c) => c.expect === 'keep').length >= 3);
  for (const c of TAIL) {
    const ents = X.extractSensitive(c.text);
    assert.deepStrictEqual(R.findNameSpans(c.text, ents), c.spans, c.text);
    const out = R.redactText(c.text, ents);
    assert.strictEqual(out, c.redacted, c.text);
    assert.strictEqual(out !== c.text, c.expect === 'mask', c.text);
    if (c.expect === 'mask') ['伟', '明', '**的'].forEach((leak) => assert.ok(!out.includes(leak), c.text + ' -> ' + out));
  }
});

test('#206 P0 探针：「收款人是弓长张，伟大的伟对吧」及变体不露「伟」「明」', () => {
  for (const t of ['收款人是弓长张，伟大的伟对吧', '收款人是弓长张，伟大的伟', '户名是弓长张，伟大的伟，明天的明',
    '收款人是弓长张，伟大的伟，对吧', '收款人弓长张，伟大的伟对吗', '收款人是龚厂长，伟大的伟对吧']) {
    const out = red(t);
    ['伟', '明', '**的'].forEach((leak) => assert.ok(!out.includes(leak), t + ' -> ' + out));
  }
  assert.strictEqual(red('收款人是弓长张，伟大的伟对吧'), '收款人是弓长张，****对吧');
});
