# 开源运营计划（docs/GROWTH.md）

> 2026-10-19 起草。本文只是计划和建议：**所有对外发帖、投稿、注册账号、修改仓库设置的动作都需负责人批准**，文中逐项标注。渠道规则查证于 2026-10-19，附原始链接；查不到原文的标「待核实」。
>
> **2026-10-19 负责人决定**：topics 与 Discussions 已定并执行（第 1.1、1.4 节）；网站统计暂不上（第 5 节）；投稿等 v0.4 全流程跑通后再议（第 3 节）。

## 0. 现状（2026-10-19 用 `gh repo view` 查询，已按负责人决定更新）

| 项 | 现状 |
|---|---|
| description | 开源中文 AI 反诈“拖住”机器人：陪诈骗分子聊天、浪费其时间并提取脱敏情报。Open-source Chinese anti-scam time-waster bot. |
| homepage | https://deepsuck.si |
| topics | `anti-fraud` `anti-scam` `chatbot` `chinese` `scambaiting` `fraud-prevention` `voice-ai`（原有 `qwen` 已去掉，见 #29） |
| Discussions | 已开启；四个分类（公告、问答、想法、Scam Script Leads（诈骗话术线索））已调整完成，欢迎帖已置顶（#30） |
| Releases / tags | 没有（`package.json` 版本 0.4.0，`CHANGELOG.md` 只有「未发布」） |
| README 徽章 | Pages 工作流、Tests 工作流、Apache-2.0、CC BY 4.0、stars |
| 标签 | 已有 `good first issue`、`help wanted`、`area:*`、`type:*`、`priority:*` |

## 1. 仓库优化

### 1.1 description 与 topics（topics 已定并执行；description 仍为建议）

description 建议加上情报库，中英各一句：

> 开源 AI 反诈“拖住”机器人：用受害人人设拖住骗子，提取脱敏诈骗情报，公开诈骗情报库。Open-source anti-scam time-waster bot with masked scam intel and a public intel library.

topics（GitHub 上限 20 个，全小写、连字符）：

**已执行（2026-10-19，#29）**：去掉 `qwen`，补上 `fraud-prevention`、`voice-ai`（`anti-scam`、`scambaiting`、`chinese` 原本就有），保留 `anti-fraud`、`chatbot`。`package.json` 的 `keywords` 去掉 `qwen`、`dashscope`（#34）。

以后可以再考虑的 topics（未执行，需负责人批准）：`honeypot` `threat-intelligence` `stix` `scam-detection` `webrtc` `data-redaction` `open-data`。

- 移除 `qwen` 的理由：项目公开文案约定不点名商业公司或产品（`tests/brand_copy.test.js`），topic 也是公开文案。
- `honeypot`、`threat-intelligence`、`stix` 对应情报库与 STIX 2.1 导出，便于安全研究者检索。

### 1.2 README 徽章

现有 4 个够用，保持克制。建议只补：

- `test` 工作流徽章（已加，#34）：`https://github.com/deepsucksi/deepsuck/actions/workflows/test.yml/badge.svg`；
- 首个 release 之后加版本徽章：`https://img.shields.io/github/v/release/deepsucksi/deepsuck?color=171c1f`；
- 博客上线后在链接行加「博客」与 RSS（`https://deepsuck.si/blog/feed.xml`）。

不建议加下载量、访问计数器这类第三方计数徽章（会向第三方暴露访客请求）。

### 1.3 good first issue 规范（已执行，#31）

规范已写进 [CONTRIBUTING.md 的「新人任务」](../CONTRIBUTING.md#新人任务good-first-issue)一节，以那里为准：范围小、不碰 `deploy/`、不需要云服务密钥、不碰人设台词和情报数据、本地 `npm test` 能验证、有联系人 48 小时内回复；同时打 `area:*` 标签，认领后两周没有进展改回 `help wanted`。

- 模板：`.github/ISSUE_TEMPLATE/good-first-issue.yml`（「新人任务」Issue Form，字段为背景、要做什么、涉及文件、怎么验证、完成标准、预估难度、联系人，自动加 `good first issue`）。
- 标签：`good first issue`、`help wanted` 均已存在。
- 题目优先选网站、文档和测试类的小问题（无障碍属性、文档链接、补测试），开之前先在仓库里核实问题确实存在。提取器、话术语料、人设台词这类改动需要项目背景，不作为新人任务。

### 1.4 Discussions（已开启，分类已调整完成）

负责人已定 4 个分类：公告、问答、想法、Scam Script Leads（诈骗话术线索）。GitHub API 不支持创建、改名或删除分类，已由维护者在仓库 Settings → Discussions 页面手动调整完成：

| 分类 | 格式 | 用途 |
|---|---|---|
| 公告 | 公告（仅维护者发帖） | 版本发布、博客更新、讨论规则 |
| 问答 | 问答（可标记答案） | 部署、自托管、使用问题 |
| 想法 | 开放讨论 | 新场景、新人设、新功能提议，成熟后转 issue |
| Scam Script Leads（诈骗话术线索） | 开放讨论 | 脱敏后的话术和套路，用 `.github/DISCUSSION_TEMPLATE/scam-script-leads.yml` 模板，[分类入口](https://github.com/deepsucksi/deepsuck/discussions/categories/scam-script-leads) |

- 模板文件名须与分类 slug 一致：已核对，slug 为 `scam-script-leads`（GraphQL `discussionCategories { name slug }`）。
- **坑：分类显示名必须保持英文 Scam Script Leads**（描述可以是中文）。slug 由显示名生成，中文显示名会得到中文 slug，中文 slug 下发帖表单模板不生效。该分类原名「诈骗话术线索」，已在网页上改名修复（负责人已批准）；以后不要把分类名改回中文，改名后也要同步核对 slug 与模板文件名。
- 公告分类已置顶欢迎帖「讨论区规则：先读这一条」（https://github.com/deepsucksi/deepsuck/discussions/69），要点：禁止发布真实个人信息，只提交脱敏后的话术和套路；遇到诈骗先拨 110 / 96110。
- 结构化情报提交与申诉仍然只走 Issue 模板（IssueOps 工作流依赖它），Discussions 里的线索只作讨论素材。

## 2. 发布节奏与 release notes

- **版本号**：沿用 `package.json` 的 0.x 语义化版本。新功能 / 新场景 / 新数据格式升次版本（0.4 → 0.5），只修 bug 升修订号。
- **节奏**：每月一个次版本，月底发布；有安全或脱敏相关修复时随时发修订版。里程碑与版本对齐（当前 `v0.4 全流程跑通`、`v0.5 电话接入`）。
- **流程**：`CHANGELOG.md` 的「未发布」整理成版本小节 → PR 审核 → 维护者在 main 上打 tag `v0.4.0` → 用下面的模板创建 GitHub Release。打 tag 和发 Release 由负责人操作。
- **博客**：每个次版本配一篇短文（中文为主、附英文），重点讲一项改动和它的实测数据。

release notes 模板：

```markdown
## DeepSuck v0.X.0（YYYY-MM-DD）

一句话：这一版最重要的变化。

### 新增
- ……（#issue）

### 改进
- ……，实测数据：……（出处：docs/xxx.md / eval/results-xxx.json）

### 修复
- ……（Fixes #N）

### 数据与隐私
- 脱敏规则、留存策略、情报库发布策略是否有变化；没有就写「无变化」。

### 升级说明
- 自托管：`cd /opt/deepsuck && git pull && cd deploy && docker compose up -d --build`
- 新增或改名的环境变量：……

### 致谢
- @贡献者

完整变更见 CHANGELOG.md。遇到诈骗请拨打 110 / 96110。
```

## 3. 投稿与分享渠道（全部需负责人批准，用负责人自己的账号）

**已定（2026-10-19）：投稿等 v0.4 全流程跑通后再议。** 下表只作为届时的参考，现在不投任何渠道。

原则：先上线可试用的内容（沙盒、语音演示、情报库、博客）再投稿；每个渠道只发一次首发帖，之后只在有实质更新时再发；不刷票、不找人点赞；帖子写清项目只做防御、不主动联系真人。

| 渠道 | 类型 | 规则要点（查证于 2026-10-19） | 适合发什么 | 状态 |
|---|---|---|---|---|
| Hacker News · Show HN | 英文开发者社区 | 必须是别人能直接试用的东西，博客文章、注册页、列表不算 Show HN；标题以 "Show HN" 开头；不要请朋友点赞或评论；小版本更新一般不够格。[规则](https://news.ycombinator.com/showhn.html) | 沙盒（无需注册即可试用）+ 仓库链接；作者需在帖子下及时回复 | 需负责人批准 |
| V2EX ·「分享创造」节点 | 中文开发者社区 | 节点欢迎独立开发者发布新作；营销内容须发「推广」节点，否则会被移动，屡次忽略影响账号。[节点说明](https://www.v2ex.com/help/node)。社区帖子反映新账号要满 30 天才能在「分享创造」发帖（[帖子](https://www.v2ex.com/t/1175853)，待核实为官方规则） | 写设计思路、踩坑和数据，不只丢链接 | 需负责人批准 |
| HelloGitHub 月刊 | 中文开源项目月刊 | 每月 28 号发布；推荐或自荐入口在 [hellogithub.com/periodical](https://hellogithub.com/periodical)（[README](https://github.com/521xueweihan/HelloGitHub)）；自荐需填类别、标题、原创描述和亮点，审核看文档完整度、项目价值、入门友好度（[审核标准讨论](https://github.com/521xueweihan/HelloGitHub/issues/271)，具体字数要求待核实） | 仓库 + 一段 32–256 字的项目描述 | 需负责人批准（可能需要登录） |
| 科技爱好者周刊 | 中文技术周刊 | 每周五发布；README 写明「欢迎投稿文章/软件/资源，请提交 issue」（[README](https://github.com/ruanyf/weekly)）。第 412 期标题为「禁止 issue，只用 PR」，投稿方式是否变化待核实 | 项目或博客技术文章 | 需负责人批准 |
| awesome-honeypots | awesome 列表 | 先搜重复；每条一个 PR；格式 `[名称](链接) - 描述.`，描述以句号结尾。[CONTRIBUTING](https://github.com/paralax/awesome-honeypots/blob/master/CONTRIBUTING.md) | 「对话式蜜罐 / 诈骗拖延机器人」一条 | 需负责人批准 |
| awesome-threat-intelligence | awesome 列表 | 不重复；每条一个 PR；遵守表格格式；PR 与提交标题要有意义。[CONTRIBUTING](https://github.com/hslatman/awesome-threat-intelligence/blob/main/CONTRIBUTING.md) | 公开诈骗情报库与 STIX 2.1 订阅源（数据 CC BY 4.0） | 需负责人批准 |
| sindresorhus/awesome | awesome 总表 | 只收「列表」本身，要求列表存在满 30 天、通过 awesome-lint、提交者先评审 4 个其他 PR 等。[PR 模板](https://github.com/sindresorhus/awesome/blob/main/pull_request_template.md) | 不适用（DeepSuck 不是列表） | 不投 |
| Reddit r/opensource 等 | 英文社区 | 规则页抓取被拦截，待核实 | — | 待核实 |
| 掘金、SegmentFault、开源中国 | 中文开发者社区 | 未查到投稿规则原文，待核实 | 技术拆解文章转载（注明原文链接与许可） | 待核实 |
| Lobsters | 英文开发者社区 | 邀请制，待核实 | — | 待核实 |

## 4. 搜索引擎收录

博客 PR 已经提供：自动生成的 `site/sitemap.xml`（全站页面 + 已发布文章，带 hreflang）、`site/robots.txt` 里的 `Sitemap:` 行、每篇文章的 canonical、OG / Twitter 卡片与 JSON-LD。站点验证需要账号，**由负责人登录各平台获取验证文件或 meta**，再开 PR 放进仓库。不要编造或复用他人的验证码。

| 平台 | 可用验证方式（官方说明） | 放在哪里 | 谁去拿 |
|---|---|---|---|
| Google Search Console | HTML 文件上传、HTML 标签 `<meta name="google-site-verification" content="…">`、DNS TXT（域名资源只能用 DNS）。[说明](https://support.google.com/webmasters/answer/9008080) | 文件放 `site/` 根目录（Pages 会原样发布）；meta 放 `site/index.html` 的 `<head>`；DNS TXT 加在 deepsuck.si 的域名解析里 | 负责人（需账号） |
| Bing Webmaster Tools | `BingSiteAuth.xml` 文件、`<meta name="msvalidate.01" content="…">`、DNS CNAME；或从已验证的 Google Search Console 导入（自动验证并导入 sitemap）。[说明](https://www.bing.com/webmasters/help/add-and-verify-site-12184f8b) | 同上 | 负责人（需账号） |
| 百度搜索资源平台 | 文件验证（形如 `baidu_verify_codeva-…html`，放根目录）、HTML 标签验证（`<meta name="baidu-site-verification" content="…">`）；CNAME 验证已暂停。[官方手册](https://ziyuan.baidu.com/college/courseinfo?id=267) | 同上 | 负责人（需账号）；另注意 #16 大陆访问问题会影响百度抓取 |

- 验证完成后提交 `https://deepsuck.si/sitemap.xml`。验证文件、meta 要一直保留，平台会定期复查。
- 可选（建议，需负责人拍板）：IndexNow 协议不需要账号，只需在站点根目录放一个密钥文件，发布后向接口推送新 URL；参与方包括 Bing 等，不包括 Google。[说明](https://www.indexnow.org/documentation)。引入它等于新增一次对外请求，作为建议列出。

## 5. 指标

每月初在 Discussions 公告或内部记录里更新一次，只记数字和来源，不记访客个人信息。

| 指标 | 来源 | 工具与做法 | 备注 |
|---|---|---|---|
| Star、fork、watcher | GitHub API | `gh api repos/deepsucksi/deepsuck --jq '{stars:.stargazers_count,forks:.forks_count,watchers:.subscribers_count}'` | 2026-10-19 为 1 star |
| 仓库访问与克隆 | GitHub traffic API | `gh api repos/deepsucksi/deepsuck/traffic/views`、`/traffic/clones`、`/traffic/popular/referrers`；需要推送权限，**只保留最近 14 天**。[文档](https://docs.github.com/en/rest/metrics/traffic) | 想留长期数据，需要每天快照；建议加一个定时工作流把结果提交到单独分支，需负责人批准 |
| 网站访问量 | 暂不统计 | **已定（2026-10-19）：统计工具暂不上。** deepsuck.si 在大陆可以访问，但 VPS 从大陆连不通，自托管统计会丢掉大陆访客的数据。网站相关的指标先看 GitHub traffic 和各搜索平台后台的数据 | 不引入任何第三方托管统计 |
| 语音演示使用量 | 自有服务 | live.deepsuck.si 的 `stats.json` 计数与通话追踪（只计数，不含内容） | 已有 |
| 收录数 | 各搜索平台后台 | Google Search Console「网页索引」、Bing「网站资源管理器」、百度「索引量」 | 依赖第 4 节的验证；`site:deepsuck.si` 搜索结果只作粗略参考 |
| 社区参与 | GitHub | 新 issue / PR 数、外部贡献者数、`good first issue` 关闭数、Discussions 帖子数（`gh issue list`、`gh pr list --search`） | |
| 订阅 | RSS | 静态站无法统计订阅数，暂不统计 | |

## 6. 需负责人拍板 / 批准的事项

已定（2026-10-19）：

- topics（第 1.1 节）：已执行；`package.json` keywords 已随 #34 合入。
- Discussions（第 1.4 节）：已开启，四个分类（公告、问答、想法、Scam Script Leads（诈骗话术线索））已调整完成，欢迎帖 https://github.com/deepsucksi/deepsuck/discussions/69 已置顶。
- 网站统计（第 5 节）：暂不上。
- 投稿（第 3 节）：v0.4 全流程跑通后再议。

仍待拍板：

1. 仓库 description 是否按第 1.1 节改。
2. 发布节奏、首个 tag 与 Release（第 2 节）。
3. 三个搜索平台的账号与验证（第 4 节），是否使用 IndexNow。
4. 是否加 GitHub traffic 每日快照工作流（第 5 节）。
