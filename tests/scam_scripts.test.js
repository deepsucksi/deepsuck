'use strict';
// site/assets/core/scam_scripts.json（话术语料权威版）与 scenarios.json sampleSources 的结构与脱敏检查。
// 完整 JSON Schema 校验在 python/tests/test_scam_scripts.py（jsonschema）；这里不引第三方依赖，只查关键约束。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const T = require('../site/assets/js/tactics.js');
const X = require('../site/assets/js/extractors.js');

const CORE = path.join(__dirname, '../site/assets/core');
const D = JSON.parse(fs.readFileSync(path.join(CORE, 'scam_scripts.json'), 'utf8'));
const SC = JSON.parse(fs.readFileSync(path.join(CORE, 'scenarios.json'), 'utf8'));
const PHASES = ['opening', 'trust', 'pressure', 'request', 'payout'];
const EMOJI = /[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/u;

test('话术语料：许可、阶段、7 类 × 5 阶段全覆盖', () => {
  assert.equal(D.schema, 'deepsuck.core.scam-scripts/v1');
  assert.equal(D.license, 'CC-BY-4.0');
  assert.equal(D.attribution, 'DeepSuck (deepsuck.si)');
  assert.deepEqual(D.phases.map((p) => p.id), PHASES);
  assert.equal(D.types.length, 7);
  for (const t of D.types) for (const ph of PHASES) assert.ok(D.entries.some((e) => e.type === t.id && e.phase === ph), t.id + ' ' + ph);
});

test('话术语料：来源标注与 sourceRef、链接一致', () => {
  const src = new Map(D.sources.map((s) => [s.id, s]));
  for (const e of D.entries) {
    assert.ok(D.sourceTypes[e.sourceType], e.id);
    assert.equal(e.sourceLabel, D.sourceTypes[e.sourceType].label, e.id);
    assert.ok(e.sourceIds.length && e.sourceIds.every((s) => src.has(s)), e.id);
    if (e.sourceType === 'awareness') assert.equal(e.sourceRef, undefined, e.id);
    else assert.ok(e.sourceRef, e.id + ' 标注为案例 / 通报 / 数据集时必须指明 sourceRef');
    for (const u of e.sourceUrls) assert.match(u, /^https?:\/\//);
  }
});

test('话术语料：脱敏（无长数字、手机号、网址、打码星号、emoji），占位符都有定义', () => {
  for (const e of D.entries) {
    const s = e.text;
    assert.ok(!/\d{6,}/.test(s) && !/1[3-9]\d{9}/.test(s), s);
    assert.ok(!/https?:\/\/|www\./i.test(s) && !s.includes('*') && !EMOJI.test(s), s);
    for (const m of s.matchAll(/\{(.+?)\}/g)) assert.ok(D.placeholders[m[1]], s);
    // 句子本身不含可提取的敏感值
    assert.deepEqual(X.extractSensitive(s), [], s);
  }
  assert.ok(!JSON.stringify(D).includes('DeepSeek'));
});

test('话术语料：tactics 字段与当前分类器一致（改分类规则后请重跑 build 脚本）', () => {
  let n = 0;
  for (const e of D.entries) {
    const got = T.classify(e.text).map((t) => t.id);
    for (const id of e.tactics) assert.ok(got.includes(id), e.id + ' ' + id);
    n += got.length > 0;
  }
  assert.ok(n / D.entries.length >= 0.5, '至少一半语料句能被话术分类器识别');
});

test('演示场景：sampleSources 与 samples 一一对应，标注取自语料的 sourceTypes', () => {
  for (const s of SC.scenarios) {
    assert.equal(s.sampleSources.length, s.samples.length, s.id);
    for (const x of s.sampleSources) {
      assert.ok(D.sourceTypes[x.sourceType], s.id);
      assert.equal(x.label, D.sourceTypes[x.sourceType].label);
      assert.ok(D.sources.some((y) => y.id === x.sourceId), x.sourceId);
      if (x.sourceType !== 'awareness') assert.ok(x.sourceRef, s.id);
    }
    for (const line of s.samples) for (const m of line.matchAll(/https?:\/\/([^/\s]+)/g)) assert.match(m[1], /\.example$/, line);
  }
});
