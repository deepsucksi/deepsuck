#!/usr/bin/env node
/*!
 * DeepSuck — scripts/build-blog.js：content/blog/{zh,en}/*.md → site/blog/ 静态页 + RSS，并重新生成 site/sitemap.xml。Apache-2.0
 *
 *   npm run blog                 生成正式内容（不含草稿），写入 site/blog/ 与 site/sitemap.xml，结果随仓库提交
 *   npm run blog:check           只比对：生成结果与仓库里的文件不一致就退出 1（tests/blog.test.js 也会检查）
 *   npm run blog:preview         含草稿的本地预览：复制 site/ 到 .blog-preview/ 再生成，草稿页带「草稿」标记和 noindex
 *
 * 约定：
 * - 文章是 content/blog/<语言>/<slug>.md，开头是 frontmatter（title / description / date 必填，updated、draft 可选）。
 *   中英文同名文件互为译文，页面用 hreflang 互链；只有一边时语言切换回到另一语言的博客首页。
 * - draft: true 的文章在正式构建中不输出（不出页面、不进 RSS 与 sitemap）。
 * - Markdown 由随仓库附带的 marked（scripts/vendor/marked，MIT）转换；不联网、无 npm 依赖，输出是确定的。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { marked } = require('./vendor/marked/marked.cjs');

const ROOT = path.resolve(__dirname, '..');
const LANGS = ['zh', 'en'];

const T = {
  zh: {
    htmlLang: 'zh-CN', hreflang: 'zh-CN', locale: 'zh_CN', base: '/blog/',
    blog: '博客', blogTitle: 'DeepSuck 博客', blogDesc: 'DeepSuck 开源反诈项目的笔记：项目进展、技术拆解与诈骗识别。',
    empty: '文章即将发布', emptyNote: '第一批文章正在审校。订阅 RSS，文章发布后会出现在你的阅读器里。', subscribe: '订阅 RSS', home: '首页', intel: '情报库', demo: '进入沙盒', menu: '菜单', skip: '跳到正文', nav: '主导航', pageNav: '页面导航',
    other: 'EN', otherName: 'English', readOther: 'Read in English', back: '返回博客', draft: '草稿 · 未发布', rss: 'RSS 订阅',
    foot: 'DeepSuck · 代码 Apache-2.0 · 仅用于防诈研究与教育', foot110: '遇到诈骗请拨打 110 / 96110', published: '发布于', updated: '更新于',
  },
  en: {
    htmlLang: 'en', hreflang: 'en', locale: 'en_US', base: '/blog/en/',
    blog: 'Blog', blogTitle: 'DeepSuck Blog', blogDesc: 'Notes from the DeepSuck open-source anti-scam project: progress, technical write-ups and scam-recognition guides.',
    empty: 'Articles coming soon', emptyNote: 'The first articles are in review. Subscribe to the RSS feed and they will show up in your reader once published.', subscribe: 'Subscribe via RSS', home: 'Home', intel: 'Intel library', demo: 'Try the sandbox', menu: 'Menu', skip: 'Skip to content', nav: 'Main navigation', pageNav: 'Page navigation',
    other: '中文', otherName: '中文', readOther: 'Read in Chinese', back: 'Back to blog', draft: 'Draft · unpublished', rss: 'RSS feed',
    foot: 'DeepSuck · Code Apache-2.0 · For anti-fraud research and education only', foot110: 'Scam? Call 110 / 96110 (China)', published: 'Published', updated: 'Updated',
  },
};
const OTHER = { zh: 'en', en: 'zh' };

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function jsonLd(obj) {
  return JSON.stringify(obj).replace(/</g, '\\u003c');
}

// ---- frontmatter：只支持扁平的 key: value（字符串、true/false、[a, b] 列表），够用即可 ----
function parseFrontmatter(src, file) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  if (!m) throw new Error(`${file}: 缺少 frontmatter（文件开头用 --- 包起来）`);
  const data = {};
  for (const line of m[1].split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    const kv = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    if (!kv) throw new Error(`${file}: 无法解析 frontmatter 行：${line}`);
    let v = kv[2].trim();
    if (v === 'true' || v === 'false') v = v === 'true';
    else if (/^\[.*\]$/.test(v)) v = v.slice(1, -1).split(',').map((x) => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
    else if (/^".*"$/.test(v)) v = JSON.parse(v);
    else if (/^'.*'$/.test(v)) v = v.slice(1, -1);
    data[kv[1]] = v;
  }
  return { data, body: src.slice(m[0].length) };
}

function loadPosts(root) {
  const posts = [];
  for (const lang of LANGS) {
    const dir = path.join(root, 'content', 'blog', lang);
    if (!fs.existsSync(dir)) continue;
    for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.md')).sort()) {
      const file = path.join('content', 'blog', lang, f);
      const slug = f.slice(0, -3);
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || slug === 'en') throw new Error(`${file}: 文件名（slug）只能用小写字母、数字和连字符，且不能是 en`);
      const { data, body } = parseFrontmatter(fs.readFileSync(path.join(root, file), 'utf8'), file);
      for (const k of ['title', 'description', 'date']) if (!data[k] || typeof data[k] !== 'string') throw new Error(`${file}: frontmatter 缺少 ${k}`);
      for (const k of ['date', 'updated']) if (data[k] !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(data[k])) throw new Error(`${file}: ${k} 须为 YYYY-MM-DD`);
      if (data.draft !== undefined && typeof data.draft !== 'boolean') throw new Error(`${file}: draft 只能是 true 或 false`);
      posts.push({ lang, slug, file, title: data.title, description: data.description, date: data.date, updated: data.updated || data.date,
        draft: data.draft === true, tags: Array.isArray(data.tags) ? data.tags : [], body });
    }
  }
  return posts;
}

// ---- URL 工具 ----
function postPath(p) { return T[p.lang].base + p.slug + '/'; }
function rel(from, to) {
  const fromDir = from.endsWith('/') ? from : path.posix.dirname(from) + '/';
  const [toPath, suffix = ''] = to.split(/(?=[?#])/);
  let r = path.posix.relative(fromDir, toPath);
  if (toPath.endsWith('/') && r) r += '/';
  return (r || './') + suffix;
}

function renderMarkdown(md) {
  const html = marked.parse(md, { gfm: true, async: false });
  return html.replace(/<table>/g, '<div class="table-scroll"><table>').replace(/<\/table>/g, '</table></div>');
}

const GH_ICON = '<svg class="github-mark" aria-hidden="true" focusable="false" fill="currentColor" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><path d="M6.766 11.328c-2.063-.25-3.516-1.734-3.516-3.656 0-.781.281-1.625.75-2.188-.203-.515-.172-1.609.063-2.062.625-.078 1.468.25 1.968.703.594-.187 1.219-.281 1.985-.281.765 0 1.39.094 1.953.265.484-.437 1.344-.765 1.969-.687.218.422.25 1.515.046 2.047.5.593.766 1.39.766 2.203 0 1.922-1.453 3.375-3.547 3.64.531.344.89 1.094.89 1.954v1.625c0 .468.391.734.86.547C13.781 14.359 16 11.53 16 8.03 16 3.61 12.406 0 7.984 0 3.563 0 0 3.61 0 8.031a7.88 7.88 0 0 0 5.172 7.422c.422.156.828-.125.828-.547v-1.25c-.219.094-.5.156-.75.156-1.031 0-1.64-.562-2.078-1.609-.172-.422-.36-.672-.719-.719-.187-.015-.25-.093-.25-.187 0-.188.313-.328.625-.328.453 0 .844.281 1.25.86.313.452.64.655 1.031.655s.641-.14 1-.5c.266-.265.47-.5.657-.656"/></svg>';

function layout({ lang, urlPath, title, description, ogType, alternates, otherHref, head = '', body, draft }) {
  const t = T[lang];
  const site = SITE;
  const r = (to) => rel(urlPath, to);
  const homeHref = lang === 'en' ? r('/?lang=en') : r('/');
  const canonical = site.origin + urlPath;
  const og = site.origin + site.ogImage;
  const alt = alternates.map((a) => `<link rel="alternate" hreflang="${a.hreflang}" href="${site.origin + a.path}">`).join('\n');
  const otherLang = OTHER[lang];
  return `<!doctype html>
<html lang="${t.htmlLang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
${draft ? '<meta name="robots" content="noindex">\n' : ''}<link rel="canonical" href="${canonical}">
${alt}
<link rel="alternate" type="application/rss+xml" title="${esc(t.blogTitle)}" href="${site.origin + t.base}feed.xml">
<meta property="og:type" content="${ogType}">
<meta property="og:site_name" content="DeepSuck">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${og}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="${esc(title)}">
<meta property="og:locale" content="${t.locale}">
<meta property="og:locale:alternate" content="${T[otherLang].locale}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(title)}">
<meta name="twitter:description" content="${esc(description)}">
<meta name="twitter:image" content="${og}">
<meta name="theme-color" content="#ffffff">
${head}<link rel="icon" href="${r('/assets/brand/favicon-32.png')}" type="image/png" sizes="32x32">
<link rel="icon" href="${r('/favicon.ico')}" sizes="48x48">
<link rel="apple-touch-icon" href="${r('/assets/brand/favicon-180.png')}" sizes="180x180">
<link rel="manifest" href="${r('/site.webmanifest')}">
<link rel="stylesheet" href="${r('/assets/css/style.css')}">
<link rel="stylesheet" href="${r('/assets/css/blog.css')}">
</head>
<body class="blog">
<a class="skip-link" href="#main">${t.skip}</a>
<header class="topbar">
  <div class="wrap">
    <a class="brand" href="${homeHref}" aria-label="DeepSuck"><span class="brand-symbol"><img src="${r('/assets/brand/on-hold-mono-96.png')}" alt="" width="96" height="96"></span><img class="brand-wordmark" src="${r('/assets/brand/wordmark.svg')}" alt="DeepSuck" width="146" height="40"></a>
    <nav class="nav" aria-label="${t.nav}">
      <a class="hide-m" href="${homeHref}">${t.home}</a>
      <a class="hide-m" href="${r('/intel.html')}">${t.intel}</a>
      <a class="hide-m" href="${r(t.base)}" aria-current="page">${t.blog}</a>
      <a class="btn small ghost hide-xs lang-toggle" href="${otherHref}" hreflang="${T[otherLang].hreflang}" lang="${T[otherLang].htmlLang}" data-lang-switch="${otherLang}">${t.other}</a>
      <a class="hide-m nav-source" href="https://github.com/deepsucksi/deepsuck" target="_blank" rel="noopener">${GH_ICON}<span>GitHub</span> ↗</a>
      <a class="btn small primary" href="${r('/demo.html')}">${t.demo}</a>
    </nav>
    <details class="menu">
      <summary class="btn small">${t.menu}</summary>
      <nav class="menu-panel" aria-label="${t.pageNav}">
        <a href="${homeHref}">${t.home}</a>
        <a href="${r('/intel.html')}">${t.intel}</a>
        <a href="${r(t.base)}" aria-current="page">${t.blog}</a>
        <a href="${r('/demo.html')}">${t.demo}</a>
        <a class="mobile-source" href="https://github.com/deepsucksi/deepsuck" target="_blank" rel="noopener">${GH_ICON}<span>GitHub ↗</span></a>
        <a class="menu-lang lang-toggle" href="${otherHref}" hreflang="${T[otherLang].hreflang}" lang="${T[otherLang].htmlLang}" data-lang-switch="${otherLang}">${t.otherName}</a>
      </nav>
    </details>
  </div>
</header>

<main id="main" class="wrap blog-page">
${body}
</main>

<footer>
  <div class="wrap">
    <span>${t.foot}</span>
    <span>${t.foot110}</span>
    <a href="${homeHref}">${t.home}</a>
    <a href="${r('/intel.html')}">${t.intel}</a>
    <a href="${r(t.base)}">${t.blog}</a>
    <a href="${r(t.base + 'feed.xml')}">${t.rss}</a>
    <a href="https://github.com/deepsucksi/deepsuck" target="_blank" rel="noopener">GitHub</a>
  </div>
</footer>
<script src="${r('/assets/js/blog.js')}"></script>
</body>
</html>
`;
}

function fmtDate(d, lang) {
  if (lang === 'zh') { const [y, m, dd] = d.split('-'); return `${y} 年 ${+m} 月 ${+dd} 日`; }
  const M = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const [y, m, dd] = d.split('-'); return `${M[+m - 1]} ${+dd}, ${y}`;
}
function rfc822(d) { return new Date(d + 'T00:00:00+08:00').toUTCString(); }

function counterpart(p, list) { return list.find((q) => q.slug === p.slug && q.lang === OTHER[p.lang]); }

function renderPost(p, list) {
  const t = T[p.lang];
  const urlPath = postPath(p);
  const other = counterpart(p, list);
  const alternates = [{ hreflang: t.hreflang, path: urlPath }];
  if (other) alternates.push({ hreflang: T[other.lang].hreflang, path: postPath(other) });
  if (other) { const zh = p.lang === 'zh' ? p : other; alternates.push({ hreflang: 'x-default', path: postPath(zh) }); }
  const otherHref = rel(urlPath, other ? postPath(other) : T[OTHER[p.lang]].base);
  const ld = {
    '@context': 'https://schema.org', '@type': 'BlogPosting',
    headline: p.title, description: p.description, inLanguage: t.htmlLang,
    datePublished: p.date, dateModified: p.updated, url: SITE.origin + urlPath,
    mainEntityOfPage: { '@type': 'WebPage', '@id': SITE.origin + urlPath },
    image: [SITE.origin + SITE.ogImage],
    author: { '@type': 'Organization', name: 'DeepSuck contributors', url: 'https://github.com/deepsucksi/deepsuck' },
    publisher: { '@type': 'Organization', name: 'DeepSuck', url: SITE.origin + '/', logo: { '@type': 'ImageObject', url: SITE.origin + '/assets/brand/favicon-180.png' } },
    isPartOf: { '@type': 'Blog', '@id': SITE.origin + t.base, name: t.blogTitle },
  };
  if (p.tags.length) ld.keywords = p.tags;
  const head = `<meta property="article:published_time" content="${p.date}">\n<meta property="article:modified_time" content="${p.updated}">\n<script type="application/ld+json">${jsonLd(ld)}</script>\n`;
  const meta = `<time datetime="${p.date}">${t.published} ${fmtDate(p.date, p.lang)}</time>` + (p.updated !== p.date ? ` · <time datetime="${p.updated}">${t.updated} ${fmtDate(p.updated, p.lang)}</time>` : '');
  const body = `<article class="post">
  <header class="post-head">
    <p class="post-kicker"><a href="${rel(urlPath, t.base)}">${t.blog}</a>${p.draft ? ` <span class="tag amber">${t.draft}</span>` : ''}</p>
    <h1>${esc(p.title)}</h1>
    <p class="lead">${esc(p.description)}</p>
    <p class="post-meta">${meta}</p>
  </header>
  <div class="prose">
${renderMarkdown(p.body).trim()}
  </div>
  <footer class="post-foot">
    <a href="${rel(urlPath, t.base)}">← ${t.back}</a>${other ? `\n    <a href="${otherHref}" hreflang="${T[other.lang].hreflang}" lang="${T[other.lang].htmlLang}" data-lang-switch="${other.lang}">${t.readOther}</a>` : ''}
  </footer>
</article>`;
  return layout({ lang: p.lang, urlPath, title: `${p.title} · DeepSuck`, description: p.description, ogType: 'article', alternates, otherHref, head, body, draft: p.draft });
}

function renderIndex(lang, list) {
  const t = T[lang];
  const urlPath = t.base;
  const posts = list.filter((p) => p.lang === lang);
  const alternates = [{ hreflang: 'zh-CN', path: T.zh.base }, { hreflang: 'en', path: T.en.base }, { hreflang: 'x-default', path: T.zh.base }];
  const ld = { '@context': 'https://schema.org', '@type': 'Blog', name: t.blogTitle, description: t.blogDesc, url: SITE.origin + urlPath, inLanguage: t.htmlLang,
    publisher: { '@type': 'Organization', name: 'DeepSuck', url: SITE.origin + '/' },
    blogPost: posts.map((p) => ({ '@type': 'BlogPosting', headline: p.title, url: SITE.origin + postPath(p), datePublished: p.date })) };
  const items = posts.map((p) => `    <li class="post-item">
      <time datetime="${p.date}">${p.date}</time>
      <div>
        <h2><a href="${rel(urlPath, postPath(p))}">${esc(p.title)}</a>${p.draft ? ` <span class="tag amber">${t.draft}</span>` : ''}</h2>
        <p>${esc(p.description)}</p>
      </div>
    </li>`).join('\n');
  const body = `<div class="blog-hero">
  <h1>${t.blog}</h1>
  <p class="lead">${esc(t.blogDesc)}</p>
</div>
${posts.length ? `<ol class="post-list" reversed>\n${items}\n  </ol>
<p class="blog-feed"><a href="feed.xml">${t.rss}</a></p>` : `<section class="blog-empty" aria-labelledby="blog-empty-title">
  <h2 id="blog-empty-title">${t.empty}</h2>
  <p>${esc(t.emptyNote)}</p>
  <p class="blog-empty-actions"><a class="btn small" href="feed.xml" type="application/rss+xml">${t.subscribe}</a></p>
</section>`}`;
  return layout({ lang, urlPath, title: `${t.blogTitle}`, description: t.blogDesc, ogType: 'website', alternates, otherHref: rel(urlPath, T[OTHER[lang]].base),
    head: `<script type="application/ld+json">${jsonLd(ld)}</script>\n`, body, draft: false });
}

function renderFeed(lang, list) {
  const t = T[lang];
  const posts = list.filter((p) => p.lang === lang);
  const newest = posts.length ? posts.map((p) => p.updated).sort().pop() : null;
  const items = posts.map((p) => {
    const url = SITE.origin + postPath(p);
    const html = renderMarkdown(p.body).replace(/]]>/g, ']]&gt;');
    return `  <item>
    <title>${esc(p.title)}</title>
    <link>${url}</link>
    <guid isPermaLink="true">${url}</guid>
    <pubDate>${rfc822(p.date)}</pubDate>
    <description>${esc(p.description)}</description>
    <content:encoded><![CDATA[${html}]]></content:encoded>
  </item>`;
  }).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>${esc(t.blogTitle)}</title>
  <link>${SITE.origin + t.base}</link>
  <description>${esc(t.blogDesc)}</description>
  <language>${t.htmlLang}</language>
  <atom:link href="${SITE.origin + t.base}feed.xml" rel="self" type="application/rss+xml"/>
${newest ? `  <lastBuildDate>${rfc822(newest)}</lastBuildDate>\n` : ''}${items ? items + '\n' : ''}</channel>
</rss>
`;
}

function renderSitemap(list) {
  const u = (loc, lastmod, changefreq, priority, alts = []) => `  <url><loc>${SITE.origin + loc}</loc>${alts.map((a) => `<xhtml:link rel="alternate" hreflang="${a.hreflang}" href="${SITE.origin + a.path}"/>`).join('')}<lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`;
  const rows = SITE.pages.map((p) => u(p.path, p.lastmod, p.changefreq, p.priority));
  const idxAlts = [{ hreflang: 'zh-CN', path: T.zh.base }, { hreflang: 'en', path: T.en.base }, { hreflang: 'x-default', path: T.zh.base }];
  for (const lang of LANGS) {
    const own = list.filter((p) => p.lang === lang).map((p) => p.updated);
    rows.push(u(T[lang].base, [SITE.blogLastmod, ...own].sort().pop(), 'weekly', '0.6', idxAlts));
  }
  for (const p of list) {
    const other = counterpart(p, list);
    const alts = other ? [{ hreflang: T[p.lang].hreflang, path: postPath(p) }, { hreflang: T[other.lang].hreflang, path: postPath(other) }] : [];
    rows.push(u(postPath(p), p.updated, 'monthly', '0.7', alts));
  }
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${rows.join('\n')}
</urlset>
`;
}

let SITE;
/** 生成全部文件，返回 Map<相对 site/ 的路径, 内容>。drafts=true 时包含草稿。 */
function build({ root = ROOT, drafts = false } = {}) {
  SITE = JSON.parse(fs.readFileSync(path.join(root, 'content', 'blog', 'site.json'), 'utf8'));
  const all = loadPosts(root);
  const list = all.filter((p) => drafts || !p.draft).sort((a, b) => (b.date + b.slug).localeCompare(a.date + a.slug));
  const files = new Map();
  for (const lang of LANGS) {
    const dir = lang === 'zh' ? 'blog' : 'blog/en';
    files.set(`${dir}/index.html`, renderIndex(lang, list));
    files.set(`${dir}/feed.xml`, renderFeed(lang, list));
  }
  for (const p of list) files.set(`${p.lang === 'zh' ? 'blog' : 'blog/en'}/${p.slug}/index.html`, renderPost(p, list));
  files.set('sitemap.xml', renderSitemap(list));
  return { files, posts: list, all };
}

function listFiles(dir, base = dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? listFiles(p, base) : [path.relative(base, p).split(path.sep).join('/')];
  });
}

/** 与磁盘上 site/ 的内容比对，返回不一致的路径列表（缺失、多余、内容不同）。 */
function diff(files, siteDir = path.join(ROOT, 'site')) {
  const out = [];
  const onDisk = new Set(listFiles(path.join(siteDir, 'blog')).map((f) => 'blog/' + f));
  for (const [f, content] of files) {
    const p = path.join(siteDir, f);
    if (!fs.existsSync(p)) out.push('缺少 ' + f);
    else if (fs.readFileSync(p, 'utf8') !== content) out.push('过期 ' + f);
    onDisk.delete(f);
  }
  for (const f of onDisk) out.push('多余 ' + f);
  return out;
}

function write(files, outDir) {
  fs.rmSync(path.join(outDir, 'blog'), { recursive: true, force: true });
  for (const [f, content] of files) {
    const p = path.join(outDir, f);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, content);
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const drafts = args.includes('--drafts');
  const outIdx = args.indexOf('--out');
  const out = outIdx >= 0 ? path.resolve(args[outIdx + 1]) : path.join(ROOT, 'site');
  const { files, posts, all } = build({ drafts });
  if (args.includes('--check')) {
    const d = diff(files);
    if (d.length) { console.error('site/blog 与 content/blog 不同步，请运行 npm run blog：\n  ' + d.join('\n  ')); process.exit(1); }
    console.log(`blog: 已同步（${posts.length} 篇已发布，${all.length - posts.length} 篇草稿未输出）`);
    process.exit(0);
  }
  if (drafts && out === path.join(ROOT, 'site')) { console.error('含草稿的构建不能写进 site/，请加 --out <目录>（npm run blog:preview）'); process.exit(1); }
  if (out !== path.join(ROOT, 'site')) {
    fs.rmSync(out, { recursive: true, force: true });
    fs.cpSync(path.join(ROOT, 'site'), out, { recursive: true, filter: (src) => !src.includes(path.join('site', 'data', 'blocklist')) });
  }
  write(files, out);
  console.log(`blog: ${posts.length} 篇${drafts ? '（含草稿）' : ''} → ${path.relative(ROOT, out) || '.'}/blog/，sitemap.xml 已更新`);
}

module.exports = { build, diff, parseFrontmatter, rel, T };
