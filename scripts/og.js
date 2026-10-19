#!/usr/bin/env node
/*!
 * DeepSuck — scripts/og.js：把 scripts/og/og.html 渲染为 1200×630 的 Open Graph 图。
 *   npm i --no-save playwright-core && npm run og
 * 输出：site/assets/og.png（首页）、og-demo.png、og-intel.png。
 * 沙盒图的人设名单、人数与场景数从 site/assets/core/personas.json、scenarios.json 读取（人设唯一数据源），不在模板里写死。Apache-2.0
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
let chromium;
try { ({ chromium } = require('playwright-core')); } catch (e) { console.error('缺少 playwright-core：npm i --no-save playwright-core'); process.exit(1); }
const ROOT = path.resolve(__dirname, '..');
const CORE = path.join(ROOT, 'site', 'assets', 'core');
const readCore = (n) => JSON.parse(fs.readFileSync(path.join(CORE, n + '.json'), 'utf8'));
const OG = { personas: readCore('personas').personas.map((p) => p.name), scenarios: readCore('scenarios').scenarios.length };
const exe = process.env.CHROME_PATH || ['/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find((p) => fs.existsSync(p));
(async () => {
  const b = await chromium.launch(exe ? { executablePath: exe, args: ['--no-sandbox'] } : { channel: 'chrome' });
  const page = await (await b.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 })).newPage();
  await page.addInitScript((og) => { window.__OG = og; }, OG);
  console.log('  人设（personas.json）：' + OG.personas.join('、') + '；场景 ' + OG.scenarios + ' 个');
  for (const [v, name] of [['home', 'og.png'], ['demo', 'og-demo.png'], ['intel', 'og-intel.png']]) {
    await page.goto(pathToFileURL(path.join(__dirname, 'og', 'og.html')).href + '?v=' + v);
    await page.evaluate(() => document.fonts.ready);
    const out = path.join(ROOT, 'site', 'assets', name);
    await page.screenshot({ path: out, clip: { x: 0, y: 0, width: 1200, height: 630 } });
    console.log('  site/assets/' + name + '  ' + Math.round(fs.statSync(out).size / 1024) + ' KB');
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
