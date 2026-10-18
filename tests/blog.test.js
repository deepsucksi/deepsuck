'use strict';
// 博客：content/blog/*.md → site/blog/（scripts/build-blog.js）。检查生成结果与仓库一致、草稿不上线、链接有效、SEO 元数据齐全。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { build, diff, rel } = require('../scripts/build-blog.js');

const ROOT = path.join(__dirname, '..');
const SITE = path.join(ROOT, 'site');
const ORIGIN = 'https://deepsuck.si';
const FIXTURE = path.join(__dirname, 'fixtures', 'blog');
const pub = build();                                   // 仓库里的正式内容（不含草稿）
const all = build({ drafts: true });                   // 仓库里的全部内容（含草稿，即 npm run blog:preview）
const fxPub = build({ root: FIXTURE });                // 测试夹具：两篇已发布的中英互译文章 + 一篇中文草稿
const fxAll = build({ root: FIXTURE, drafts: true });
const BUILDS = [pub, all, fxPub, fxAll];

const htmlFiles = (b) => [...b.files.keys()].filter((f) => f.endsWith('.html'));
const attr = (html, re) => { const m = re.exec(html); return m ? m[1] : null; };
const meta = (html, key) => attr(html, new RegExp(`<meta (?:property|name)="${key}" content="([^"]*)"`));

test('site/blog 与 sitemap.xml 和 content/blog 同步（改了文章请运行 npm run blog）', () => {
  assert.deepEqual(diff(pub.files), []);
});

test('草稿不进正式构建：页面、RSS、sitemap 都没有草稿', () => {
  assert.ok(fxPub.all.some((p) => p.draft) && fxPub.posts.length === 2, '夹具：2 篇已发布 + 1 篇草稿');
  for (const b of [pub, fxPub]) {
    for (const p of b.all.filter((x) => x.draft)) {
      const dir = (p.lang === 'zh' ? 'blog/' : 'blog/en/') + p.slug + '/';
      for (const [f, c] of b.files) {
        assert.ok(!f.startsWith(dir), `草稿 ${p.file} 被输出为 ${f}`);
        assert.ok(!c.includes('/' + p.slug + '/'), `${f} 里出现了草稿链接 ${p.slug}`);
      }
    }
    assert.ok(b.posts.every((p) => !p.draft));
    for (const lang of ['zh', 'en']) {
      const idx = b.files.get(lang === 'zh' ? 'blog/index.html' : 'blog/en/index.html');
      if (b.posts.some((p) => p.lang === lang)) assert.doesNotMatch(idx, /class="blog-empty"/);
      else assert.match(idx, /class="blog-empty"/, '没有已发布文章时显示空状态');
    }
  }
  assert.match(fxPub.files.get('blog/index.html'), /sample-post/);
  // 预览构建里草稿页带 noindex 与草稿标记，已发布页不带
  for (const b of [all, fxAll]) for (const p of b.posts) {
    const html = b.files.get((p.lang === 'zh' ? 'blog/' : 'blog/en/') + p.slug + '/index.html');
    if (!p.draft) { assert.doesNotMatch(html, /noindex/); continue; }
    assert.match(html, /<meta name="robots" content="noindex">/);
    assert.match(html, /class="tag amber"/);
  }
  assert.throws(() => require('node:child_process').execFileSync(process.execPath, [path.join(ROOT, 'scripts/build-blog.js'), '--drafts'], { stdio: 'pipe' }), '含草稿的构建不能写进 site/');
});

test('列表页空状态：没有已发布文章时显示「文章即将发布」/「Articles coming soon」、一句说明和 RSS 订阅入口', () => {
  const os = require('node:os');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'blog-empty-'));
  try {
    fs.mkdirSync(path.join(tmp, 'content', 'blog', 'zh'), { recursive: true });
    fs.mkdirSync(path.join(tmp, 'content', 'blog', 'en'), { recursive: true });
    fs.copyFileSync(path.join(FIXTURE, 'content', 'blog', 'site.json'), path.join(tmp, 'content', 'blog', 'site.json'));
    fs.copyFileSync(path.join(FIXTURE, 'content', 'blog', 'zh', 'draft-only.md'), path.join(tmp, 'content', 'blog', 'zh', 'draft-only.md'));
    const empty = build({ root: tmp });
    assert.equal(empty.posts.length, 0);
    const cases = { 'blog/index.html': ['文章即将发布', '订阅 RSS'], 'blog/en/index.html': ['Articles coming soon', 'Subscribe via RSS'] };
    for (const [f, [heading, cta]] of Object.entries(cases)) {
      const html = empty.files.get(f);
      const block = attr(html, /(<section class="blog-empty"[\s\S]*?<\/section>)/);
      assert.ok(block, `${f} 没有空状态区块`);
      assert.match(block, new RegExp(`<h2 id="blog-empty-title">${heading}</h2>`));
      assert.match(block, /<p>[^<]{20,}<\/p>/, `${f} 空状态缺一句说明`);
      assert.match(block, new RegExp(`<a class="btn small" href="feed.xml" type="application/rss\\+xml">${cta}</a>`));
      assert.ok(empty.files.has(f.replace('index.html', 'feed.xml')), `${f} 的 RSS 订阅入口指向的 feed.xml 不存在`);
      assert.doesNotMatch(html, /class="post-list"/);
      assert.doesNotMatch(html, /draft-only/, '空状态页不能泄露草稿');
    }
    // 有文章时不显示空状态，RSS 链接放在列表下方
    for (const f of ['blog/index.html', 'blog/en/index.html']) {
      const html = fxPub.files.get(f);
      assert.doesNotMatch(html, /blog-empty/);
      assert.match(html, /<p class="blog-feed"><a href="feed.xml">/);
    }
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('文章页：canonical、hreflang、OG、Twitter 卡片、JSON-LD BlogPosting 齐全', () => {
  assert.ok(fxAll.posts.length + all.posts.length >= 3);
  for (const b of [fxAll, all]) for (const p of b.posts) {
    const f = (p.lang === 'zh' ? 'blog/' : 'blog/en/') + p.slug + '/index.html';
    const html = b.files.get(f);
    const url = ORIGIN + '/' + f.replace(/index\.html$/, '');
    assert.equal(attr(html, /<link rel="canonical" href="([^"]+)"/), url, f);
    assert.equal(meta(html, 'og:url'), url);
    assert.equal(meta(html, 'og:type'), 'article');
    for (const k of ['og:title', 'og:description', 'og:image', 'twitter:title', 'twitter:description', 'twitter:image']) assert.ok(meta(html, k), `${f} 缺少 ${k}`);
    assert.equal(meta(html, 'twitter:card'), 'summary_large_image');
    assert.equal(attr(html, /<html lang="([^"]+)"/), p.lang === 'zh' ? 'zh-CN' : 'en');
    const ld = JSON.parse(attr(html, /<script type="application\/ld\+json">([\s\S]*?)<\/script>/));
    assert.equal(ld['@type'], 'BlogPosting');
    for (const k of ['headline', 'description', 'datePublished', 'dateModified', 'inLanguage', 'author', 'publisher', 'image', 'mainEntityOfPage']) assert.ok(ld[k], `${f} JSON-LD 缺少 ${k}`);
    assert.equal(ld.headline, p.title);
    assert.equal(ld.url, url);
    // hreflang 双向：A 指向 B，B 也指向 A
    const alts = [...html.matchAll(/<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">/g)].map((m) => [m[1], m[2]]);
    assert.ok(alts.some(([h, u]) => h === (p.lang === 'zh' ? 'zh-CN' : 'en') && u === url), `${f} 缺少指向自身的 hreflang`);
    for (const [h, u] of alts.filter(([h, u]) => u !== url && h !== 'x-default')) {
      const other = b.files.get(u.slice(ORIGIN.length + 1) + 'index.html');
      assert.ok(other, `${f} 的 hreflang ${h} 指向不存在的页面 ${u}`);
      assert.ok(other.includes(`href="${url}"`), `${u} 没有反向 hreflang 到 ${url}`);
    }
  }
});

test('Markdown 正文完整转换：标题、二级标题与表格都在页面里', () => {
  for (const b of [fxAll, all]) for (const p of b.posts) {
    const html = b.files.get((p.lang === 'zh' ? 'blog/' : 'blog/en/') + p.slug + '/index.html');
    const heads = [...p.body.matchAll(/^## (.+)$/gm)].map((m) => m[1].trim());
    assert.ok(heads.length >= 3, `${p.file} 至少 3 个二级标题`);
    for (const h of heads) assert.ok(html.includes(`<h2>${h.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')}</h2>`), `${p.file}: 缺少 <h2>${h}</h2>`);
    assert.equal((html.match(/<table>/g) || []).length, (p.body.match(/^\|.*\|\s*\n\|[-| :]+\|/gm) || []).length, `${p.file}: 表格数量不一致`);
    assert.ok(!/<p>---|\]\(http/.test(html), `${p.file}: 有未转换的 Markdown`);
  }
});

test('链接有效：站内链接都指向存在的文件，仓库链接指向存在的路径', () => {
  for (const b of BUILDS) {
    for (const f of htmlFiles(b)) {
      const html = b.files.get(f);
      for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
        let u = m[1].replace(/&amp;/g, '&');
        const gh = /^https:\/\/github\.com\/deepsucksi\/deepsuck\/(?:blob|tree)\/main\/([^#?]+)/.exec(u);
        if (gh) { assert.ok(fs.existsSync(path.join(ROOT, decodeURIComponent(gh[1]))), `${f}: 仓库里没有 ${gh[1]}`); continue; }
        if (u.startsWith(ORIGIN)) u = u.slice(ORIGIN.length) || '/';
        else if (/^(https?:|mailto:|#)/.test(u)) continue;
        let target = u.startsWith('/') ? u : path.posix.join('/' + path.posix.dirname(f), u);
        target = target.split(/[?#]/)[0];
        if (target.endsWith('/')) target += 'index.html';
        target = path.posix.normalize(target).replace(/^\//, '');
        assert.ok(b.files.has(target) || fs.existsSync(path.join(SITE, target)), `${f}: 链接 ${m[1]} 指向不存在的 ${target}`);
      }
    }
  }
});

test('RSS：中英各一份，带 language，条目数与已发布文章一致', () => {
  for (const [lang, f, code] of [['zh', 'blog/feed.xml', 'zh-CN'], ['en', 'blog/en/feed.xml', 'en']]) {
    for (const b of BUILDS) {
      const xml = b.files.get(f);
      assert.match(xml, /^<\?xml version="1.0" encoding="UTF-8"\?>\n<rss version="2.0"/);
      assert.ok(xml.includes(`<language>${code}</language>`));
      assert.ok(xml.includes(`<atom:link href="${ORIGIN}/${f}" rel="self"`));
      assert.equal((xml.match(/<item>/g) || []).length, b.posts.filter((p) => p.lang === lang).length);
    }
  }
});

test('sitemap.xml 覆盖全站页面与文章，robots.txt 指向 sitemap', () => {
  const sm = pub.files.get('sitemap.xml');
  const locs = [...sm.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  for (const f of fs.readdirSync(SITE).filter((x) => x.endsWith('.html') && x !== '404.html')) {
    assert.ok(locs.includes(ORIGIN + (f === 'index.html' ? '/' : '/' + f)), `sitemap 缺少 ${f}`);
  }
  for (const f of htmlFiles(pub)) assert.ok(locs.includes(ORIGIN + '/' + f.replace(/index\.html$/, '')), `sitemap 缺少 ${f}`);
  assert.equal(new Set(locs).size, locs.length, 'sitemap 有重复地址');
  for (const b of [all, fxPub, fxAll]) for (const p of b.posts) assert.ok(b.files.get('sitemap.xml').includes(`/${p.slug}/`));
  assert.match(fxPub.files.get('sitemap.xml'), /hreflang="en" href="https:\/\/deepsuck\.si\/blog\/en\/sample-post\/"/);
  assert.match(fs.readFileSync(path.join(SITE, 'robots.txt'), 'utf8'), /^Sitemap: https:\/\/deepsuck\.si\/sitemap\.xml$/m);
});

test('首页有克制的博客入口，语言切换跳到对应语言', () => {
  const html = fs.readFileSync(path.join(SITE, 'index.html'), 'utf8');
  const links = html.match(/<a [^>]*href="blog\/"[^>]*>/g) || [];
  assert.ok(links.length >= 3, '顶栏、菜单、页脚各一个');
  for (const a of links) { assert.match(a, /data-href-en="blog\/en\/"/); assert.match(a, /data-i18n="nav.blog"/); }
  assert.match(fs.readFileSync(path.join(SITE, 'assets/js/i18n.js'), 'utf8'), /'nav\.blog': 'Blog'/);
  for (const lang of ['zh', 'en']) {
    const idx = all.files.get(lang === 'zh' ? 'blog/index.html' : 'blog/en/index.html');
    assert.match(idx, new RegExp(`data-lang-switch="${lang === 'zh' ? 'en' : 'zh'}"`));
  }
});

test('文章源文件：不点名商业公司或产品（开源项目可写原名并列入致谢），不用 emoji，人设口径为现行四位、不写年龄道具', () => {
  const BANNED = /openai|deepseek|apate|chatgpt|anthropic|claude|gpt|qwen|通义|千问|dashscope|百炼|阿里|paraformer|cosyvoice|淘宝|微信|支付宝|\bQQ\b|腾讯|telegram|whatsapp|chrome|google|baidu|百度|bing|李大爷|周伯|老花镜|耳背|孙子/i;
  const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F000}-\u{1F2FF}]/u;
  for (const p of all.all) {
    const src = fs.readFileSync(path.join(ROOT, p.file), 'utf8');
    src.split('\n').forEach((l, i) => {
      assert.ok(!BANNED.test(l), `${p.file}:${i + 1}: ${l.match(BANNED)}`);
      assert.ok(!EMOJI.test(l), `${p.file}:${i + 1}: emoji`);
    });
  }
});

test('相对路径工具 rel()', () => {
  assert.equal(rel('/blog/', '/'), '../');
  assert.equal(rel('/blog/en/x/', '/assets/css/style.css'), '../../../assets/css/style.css');
  assert.equal(rel('/blog/en/', '/blog/'), '../');
  assert.equal(rel('/blog/', '/blog/'), './');
  assert.equal(rel('/blog/en/', '/?lang=en'), '../../?lang=en');
  assert.equal(rel('/blog/a/', '/blog/en/a/'), '../en/a/');
});
