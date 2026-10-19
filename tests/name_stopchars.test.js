'use strict';
// #185 应答字、虚词共用字表 site/assets/core/name_stopchars.json 的格式检查（行为反例见 extractor 测试）
const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../site/assets/core/name_stopchars.json');
const EX = require('../site/assets/core/extractors.json');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('name_stopchars.json：格式、单字、不重复、每个字至少一条反例', () => {
  assert.equal(S.schema, 'deepsuck.core.name_stopchars/v1');
  assert.ok(typeof S.comment === 'string' && S.comment.includes('用途'));
  assert.ok(Array.isArray(S.chars) && S.chars.length > 0);
  const seen = new Set();
  for (const r of S.chars) {
    assert.match(r.char, /^[\u4e00-\u9fa5]$/, '每项是单个汉字：' + r.char);
    assert.ok(!seen.has(r.char), '重复：' + r.char);
    seen.add(r.char);
    assert.ok(typeof r.kind === 'string' && r.kind);
    assert.ok(Array.isArray(r.negatives) && r.negatives.length >= 1, r.char + ' 至少一条反例');
    for (const t of r.negatives) assert.ok(t.includes(r.char), r.char + ' 的反例要含这个字：' + t);
  }
  for (const c of ['对', '是', '嗯', '好', '行', '哦', '有', '没', '只', '和', '谁', '啥']) assert.ok(seen.has(c), '缺 ' + c);
  const words = new Set();
  for (const r of S.words || []) {
    assert.match(r.word, /^[\u4e00-\u9fa5]{2,}$/, 'words 每项是两个字以上：' + r.word);
    assert.ok(!words.has(r.word), '重复：' + r.word);
    words.add(r.word);
    assert.ok(Array.isArray(r.negatives) && r.negatives.length >= 1 && r.negatives.every((t) => t.includes(r.word)), r.word);
  }
  for (const w of ['什么', '多少']) assert.ok(words.has(w), '缺 ' + w);
});

test('name_stopchars.json：表里的字都不是常见姓氏', () => {
  for (const r of S.chars) assert.ok(!EX.nameRules.surnames.includes(r.char), r.char + ' 在 nameRules.surnames 里');
});

test('name_stopchars.json：已打包进 core-data.js（网页侧读 DeepSuck.coreData.name_stopchars）', () => {
  const box = { self: {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../site/assets/js/core-data.js'), 'utf8'), box);
  assert.deepEqual(JSON.parse(JSON.stringify(box.self.DeepSuck.coreData.name_stopchars)), S);
});
