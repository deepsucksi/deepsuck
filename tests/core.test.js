'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const build = require('../scripts/build-core.js');
const X = require('../site/assets/js/extractors.js');
const R = require('../site/assets/js/redact.js');
const T = require('../site/assets/js/tactics.js');
const N = require('../site/assets/js/normalize.js');
const E = require('../site/assets/js/engine.js');

const CORE = path.join(__dirname, '../site/assets/core');

test('core-data.js 与 core/*.json 同步（改了 JSON 请运行 npm run build:core）', () => {
  assert.equal(fs.readFileSync(build.OUT, 'utf8'), build.render());
});

test('core/*.json：正则全部可编译，且只用 Python re 也支持的语法', () => {
  const ex = JSON.parse(fs.readFileSync(path.join(CORE, 'extractors.json'), 'utf8'));
  const ta = JSON.parse(fs.readFileSync(path.join(CORE, 'tactics.json'), 'utf8'));
  const sources = Object.values(ex.patterns).map((p) => p.source).concat(ta.tactics.map((t) => t.pattern));
  for (const src of sources) {
    assert.doesNotThrow(() => new RegExp(src));
    assert.ok(!/\(\?<[a-zA-Z]/.test(src), '不使用命名分组（Python 语法不同）：' + src);
    assert.ok(!/\\p\{/.test(src), '不使用 \\p{} Unicode 属性：' + src);
  }
  const pe = JSON.parse(fs.readFileSync(path.join(CORE, 'personas.json'), 'utf8'));
  for (const p of pe.personas) for (const list of Object.values(p.templates)) for (const it of list) {
    if (typeof it !== 'string') { assert.ok(it.when && it.t); assert.doesNotThrow(() => new RegExp(it.when)); }
  }
});

const OBF = [
  ['加我 微 信 kefu_tb2026 详聊', 'wechat', 'kefu_tb2026'],
  ['V信：abc12345', 'wechat', 'abc12345'],
  ['薇信号 scam_demo01', 'wechat', 'scam_demo01'],
  ['绿泡泡 hello_world88', 'wechat', 'hello_world88'],
  ['扣扣 2876543210', 'qq', '2876543210'],
  ['企鹅号码：1000012345', 'qq', '1000012345'],
  ['Q Q：1000012345', 'qq', '1000012345'],
  ['网址 refund-tb 点 com 下载', 'url', 'refund-tb.com'],
  ['打开 goldwin-vip。top 注册', 'url', 'goldwin-vip.top'],
  ['refund-tb[.]top/dl', 'url', 'refund-tb.top/dl'],
  ['w w w . goldwin-vip . top', 'url', 'www.goldwin-vip.top'],
  ['打 幺三九 零零幺幺 二二三三', 'phone', '139 0011 2233'],
  ['电话一三九零零一一二二三三', 'phone', '13900112233'],
  ['１３９００１１２２３３', 'phone', '13900112233'],
  ['1 3 9 0 0 1 1 2 2 3 3 联系', 'phone', '13900112233'],
  ['卡号 六二二二 零二零二 零零一一 二二三三 四四五', 'bank_card', '6222 0202 0011 2233 445'],
  ['支付寶 13900112233', 'alipay', '13900112233']
];

test('去武装写法：提取到规范化后的值', () => {
  for (const [text, type, value] of OBF) {
    const hit = X.extractSensitive(text).find((e) => e.type === type);
    assert.ok(hit, `${text} 应提取到 ${type}`);
    assert.equal(hit.value, value, text);
  }
});

test('去武装写法：脱敏替换的是原文片段，不残留数字/汉字数字', () => {
  const cases = [
    ['打 幺三九 零零幺幺 二二三三 找我', /幺三九|零零幺幺|二二三三/],
    ['卡号 六二二二 零二零二 零零一一 二二三三 四四五，户名王建国', /零二零二|二二三三|建国/],
    ['１３９００１１２２３３', /００１１/],
    ['加 微 信 kefu_tb2026', /kefu_tb2026/],
    ['1 3 9 0 0 1 1 2 2 3 3', /0 0 1 1/]
  ];
  for (const [text, leak] of cases) {
    const red = R.redactText(text, X.extract(text));
    assert.ok(!leak.test(red), `${text} -> ${red}`);
  }
});

test('去武装写法：不误伤正常文本', () => {
  for (const t of ['三三两两地走过来', '版本 1.5 更新了', '我点了一下就好了', '今天下午三点开会', 'App点开没反应']) {
    assert.deepEqual(X.extractSensitive(t).map((e) => e.value), [], t);
  }
  assert.equal(N.normalize('普通的一句话').changed, false);
  assert.equal(N.normalize('访问 abc.com。然后').text, '访问 abc.com。然后');
});

test('话术识别也能看穿去武装写法', () => {
  assert.ok(T.classify('加我 微 信 私聊').some((t) => t.id === 'off_platform'));
  assert.ok(T.classify('把 验 证 码 发我').some((t) => t.id === 'otp'));
  assert.ok(T.classify('转到 安 全 账 户').some((t) => t.id === 'safe_account'));
});

test('会话：去武装写法的情报进入看板且报告不泄露', () => {
  const s = new E.Session({ scenario: 'police', persona: 'zheng' });
  s.ingest('把钱转到 六二二二 零二零二 零零一一 二二三三 四四五，有问题打 幺三九 零零幺幺 二二三三');
  const types = s.intelList().map((i) => i.type).sort();
  assert.deepEqual(types, ['bank_card', 'phone']);
  const json = JSON.stringify(s.report());
  assert.ok(!/二二三三|零零幺幺/.test(json), json);
  const sub = s.submission();
  assert.ok(sub.indicators.some((i) => i.value === '13900112233'));
});
