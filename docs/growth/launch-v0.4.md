# v0.4 发布与增长方案（草稿）

> 2026-10-21 起草，供负责人审。发布日 2026-10-26（周一）。本文只是方案：**所有对外发帖、投稿、注册账号、修改仓库设置都需负责人批准，并由负责人用自己的账号操作**。渠道规则沿用 [GROWTH.md 第 3 节](../GROWTH.md#3-投稿与分享渠道全部需负责人批准用负责人自己的账号)的查证结果，没核实的标「待核实」。
>
> 时间均为北京时间（UTC+8）。

## 0. 边界（所有文案都适用）

- 面向读者的文字不点名任何商用模型或厂商，统一说「云端大模型 API（兼容标准聊天接口）」。
- 项目只做防御、研究与教育：机器人不主动联系任何真实的人；演示里由访客自己扮演骗子。文案里不鼓励、不教人去主动“钓”真实骗子。
- 不提供接入电话卡、号码或接卡方式；不公开 SIP 地址、分机账号或任何凭证。提到 SIP 时只说「可自托管的 SIP 软电话演示，只接不拨」，细节指向仓库文档。
- 情报库目前 18 条**全部是示例数据**（`site/data/intel.json` 的 `notice`），文案里不能说成“已收录 N 条真实情报”。
- 不刷票、不找人点赞或评论；每个渠道只发一次首发帖，之后只在有实质更新时再发。

## 1. 外部现状（2026-10-21 用 gh 核实）

| 项 | 数值 | 命令 |
|---|---|---|
| Star | **1**（不是 0；唯一的 stargazer 为外部账号） | `gh api repos/deepsucksi/deepsuck -q .stargazers_count` |
| Fork | 0 | `.forks_count` |
| Watcher | 1 | `.subscribers_count` |
| 外部提交的 issue | 0（open_issues_count 为 47，全部是维护者自己开的 issue/PR） | `gh api 'search/issues?q=repo:deepsucksi/deepsuck+type:issue+-author:deepsucksi' -q .total_count` |
| 仓库访问（近 14 天） | 36 次 / 4 个独立访客 | `gh api repos/deepsucksi/deepsuck/traffic/views` |
| 网站访问 | 无数据（统计见 #231 / #232，部署后才有） | — |

结论：基本是冷启动，v0.4 是第一次对外露面，发布前要把“能直接试用”的入口打磨好，而不是先铺渠道。

## 2. 能拿出来的东西（都已在仓库里，可直接引用）

| 亮点 | 在哪 | 适合的渠道 |
|---|---|---|
| 沙盒：你扮演骗子，4 个受害人人设（01 王阿姨 · 退休老人、02 小陈妈妈 · 宝妈、03 小林 · 刚毕业学生、04 郑老板 · 个体小老板）× 7 个高发诈骗场景，纯浏览器规则引擎，零成本、无需注册 | https://deepsuck.si/demo.html | 全部 |
| 23 种拖延与诱导策略、19 类话术识别和 0–100 风险评分，结束后出情报看板和脱敏 JSON 报告 | README「功能」 | 开发者社区 |
| 情报提取 + 默认脱敏：银行卡（开户行 + Luhn）、手机号、QQ/微信/支付宝、BTC/ETH/TRON、网址；识别 `V信`、`扣扣`、`xxx点com` 等去武装写法 | README「功能」、`site/assets/core/` | V2EX、掘金、HN |
| 浏览器语音演示（王阿姨能听会说，带厨房环境底噪、断续停顿） | https://live.deepsuck.si/（**大陆访问受 #16 影响**） | HN、Reddit、即刻 |
| 公开诈骗情报库 + STIX 2.1 / RSS / CSV 订阅源（CC BY 4.0，当前为示例数据） | https://deepsuck.si/intel.html | HN、安全研究者 |
| 博客三篇（中英）：为什么用 AI 拖住骗子；七类常见诈骗话术的识别信号；技术拆解：王阿姨的语音链路 | https://deepsuck.si/blog/ | 少数派、知乎、掘金 |
| 5 分钟自托管，Node ≥ 18 零依赖、无需 Key 即可跑规则引擎 | docs/QUICKSTART.md | V2EX、Reddit r/selfhosted |

## 3. 演示素材：需要谁准备什么

现有素材：`screenshots/` 下沙盒、情报库、首页、语音页的 1280 / 390 截图；`screenshots/wangayi-sample.wav` 是**王阿姨人设的语音样例**（合成声音），**不是**和骗子的真实通话录音，文案里不能这么说。

| 素材 | 内容 | 谁准备 | 说明 |
|---|---|---|---|
| A. 王阿姨拖骗子的对话长截图 | 在沙盒里由维护者扮演“冒充客服退款”骗子，跑满 10–15 轮，截“王阿姨反复没听清、问卡号、骗子暴露账户被打码”的一段，加结束后的情报看板 | 维护者（网站/增长）用无头浏览器生成，负责人选图 | 只用沙盒内置样例台词或维护者自己写的台词，不用任何真实诈骗记录；截图里的账号必须是打码后的 |
| B. 语音演示录屏（30–60 秒，带声音） | 维护者在 live.deepsuck.si 扮演骗子和王阿姨通话，录屏 + 字幕 | 负责人或语音负责人（需要麦克风和能访问 live 的网络） | 明确标注“维护者扮演骗子的演示”；不录任何真实来电；勾选同意后的 trace 不外发 |
| C. 架构图一张 | 浏览器规则引擎 / 可选大模型代理 / 语音链路 / 情报库 | 维护者从 docs/ARCHITECTURE.md 重画 | 图里不写厂商名 |
| D. 小红书 3–6 张竖图 | “骗子常用的 7 句话” + 王阿姨对话截图 + 怎么报警（110 / 96110） | 负责人选题，维护者出图 | 以反诈科普为主，项目作为工具出现 |
| E. 英文 GIF（10 秒内） | 沙盒对话自动播放 + 情报卡片高亮 | 维护者 | 给 HN / Reddit / README 首屏 |

## 4. 渠道计划

总体节奏：中文渠道先、英文渠道后；技术社区先、泛人群后。负责人在每条帖子发出后 2 小时内守着回复。

| 日期 | 渠道 | 备注 |
|---|---|---|
| 10-26（一）10:00 | GitHub Release v0.4.0 + 博客短文 + V2EX | Release 与 tag 由负责人操作 |
| 10-27（二）09:30 | 掘金（技术长文） | |
| 10-27（二）21:00 | Hacker News · Show HN | 对应美东周二早上 |
| 10-28（三）12:00 | 即刻 | |
| 10-29（四）20:00 | 知乎（回答 + 文章） | |
| 10-30（五） | 少数派（投稿，审核周期待核实） | |
| 10-31（六）20:00 | 小红书 | 周末流量 |
| 11-01（日）22:00 | Reddit r/opensource、r/selfhosted | 对应美东周日上午；规则待核实 |

### 4.1 V2EX（「分享创造」节点）

- 切入：一个人/小团队做的开源小工具，讲设计取舍（为什么默认用规则引擎而不是大模型、怎么做到默认脱敏）。
- 注意：新账号可能要满 30 天才能在该节点发帖（待核实）；营销内容要发「推广」节点。
- 首发文案草稿：

> 标题：做了一个开源的反诈“拖住”机器人：你扮演骗子，AI 扮演王阿姨
>
> 起因很简单：骗子的时间是有限的，每多耗他一分钟，就少一个真受害人接到电话。
>
> DeepSuck 是一个开源（Apache-2.0）的中文反诈拖延机器人。打开 https://deepsuck.si/demo.html ，你来扮演骗子，它扮演四个“潜在受害人”之一：退休的王阿姨、宝妈小陈妈妈、刚毕业的小林、个体户郑老板。它会慢慢回、反复确认、偶尔没听清，同时把你暴露的收款账户、电话、钱包地址、网址提取出来，打码后生成情报看板。
>
> 几个设计取舍：
> - 默认是纯浏览器的规则引擎（23 种拖延与诱导策略），零成本、不用注册、不上传对话；可选接云端大模型 API（兼容标准聊天接口）。
> - 所有展示、导出、发给大模型的内容先打码；能识别「V信」「扣扣」「xxx点com」这类去武装写法。
> - 机器人从不主动联系任何人，只用于防御、研究和教育。
>
> 仓库：https://github.com/deepsucksi/deepsuck
> 5 分钟自托管：`git clone` 后 `npm start`，Node ≥ 18，零依赖。
>
> 欢迎来当骗子试试，看你能不能从王阿姨那里骗到验证码。也欢迎提话术线索（请先脱敏）。

### 4.2 掘金（技术长文）

- 切入：技术拆解。“浏览器里怎么做诈骗情报提取与脱敏”或转载博客「技术拆解：王阿姨的语音链路」（注明原文链接与许可）。
- 首发文案草稿（导语）：

> 标题：用规则引擎 + 可选大模型，做一个会拖时间的反诈机器人（开源）
>
> 这篇讲 DeepSuck 的三块核心：① 纯浏览器的人设规则引擎，怎么在 23 种拖延策略里按情境挑、不重复；② 情报提取：银行卡用开户行 + Luhn 校验，钱包地址按链区分，「V信」「扣扣」之类的去武装写法怎么归一化；③ 默认脱敏：为什么展示、导出、发给大模型的每一步都先打码。项目 Apache-2.0，沙盒在线可玩：https://deepsuck.si/demo.html

### 4.3 少数派

- 切入：面向普通读者的反诈科普 + 工具体验，不讲代码。可以投稿博客「七类常见诈骗话术的识别信号」的改写版。
- 投稿流程与审核周期待核实（可能需要负责人账号）。
- 首发文案草稿（导语）：

> 标题：我让 AI 扮成退休阿姨，陪“骗子”聊了一下午
>
> 冒充客服退款、刷单返利、校园贷……这些话术的套路其实很固定。我们做了一个开源小工具 DeepSuck：你扮演骗子，它扮演王阿姨，看它怎么一边装糊涂一边把“骗子”的收款账户问出来。文末附七类常见话术的识别信号，可以转给家里长辈。遇到诈骗请拨 110 或全国反诈专线 96110。

### 4.4 知乎

- 切入：回答已有问题（“怎么防止父母被电信诈骗”“AI 能用来反诈吗”这类，发帖前由负责人挑选具体问题），正文以科普为主，最后一段介绍工具；另发一篇文章转载博客「为什么用 AI 拖住骗子」。
- 首发文案草稿（回答结尾段）：

> 我们做了一个开源的小工具 DeepSuck，可以在浏览器里自己扮演骗子，看“王阿姨”这样的 AI 人设怎么拖时间、怎么识别话术。它只用于演示和研究，不会主动联系任何人。拿来给家里人演示“骗子会怎么说”，比讲道理直观。地址：deepsuck.si/demo.html

### 4.5 即刻

- 切入：短、轻，配对话截图（素材 A）。适合“独立开发 / 开源”相关圈子（具体圈子由负责人选）。
- 首发文案草稿：

> 做了个开源反诈小玩意：你当骗子，AI 当王阿姨。她会没听清、会反复确认、会问你卡号，最后把你暴露的账户打码列成情报。浏览器里就能玩，不用注册：deepsuck.si/demo.html

### 4.6 小红书

- 切入：反诈科普，图文笔记（素材 D），项目只在最后一张图出现。不放 GitHub 链接到正文以外的位置（平台对外链的规则待核实）。
- 首发文案草稿：

> 标题：骗子最爱说的 7 句话，转给爸妈
>
> “您的快递丢了，给您理赔”“刷单日结，先垫付”……我们整理了七类常见诈骗话术的识别信号（见图）。
> 还做了一个开源小工具，你可以扮演骗子，看 AI 王阿姨怎么应对。只用于学习和演示。
> 真遇到了：挂电话，拨 110 或 96110。

### 4.7 Hacker News（Show HN）

- 切入：英文开发者对“scambaiting + 开源 + 隐私优先”的兴趣；能直接试用的沙盒（规则要求必须能试用）。发帖人需在帖子下及时回复。
- 标题与正文草稿：

> Show HN: DeepSuck – an open-source bot that keeps phone/chat scammers busy (Chinese)
>
> DeepSuck plays a "potential victim" (a retired auntie, a young mom, a fresh graduate, a small shop owner) and stalls scammers: it answers slowly, asks them to repeat, mishears on purpose, and meanwhile extracts the bank cards, phone numbers, wallets and URLs they reveal. Everything shown, exported or sent to a model is masked first.
>
> You can try it without signing up: you play the scammer at https://deepsuck.si/demo.html (in-browser rule engine, 23 stalling tactics, 19 scam-script categories). There is also a browser voice demo, a public scam-intel library with STIX 2.1/RSS/CSV feeds (CC BY 4.0, currently example data), and an optional cloud LLM backend (any standard chat API).
>
> The bot never contacts real people; it is meant for defense, research and education. Apache-2.0, Node ≥ 18 with zero dependencies. Feedback on the redaction rules is very welcome.
>
> https://github.com/deepsucksi/deepsuck

### 4.8 Reddit（r/opensource、r/selfhosted；规则待核实）

- 切入：r/opensource 讲项目本身；r/selfhosted 讲“零依赖、一条命令自托管、可选语音服务一台小 VPS 跑得动、自带隐私友好的统计和脱敏日志”。避免发到 scambaiting 类子版块去鼓励主动钓骗子。
- 首发文案草稿（r/selfhosted）：

> Title: DeepSuck – self-hostable anti-scam "time-waster" bot with masked intel extraction (Apache-2.0)
>
> The core is a zero-dependency Node app (`npm start`, no API key needed) that runs a rule-based persona engine in the browser. Optionally you can add a cloud LLM backend (any standard chat API) and a Docker Compose stack for a browser voice demo behind Caddy. Logs keep only masked IPs; analytics are self-hosted and cookie-free. Docs: docs/QUICKSTART.md and docs/DEPLOY.md. Live sandbox: https://deepsuck.si/demo.html

## 5. SEO 与 README 首屏

### 5.1 站点

- 依赖 GROWTH.md 第 4 节：Google 验证 meta 已在 `site/index.html`；Bing、百度验证仍待负责人登录获取。发布当天提交 sitemap。
- 标题和描述里补搜索词：首页 title 现为「DeepSuck · 开源 AI 反诈“拖住”机器人」，建议描述里加入“防诈骗”“诈骗话术识别”“情报库”；沙盒页 title 加“在线体验”。
- 博客每篇文章底部加“去沙盒试一试”的固定链接（改 `scripts/build-blog.js` 模板，单开 issue）；同时把统计脚本接入博客模板（#231 只接了首页、沙盒、情报库、404）。
- 大陆访问：Pages 可访问，live 子域受 #16 影响；中文渠道一律以沙盒为主入口，语音演示写“海外网络可用”。

### 5.2 README 首屏

- 第一屏顺序建议：一句话定位 → 一张 GIF（素材 E，沙盒对话 + 情报卡片） → 三个按钮（在线试玩、5 分钟自托管、情报库） → “不主动联系任何人”的边界一句。现在首屏是横幅 + 徽章 + 链接行 + 语音页截图，可把语音页截图换成沙盒 GIF（大陆读者也能打开沙盒）。
- 加英文一句话摘要和 “English” 锚点，给 HN / Reddit 来的读者。
- 发布后加版本徽章（GROWTH.md 1.2 已列）。
- 仓库 description 按 GROWTH.md 1.1 的建议改（仍待负责人拍板）。

## 6. 两周后检验（2026-11-09）

| 指标 | 现在 | 目标（11-09） | 数据从哪来 |
|---|---|---|---|
| GitHub star | 1 | ≥ 50（及格 30） | `gh api repos/deepsucksi/deepsuck -q .stargazers_count` |
| 日真实访客（deepsuck.si，7 日均值） | 无数据 | ≥ 80 | 自托管统计（#231 / #232 部署后）的独立访客；开了 DNT/GPC 的不计，**VPS 从大陆连不通（#16），大陆访客会大量漏计**，所以同时看 GitHub traffic 的 `uniques` 做对照 |
| 沙盒演示会话数（两周累计） | 无数据 | ≥ 300 | 统计里的 `demo-session` 事件（每个会话第一条消息记一次，不含内容） |
| 语音演示通话数（两周累计） | 见服务器 | ≥ 50 | VPS 上 trace 目录的 `stats.json`（只有计数：calls、consent 等），负责人在服务器上看 |
| 外部 issue / PR | 0 | ≥ 5 | `gh issue list --search "-author:deepsucksi"` |
| 仓库访问独立访客（14 天） | 4 | ≥ 500 | `gh api repos/deepsucksi/deepsuck/traffic/views` |
| 各渠道带来的访问 | — | 记录排序即可 | 统计里的来源站点（只记域名）、GitHub `traffic/popular/referrers` |

注意：统计端点地址要等 #232 部署、#231 的 `endpoint` 填好后才开始计数，10-26 之前上线才能看到完整两周。上线晚了就把起算日顺延。

## 7. 需要负责人决定的

1. 是否按此时间表发，以及每个渠道用谁的账号（我们不注册账号）。
2. 素材 B（语音录屏）由谁录。
3. 统计服务与访问日志（#232）何时部署；统计子域名用什么。
4. README 首屏是否换成沙盒 GIF；仓库 description 是否改。
5. GROWTH.md 第 5 节写着“统计暂不上”（2026-10-19 决定），本次 #231 / #232 已按新安排推进，确认后在 GROWTH.md 里同步更新。
