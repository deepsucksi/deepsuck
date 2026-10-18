'use strict';
// EN 模式无中文：用无头 Chrome 打开站点各页，切到英文（?lang=en 或点语言按钮），等动态内容渲染完，
// 收集全部文本节点与 aria-label / title / alt / placeholder / data-short（CSS 显示）属性、<title>、meta description 与 og/twitter 文案，
// 断言不含中文字符（CJK）。只有白名单里的节点可以保留中文，白名单见下方 WHITELIST，每条都写了理由。
//
// 依赖：playwright-core + 本机 Chrome。项目本身零依赖，按以下顺序找 playwright-core：
//   仓库 node_modules（npm i --no-save playwright-core）→ 环境变量 PLAYWRIGHT_CORE（模块路径）→ /workspace/deepsuck-audit/tools/node_modules/playwright-core
// Chrome：CHROME_PATH → 常见安装路径。都找不到时跳过；设置 I18N_EN_REQUIRED=1（CI）则改为失败。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

const ROOT = path.join(__dirname, '..');
const SITE = path.join(ROOT, 'site');
const CJK = /[\u2E80-\u2FDF\u3040-\u30FF\u3100-\u312F\u3190-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF\u3000-\u303F]/;

// 白名单：尽量窄，只放明确的演示语料 / 情报数据 / 必须用中文的入口。
const WHITELIST = [
  { selector: '[data-i18n-keep="dialogue"]',
    why: '示例对话与演示语料：首页轮播里的骗子原话与人设回复、提取结果表里的骗子原话、沙盒聊天气泡、样例骗子台词按钮、看板里的对话转写。已定：英文版保留中文对话。' },
  { selector: '[data-i18n-keep="intel-data"]',
    why: '情报数据本身：data/intel.json 的条目值、备注、开户行/发卡行，以及从中文对话里提取出的打码值（如户名“王**”、APP 名、开户行）和沙盒生成的情报提交内容（对应中文的 GitHub 提交模板）。这些是数据不是界面文案，翻译会改变情报。' },
  { selector: '[data-i18n-keep="search-term"]',
    why: '情报库“如何举报”里要用户在应用商店搜索的中文应用名与入口名（国家反诈中心、我要举报），英文旁注了译名，保留中文才能搜到。' },
  { selector: '.lang-toggle',
    why: '语言切换按钮在英文模式下显示“中文”，按惯例用目标语言自己的文字标注。' },
];
const KEEP_VALUES = ['dialogue', 'intel-data', 'search-term'];

function findPlaywright() {
  const cands = ['playwright-core', process.env.PLAYWRIGHT_CORE, '/workspace/deepsuck-audit/tools/node_modules/playwright-core'].filter(Boolean);
  for (const c of cands) { try { return require(c); } catch (_) {} }
  return null;
}
function findChrome() {
  const c = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].filter(Boolean);
  return c.find((p) => fs.existsSync(p));
}
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2', '.xml': 'application/xml', '.txt': 'text/plain', '.rss': 'application/rss+xml', '.csv': 'text/csv' };
function serve() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      if (p.endsWith('/')) p += 'index.html';
      let f = path.join(SITE, p);
      if (!f.startsWith(SITE)) { res.writeHead(403); return res.end(); }
      if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
      if (!fs.existsSync(f)) { res.writeHead(404, { 'content-type': MIME['.html'] }); return res.end(fs.readFileSync(path.join(SITE, '404.html'))); }
      res.writeHead(200, { 'content-type': MIME[path.extname(f)] || 'application/octet-stream' });
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv));
  });
}

// 在页面里收集所有带中文的文本 / 属性（白名单节点及其子孙除外）
function collect(args) {
  const { whitelist, cjkSource, keepValues } = args;
  const CJK = new RegExp(cjkSource);
  const sel = whitelist.join(',');
  const hits = [];
  const kept = (el) => el && el.closest && el.closest(sel);
  const where = (el) => { const id = el.id ? '#' + el.id : ''; const cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''; return el.tagName.toLowerCase() + id + cls; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(el.tagName)) continue;
    if (CJK.test(n.nodeValue) && !kept(el)) hits.push('text ' + where(el) + ': ' + n.nodeValue.trim().slice(0, 80));
  }
  for (const el of document.body.querySelectorAll('*')) {
    for (const a of ['aria-label', 'title', 'alt', 'placeholder', 'data-short']) {
      const v = el.getAttribute(a);
      if (v && CJK.test(v) && !kept(el)) hits.push('@' + a + ' ' + where(el) + ': ' + v.slice(0, 80));
    }
    if ((el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') && CJK.test(el.value || '') && !kept(el)) hits.push('value ' + where(el) + ': ' + el.value.slice(0, 80));
    const k = el.getAttribute('data-i18n-keep');
    if (k !== null && keepValues.indexOf(k) < 0) hits.push('未登记的白名单值 data-i18n-keep="' + k + '" ' + where(el));
  }
  if (CJK.test(document.title)) hits.push('<title>: ' + document.title);
  for (const m of document.head.querySelectorAll('meta[name="description"],meta[property^="og:"],meta[name^="twitter:"],link[title]')) {
    const v = m.getAttribute('content') || m.getAttribute('title') || '';
    if (CJK.test(v)) hits.push('meta ' + (m.getAttribute('name') || m.getAttribute('property') || m.getAttribute('rel')) + ': ' + v.slice(0, 80));
  }
  const loc = document.head.querySelector('meta[property="og:locale"]');
  if (loc && loc.getAttribute('content') !== 'en_US') hits.push('og:locale = ' + loc.getAttribute('content'));
  if (document.documentElement.lang !== 'en') hits.push('<html lang> = ' + document.documentElement.lang);
  return hits;
}

function blogPages() {
  const dir = path.join(SITE, 'blog', 'en');
  if (!fs.existsSync(dir)) return [];
  const out = [];
  (function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p); else if (e.name.endsWith('.html')) out.push('/' + path.relative(SITE, p).split(path.sep).join('/'));
    }
  })(dir);
  return out.sort().map((u) => ({ name: 'blog ' + u, url: u, wait: null }));
}

const PAGES = [
  { name: '首页', url: '/index.html?lang=en', wait: () => document.getElementById('botSpeaker').textContent.trim() && document.getElementById('clueTitle').textContent.trim() },
  { name: '沙盒（开场）', url: '/demo.html?lang=en&fast=1', wait: () => document.querySelector('#msgs .msg.bot:not(.typing)') },
  { name: '沙盒（自动演示 + 看板 + 提交框）', url: '/demo.html?lang=en&fast=1&autoplay=4&summary=1&submit=1', wait: () => document.body.getAttribute('data-autoplay-done') === '1' && document.getElementById('summaryModal').open },
  { name: '沙盒（李大爷 · 冒充公检法）', url: '/demo.html?lang=en&fast=1&scenario=police&persona=li&autoplay=3', wait: () => document.body.getAttribute('data-autoplay-done') === '1' },
  { name: '情报库', url: '/intel.html?lang=en', wait: () => document.querySelector('#results .icard2') && document.querySelector('#typeStats .stat') },
  { name: '404', url: '/404.html?lang=en', wait: null },
  { name: '不存在的地址（GitHub Pages 回落到 404.html）', url: '/no-such-page?lang=en', wait: null },
];
const TOGGLES = [
  { name: '首页：点 EN 按钮', url: '/index.html', button: '#langBtn', wait: () => document.getElementById('botSpeaker').textContent.trim() },
  { name: '沙盒：点 EN 按钮（切换后动态内容重渲染）', url: '/demo.html?fast=1&autoplay=2', button: '.nav .lang-toggle', wait: () => document.body.getAttribute('data-autoplay-done') === '1' },
  { name: '情报库：点 EN 按钮', url: '/intel.html', button: '.nav .lang-toggle', wait: () => document.querySelector('#results .icard2') },
];

const pw = findPlaywright();
const chrome = findChrome();
const missing = !pw ? '找不到 playwright-core' : !chrome ? '找不到 Chrome' : '';
const required = process.env.I18N_EN_REQUIRED === '1';

test('EN 模式：渲染后的可见文本与 aria/title/alt/placeholder 不含中文（白名单除外）', { skip: missing && !required ? missing + '，跳过（CI 设 I18N_EN_REQUIRED=1 时会失败）' : false, timeout: 180000 }, async () => {
  assert.ok(!missing, missing);
  const srv = await serve();
  const base = 'http://127.0.0.1:' + srv.address().port;
  const browser = await pw.chromium.launch({ executablePath: chrome, args: ['--no-sandbox'] });
  const args = { whitelist: WHITELIST.map((w) => w.selector), cjkSource: CJK.source, keepValues: KEEP_VALUES };
  const report = [];
  try {
    for (const vp of [{ width: 1280, height: 900 }, { width: 375, height: 812 }]) {
      for (const pg of [...PAGES, ...blogPages(), ...TOGGLES]) {
        // 每页独立 context：localStorage 不串（切换方式会写 deepsuck.lang）
        const ctx = await browser.newContext({ viewport: vp, serviceWorkers: 'block' });
        const page = await ctx.newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push(String(e)));
        await page.goto(base + pg.url, { waitUntil: 'load' });
        if (pg.button) {
          await page.evaluate(() => { try { localStorage.removeItem('deepsuck.lang'); } catch (_) {} });
          const btn = page.locator(pg.button + ':visible').first();
          if (await btn.count()) await btn.click(); else await page.locator('.lang-toggle').first().evaluate((b) => b.click());
        }
        if (pg.wait) await page.waitForFunction(pg.wait, null, { timeout: 30000 });
        await page.waitForLoadState('networkidle').catch(() => {});
        await page.waitForTimeout(300);
        const hits = await page.evaluate(collect, args);
        for (const h of hits) report.push(`[${vp.width}] ${pg.name} ${pg.url}  ${h}`);
        for (const e of errors) report.push(`[${vp.width}] ${pg.name} ${pg.url}  页面脚本错误: ${e}`);
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
    srv.close();
  }
  assert.deepEqual(report, [], '英文模式仍有中文：\n' + report.join('\n'));
});

test('EN 白名单：每条都有理由，data-i18n-keep 只用登记过的值', () => {
  for (const w of WHITELIST) assert.ok(w.selector && w.why && w.why.length > 10, w.selector);
  const used = new Set();
  for (const f of ['index.html', 'demo.html', 'intel.html', '404.html']) {
    for (const m of fs.readFileSync(path.join(SITE, f), 'utf8').matchAll(/data-i18n-keep="([^"]+)"/g)) used.add(m[1]);
  }
  for (const f of fs.readdirSync(path.join(SITE, 'assets/js'))) {
    for (const m of fs.readFileSync(path.join(SITE, 'assets/js', f), 'utf8').matchAll(/data-i18n-keep[=", ]+'?"?([a-z-]+)/g)) used.add(m[1]);
  }
  for (const v of used) assert.ok(KEEP_VALUES.includes(v), v);
});

test('EN 词条：页面上每个 data-i18n / data-i18n-attr 的键都有英文', () => {
  const i18n = fs.readFileSync(path.join(SITE, 'assets/js/i18n.js'), 'utf8');
  const missingKeys = [];
  for (const f of ['index.html', 'demo.html', 'intel.html', '404.html']) {
    const html = fs.readFileSync(path.join(SITE, f), 'utf8');
    const keys = [...html.matchAll(/data-i18n="([^"]+)"/g)].map((m) => m[1]);
    for (const m of html.matchAll(/data-i18n-attr="([^"]+)"/g)) for (const s of m[1].split(';')) keys.push(s.split(':').slice(1).join(':'));
    for (const k of keys) if (!i18n.includes(`'${k}':`)) missingKeys.push(f + ' ' + k);
    // 每页都要能切换语言
    assert.match(html, /class="[^"]*lang-toggle/, f + ' 缺语言切换按钮');
    assert.match(html, /assets\/js\/i18n\.js/, f + ' 未加载 i18n.js');
  }
  assert.deepEqual(missingKeys, []);
});
