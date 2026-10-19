'use strict';
// 拆字报姓打码（#139）：规则在 site/assets/core/extractors.json 的 nameRules.split，JS 与 Python 共用
const test = require('node:test');
const assert = require('node:assert');
const R = require('../site/assets/js/redact.js');
const X = require('../site/assets/js/extractors.js');
const CORE = require('../site/assets/core/extractors.json');
const SCRIPTS = require('../eval/scammer-scripts.json');
const FX = require('./fixtures/redact.json').splitName;

const red = (t) => R.redactText(t, X.extractSensitive(t));

test('夹具：拆字报姓用例逐项一致，两类都有', () => {
  FX.forEach((c) => {
    const ents = X.extractSensitive(c.text);
    assert.deepStrictEqual(R.findNameSpans(c.text, ents), c.spans, c.text);
    const out = R.redactText(c.text, ents);
    assert.strictEqual(out, c.redacted, c.text);
    assert.strictEqual(out !== c.text, c.expect === 'mask', c.text);
  });
  assert.ok(FX.filter((c) => c.expect === 'mask').length >= 8);
  assert.ok(FX.filter((c) => c.expect === 'keep').length >= 6);
});

test('探针原句：不留 张三丰 / 三丰 / 弓长张三丰', () => {
  ['收款户名张三丰，弓长张，三丰', '收款户名张三丰。弓长张三丰。'].forEach((t) => {
    const out = red(t);
    ['张三丰', '三丰', '弓长张三丰'].forEach((leak) => assert.ok(!out.includes(leak), t + ' -> ' + out));
  });
  assert.strictEqual(red('收款户名张三丰，弓长张，三丰'), '收款户名张**，弓长张，**');
  assert.strictEqual(red('收款户名张三丰。弓长张三丰。'), '收款户名张**。弓长张**。');
});

test('没有触发词的拆字报姓：木子李四、耳东陈小明', () => {
  assert.strictEqual(red('木子李四'), '木子李*');
  assert.strictEqual(red('耳东陈小明'), '耳东陈**');
  assert.strictEqual(red('户名木子李四'), '户名木子李*');
  assert.deepStrictEqual(X.extractSensitive('户名木子李四').filter((e) => e.type === 'name').map((e) => e.value), ['李四']);
});

test('反例：含「长」「木」的普通文本、三丰路营业厅、弓长岭不打码', () => {
  ['他的成长很快，木头桌子，长木凳', '长期有效，木材加工厂', '弓长张，你好', '木子李，就是李子的李',
    '三丰路营业厅', '弓长岭', '去弓长岭的三丰路营业厅'].forEach((t) => assert.strictEqual(red(t), t));
});

test('单独出现的名不归静态规则管（交给按通话打码）；电话规则不变', () => {
  assert.strictEqual(red('三丰会接电话'), '三丰会接电话');
  assert.strictEqual(red('弓长张三丰，电话13812345678'), '弓长张**，电话138****5678');
  assert.deepStrictEqual(R.redactDialogSegments(['弓长张三丰，138开头…后面是零零幺三'], ['scammer']), ['弓长张三丰，138开头…后面是零零幺三']);
});

test('patterns.name 的拆字前缀与 nameRules.split.spellings 一致', () => {
  const src = CORE.patterns.name.source;
  CORE.nameRules.split.spellings.forEach((sp) => assert.ok(src.includes(sp.slice(0, -1) + '(?=' + sp.slice(-1) + ')'), sp));
});

test('模拟器 revealSplitName 台词：报完户名再拆字复述，全名与拆字+名都不留', () => {
  const tpls = SCRIPTS.common.revealSplitName;
  assert.ok(tpls.length >= 3);
  const names = ['赵明', '钱伟', '孙丽', '李强', '周杰', '吴刚', '郑华', '冯涛', '张三丰', '李四', '陈小明', '黄晓东', '程一', '林夕', '许嵩', '王小二'];
  let n = 0;
  names.forEach((name) => {
    const sp = CORE.nameRules.split.spellings.find((x) => x.slice(-1) === name.charAt(0));
    if (!sp) return;
    const given = name.slice(1);
    tpls.forEach((tpl) => {
      const line = tpl.replace(/\{name\}/g, name).replace(/\{name_split\}/g, sp).replace(/\{name_given\}/g, given);
      const out = red(line);
      assert.ok(!out.includes(name), line + ' -> ' + out);
      assert.ok(!out.includes(sp + given) && !out.includes(sp + '，' + given), line + ' -> ' + out);
      if (given.length >= 2) assert.ok(!out.includes(given), line + ' -> ' + out);
      assert.ok(out.includes(name.charAt(0) + '*'.repeat(name.length - 1)), line + ' -> ' + out);
      n++;
    });
  });
  assert.ok(n >= 40);
});
