# 博客源文件（content/blog/）

- `zh/<slug>.md` 是中文，`en/<slug>.md` 是英文；同名文件互为译文，页面用 hreflang 互链。slug 只用小写字母、数字和连字符。
- 页面由 `npm run blog`（`scripts/build-blog.js`）生成到 `site/blog/`，并重新生成 `site/sitemap.xml`；生成结果随 PR 一起提交，Pages 工作流不需要构建步骤。`npm test` 会检查生成结果是否和源文件同步、链接是否有效。
- 本地预览（含草稿）：`npm run blog:preview`，然后 `cd .blog-preview && python3 -m http.server 8081`，打开 http://localhost:8081/blog/ 。`.blog-preview/` 不入库。

frontmatter：

```yaml
---
title: 标题
description: 一两句摘要，用于列表、meta description、OG 与 RSS
date: 2026-10-19        # 发布日期
updated: 2026-10-20     # 可选，修改日期
draft: true             # 草稿：正式构建不输出（不出页面、RSS、sitemap）
tags: [技术, 语音]       # 可选
---
```

写作约定：不点名商业公司或产品；不用 emoji；人设不写年龄道具；数字只引用仓库里已有的文档或结果文件，并注明出处；话术类文章只写识别信号与应对，不复述可照搬的台词；引用公开来源只写来源类型。`tests/blog.test.js` 会检查其中能自动检查的部分。
