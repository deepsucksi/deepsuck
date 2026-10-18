#!/usr/bin/env node
/*!
 * 从 hexindai/bcbc（MIT，China UnionPay Bank Card BIN Checker）生成 site/assets/core/cardbin.json：
 *   bins: { "<BIN 前缀>": [["<银行代码>", "<卡种 DC/CC/SCC/PC>", <卡号长度>], ...] }（同一前缀可能按卡号长度对应不同发卡行），banks: { "<银行代码>": "<银行名称>" }
 * 数据随仓库分发（MIT，保留版权声明），查询全程本地完成，卡号不外传。
 * 用法：node scripts/fetch-cardbin.js [--ref <commit>] [--from-dir 本地 bcbc/data 目录]
 * Apache-2.0
 */
'use strict';
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const argOf = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const REF = argOf('--ref', 'de631827ffe8db2792d140f3476b02498fc1244f');
const FROM = argOf('--from-dir', null);
const OUT = path.join(__dirname, '..', 'site', 'assets', 'core', 'cardbin.json');
const RAW = 'https://raw.githubusercontent.com/hexindai/bcbc/' + REF + '/data/';

async function get(name) {
  if (FROM) return fs.readFileSync(path.join(FROM, name), 'utf8');
  const r = await fetch(RAW + name);
  if (!r.ok) throw new Error(name + ': HTTP ' + r.status);
  return r.text();
}

function rows(csv) {
  return csv.split(/\r?\n/).slice(1).map((l) => l.trim()).filter(Boolean).map((l) => l.split(','));
}

function build(binCsv, nameCsv) {
  const banks = {};
  for (const [code, name] of rows(nameCsv)) if (code && name) banks[code] = name;
  const bins = {};
  for (const [bin, bank, type, len] of rows(binCsv)) {
    if (!/^\d{3,10}$/.test(bin) || !banks[bank] || !/^(DC|CC|SCC|PC)$/.test(type)) continue;
    const n = +len;
    if (!(n >= 12 && n <= 19)) continue;
    const list = bins[bin] = bins[bin] || [];
    if (!list.some((x) => x[0] === bank && x[2] === n)) list.push([bank, type, n]);
  }
  const sorted = {};
  for (const k of Object.keys(bins).sort()) sorted[k] = bins[k];
  const sortedBanks = {};
  for (const k of Object.keys(banks).sort()) sortedBanks[k] = banks[k];
  return {
    schema: 'deepsuck.core.cardbin/v1',
    comment: '中国银联卡 BIN（发卡行识别号）表：最长前缀匹配，只用卡号前 3–10 位判断发卡行与卡种，不联网、不校验持卡人。数据并非官方注册表，仅供参考。由 scripts/fetch-cardbin.js 生成，请勿手改。',
    source: {
      name: 'hexindai/bcbc',
      homepage: 'https://github.com/hexindai/bcbc',
      ref: REF,
      files: ['data/bin.csv', 'data/name.csv'],
      license: 'MIT',
      copyright: 'Copyright (c) 2018 - 2020 Runrioter'
    },
    types: { DC: '借记卡', CC: '信用卡', SCC: '准贷记卡', PC: '预付费卡' },
    banks: sortedBanks,
    bins: sorted
  };
}

function render(data) {
  // 每个 BIN 一行，便于审阅 diff
  const head = JSON.stringify({ ...data, banks: undefined, bins: undefined }, null, 2).replace(/\n}$/, '');
  const banks = Object.keys(data.banks).map((k) => '    ' + JSON.stringify(k) + ': ' + JSON.stringify(data.banks[k])).join(',\n');
  const bins = Object.keys(data.bins).map((k) => '    ' + JSON.stringify(k) + ': ' + JSON.stringify(data.bins[k])).join(',\n');
  return head + ',\n  "banks": {\n' + banks + '\n  },\n  "bins": {\n' + bins + '\n  }\n}\n';
}

async function main() {
  const data = build(await get('bin.csv'), await get('name.csv'));
  fs.writeFileSync(OUT, render(data));
  console.log('wrote', path.relative(process.cwd(), OUT), Object.keys(data.bins).length, 'BINs,', Object.keys(data.banks).length, 'banks');
}

if (require.main === module) main().catch((e) => { console.error(e.message); process.exit(1); });
module.exports = { build, render };
