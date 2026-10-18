#!/usr/bin/env node
/*!
 * DeepSuck — scripts/screenshots.js：用无头 Chrome 给站点三页拍桌面 / 手机截图，输出 WebP 到 screenshots/。
 *
 *   npm i --no-save playwright-core     # 只需一次；项目本身仍是零依赖
 *   npm run screenshots                 # 内置静态服务器托管 site/，拍完即退出
 *   npm run screenshots -- --base https://deepsuck.si --out /tmp/shots --full
 *
 * 选项：--base <url> 拍指定站点（默认自起本地服务器）；--out <dir> 输出目录（默认 screenshots/）；
 *       --full 拍整页（默认只拍首屏）；--only landing,demo 只拍部分；--png 输出 PNG 而不是 WebP。
 * Chrome：优先 CHROME_PATH，其次常见安装路径，最后用 playwright 的 chrome channel。
 * 每张图会检查页面文字，出现不该出现的第三方品牌名时报错退出。
 * Apache-2.0
 */
'use strict';
const fs = require('fs');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf('--' + name); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : true) : def; };
const OUT = path.resolve(opt('out', path.join(ROOT, 'screenshots')));
const FULL = !!opt('full', false);
const PNG = !!opt('png', false);
const ONLY = opt('only', '') ? String(opt('only')).split(',') : null;
const FORBIDDEN = /deep\s*seek/i;

let chromium;
try { ({ chromium } = require('playwright-core')); } catch (e) {
  console.error('缺少 playwright-core：请先运行  npm i --no-save playwright-core  （不会写入 package.json）');
  process.exit(1);
}

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const c = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'];
  return c.find((p) => fs.existsSync(p));
}

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml' };
function staticServer() {
  const site = path.join(ROOT, 'site');
  const srv = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split('?')[0]);
    if (p.endsWith('/')) p += 'index.html';
    const f = path.join(site, path.normalize(p));
    if (!f.startsWith(site) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((r) => srv.listen(0, '127.0.0.1', () => r(srv)));
}

const DESKTOP = { viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 };
const MOBILE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const SHOTS = [
  { name: 'landing-1280', group: 'landing', url: '', ctx: DESKTOP, wait: 4000 },
  { name: 'landing-390', group: 'landing', url: '', ctx: MOBILE, wait: 4000 },
  { name: 'demo-1280', group: 'demo', url: 'demo.html?scenario=police&autoplay=4&fast=1', ctx: DESKTOP, done: true },
  { name: 'demo-390', group: 'demo', url: 'demo.html?scenario=police&autoplay=3&fast=1', ctx: MOBILE, done: true },
  { name: 'demo-summary-1280', group: 'demo', url: 'demo.html?scenario=police&autoplay=4&fast=1&summary=1', ctx: DESKTOP, done: true },
  { name: 'intel-1280', group: 'intel', url: 'intel.html', ctx: DESKTOP, wait: 800 },
  { name: 'intel-390', group: 'intel', url: 'intel.html', ctx: MOBILE, wait: 800 }
];

async function toWebp(page, png) {
  return Buffer.from(await page.evaluate(async (b64) => {
    const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
    const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext('2d').drawImage(img, 0, 0);
    return c.toDataURL('image/webp', 0.86).split(',')[1];
  }, png.toString('base64')), 'base64');
}

(async () => {
  let srv = null, base = opt('base', '');
  if (!base) { srv = await staticServer(); base = 'http://127.0.0.1:' + srv.address().port + '/'; }
  if (!base.endsWith('/')) base += '/';
  fs.mkdirSync(OUT, { recursive: true });
  const exe = findChrome();
  const browser = await chromium.launch(exe ? { executablePath: exe, args: ['--no-sandbox'] } : { channel: 'chrome', args: ['--no-sandbox'] });
  const enc = await (await browser.newContext()).newPage();
  let bad = 0;
  for (const s of SHOTS) {
    if (ONLY && !ONLY.includes(s.group) && !ONLY.includes(s.name)) continue;
    const ctx = await browser.newContext(s.ctx);
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(base + s.url, { waitUntil: 'networkidle' });
    if (s.done) await page.waitForSelector('body[data-autoplay-done]', { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(s.wait || 1200);
    const text = await page.evaluate(() => document.body.innerText + ' ' + document.title);
    if (FORBIDDEN.test(text)) { console.error('页面文字中出现了不应出现的品牌名：' + s.name); bad++; }
    const png = await page.screenshot({ fullPage: FULL });
    const file = path.join(OUT, s.name + (PNG ? '.png' : '.webp'));
    fs.writeFileSync(file, PNG ? png : await toWebp(enc, png));
    console.log((errors.length ? '! ' : '  ') + path.relative(process.cwd(), file) + '  ' + Math.round(fs.statSync(file).size / 1024) + ' KB' + (errors.length ? '  控制台错误：' + errors.join(' | ') : ''));
    await ctx.close();
  }
  await browser.close();
  if (srv) srv.close();
  process.exit(bad ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
