#!/usr/bin/env node
/*!
 * 把 site/assets/core/*.json（规则与台词的单一事实来源）打包成浏览器可同步加载的 site/assets/js/core-data.js。
 * 用法：npm run build:core   （修改任何 core/*.json 后运行；npm test 会检查产物是否最新）
 * Apache-2.0
 */
'use strict';
const fs = require('fs');
const path = require('path');
const CORE = path.join(__dirname, '..', 'site', 'assets', 'core');
const OUT = path.join(__dirname, '..', 'site', 'assets', 'js', 'core-data.js');
const NAMES = ['extractors', 'tactics', 'scenarios', 'personas', 'blocklists', 'cardbin', 'name_stopchars'];

function render() {
  const data = {};
  for (const n of NAMES) data[n] = JSON.parse(fs.readFileSync(path.join(CORE, n + '.json'), 'utf8'));
  return '/*! DeepSuck — core-data.js：由 scripts/build-core.js 从 site/assets/core/*.json 自动生成，请勿手改。Apache-2.0 */\n' +
    '(function (root) {\n  root.DeepSuck = root.DeepSuck || {};\n  root.DeepSuck.coreData = ' + JSON.stringify(data) + ';\n})(typeof self !== \'undefined\' ? self : this);\n';
}

if (require.main === module) {
  fs.writeFileSync(OUT, render());
  console.log('wrote', path.relative(process.cwd(), OUT));
}
module.exports = { render, OUT };
