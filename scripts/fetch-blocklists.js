#!/usr/bin/env node
/*!
 * 拉取公开钓鱼/诈骗域名黑名单（destroylist、Phishing.Database，均为 MIT），合并去重后按 FNV-1a 分成 256 片：
 *   site/data/blocklist/meta.json     数据源、许可证、条数、生成时间
 *   site/data/blocklist/d/00..ff.txt  每行 "domain<TAB>bits"（bits 第 i 位 = meta.sources[i]）
 * 产物不入库（.gitignore），由 .github/workflows/pages.yml 在部署前运行；本地可运行 npm run blocklists。
 * 用法：node scripts/fetch-blocklists.js [--out site/data/blocklist] [--from-dir 本地已下载的 txt 目录]
 * Apache-2.0
 */
'use strict';
const fs = require('fs');
const path = require('path');
const BL = require('../site/assets/js/blocklist.js');

const args = process.argv.slice(2);
const argOf = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const OUT = path.resolve(argOf('--out', path.join(__dirname, '..', 'site', 'data', 'blocklist')));
const FROM = argOf('--from-dir', null);

const DOMAIN_RE = /^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

async function getText(src) {
  if (FROM) return fs.readFileSync(path.join(FROM, src.id + '.txt'), 'utf8');
  const r = await fetch(src.url, { headers: { 'User-Agent': 'deepsuck-blocklist-builder (+https://deepsuck.si)' } });
  if (!r.ok) throw new Error(src.id + ': HTTP ' + r.status);
  return r.text();
}

function build(texts) {
  const all = new Map();
  const counts = [];
  BL.DOMAIN_SOURCES.forEach((src, i) => {
    let n = 0;
    for (let line of (texts[i] || '').split(/\r?\n/)) {
      line = line.trim().toLowerCase().replace(/^\*\./, '').replace(/\.$/, '');
      if (!line || line[0] === '#' || line[0] === '!' || !DOMAIN_RE.test(line)) continue;
      n++;
      all.set(line, (all.get(line) || 0) | (1 << i));
    }
    counts.push(n);
  });
  const shards = {};
  for (const [d, bits] of all) {
    const id = BL.shardOf(d);
    (shards[id] = shards[id] || []).push(d + '\t' + bits);
  }
  return { all, counts, shards };
}

async function main() {
  const texts = [];
  const sources = [];
  for (const src of BL.DOMAIN_SOURCES) {
    try {
      texts.push(await getText(src));
      sources.push({ id: src.id, name: src.name, homepage: src.homepage, license: src.license, url: src.url, ok: true });
    } catch (e) {
      console.warn('⚠️ 拉取失败', src.id, e.message);
      texts.push('');
      sources.push({ id: src.id, name: src.name, homepage: src.homepage, license: src.license, url: src.url, ok: false });
    }
  }
  const { all, counts, shards } = build(texts);
  if (!all.size) { console.error('没有拉到任何域名，跳过生成'); process.exitCode = 1; return; }
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(path.join(OUT, 'd'), { recursive: true });
  for (let n = 0; n < BL.SHARDS; n++) {
    const id = ('0' + n.toString(16)).slice(-2);
    fs.writeFileSync(path.join(OUT, 'd', id + '.txt'), (shards[id] || []).sort().join('\n') + '\n');
  }
  sources.forEach((s, i) => { s.count = counts[i]; });
  const meta = {
    schema: 'deepsuck.blocklist/v1',
    generatedAt: new Date().toISOString(),
    shards: BL.SHARDS,
    hash: 'fnv1a32(domain) % shards, hex2',
    total: all.size,
    sources,
    notice: '数据来自上述公开项目（MIT），按原许可证再分发；命中仅供参考，不能作为认定依据。'
  };
  fs.writeFileSync(path.join(OUT, 'meta.json'), JSON.stringify(meta, null, 1) + '\n');
  const lic = [];
  for (const s of sources) {
    let text = '';
    try { text = FROM ? '' : await (await fetch(s.url.replace(/[^/]+$/, 'LICENSE'))).text(); } catch (e) { text = ''; }
    lic.push(`== ${s.name} — ${s.homepage} — ${s.license} ==\n${text || '（见上方链接中的 LICENSE）'}`);
  }
  fs.writeFileSync(path.join(OUT, 'LICENSES.txt'), lic.join('\n\n') + '\n');
  console.log(`wrote ${path.relative(process.cwd(), OUT)}: ${all.size} domains (${counts.join(' + ')}) in ${BL.SHARDS} shards`);
}

if (require.main === module) main();
module.exports = { build };
