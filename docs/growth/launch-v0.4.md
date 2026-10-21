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
| 10-30（五） | 少数派（投稿作品，编辑部尽力 3 个工作日内答复，见 4.0） | |
| 10-31（六）20:00 | 小红书 | 周末流量 |
| 11-01（日）22:00 | Reddit r/opensource（独立帖，Promotional flair）、r/selfhosted（只能发在当周 New Project Megathread 的顶层评论） | 对应美东周日上午；规则见 4.0 |

### 4.0 渠道规则核实（查证日期 2026-10-21）

以下各渠道首发文案都是俊杰本人第一人称的草稿，发之前请按自己的习惯再改一遍；事实部分（功能、踩坑）都能在仓库里找到出处，不要往里加没发生过的经历或数字。

| 渠道 | 核实结果 | 来源 |
|---|---|---|
| V2EX「分享创造」（2026-10-21 复查） | **注册**：官方注册页写明，2024 年 6 月以后用 Google 注册的新账号需要邀请码才能激活，持有 10K V2EX Coin 可直接建号（所以新号门槛主要在注册这一步）。**铜币**：官方货币说明写明新账号初始 100 铜币，创建主题至少消耗 20 铜币、内容越长越多，10 分钟内编辑每次 5 铜币；首帖铜币够用。**注册时长**：「分享创造」节点本身有没有注册时长要求，官方未公布，**未核实**；站长 2018 年回复过该节点没有注册时间限制，用户反馈的「注册满 N 天」提示来自外链、图床（如 imgur 要满 180 天）等反垃圾规则，另有用户反馈部分节点要求账号满 7 天，未说明是哪些节点。**手机验证**：官方文档未写明固定规则，**未核实**；用户反馈含敏感词、@、长串数字、图片等内容时会被要求先验证邮箱或手机。营销内容须发「推广」节点。建议：用已有的老账号发，首帖少放外链、不贴图床图片，被拦按提示处理。 | [注册页](https://www.v2ex.com/signup)、[虚拟货币系统](https://v2ex.com/help/currency)、[节点说明](https://v2ex.com/help/node)、[t/469028 站长回复](https://www.v2ex.com/t/469028)、[t/1156126（7 天 / imgur 180 天）](https://www.v2ex.com/t/1156126)、[t/672423（手机验证）](https://www.v2ex.com/t/672423) |
| Reddit r/selfhosted | 规则 6：首次公开不满 3 个月的项目只能发在当周 New Project Megathread（每周五新开），独立帖会被删；规则 2：自宣传要适度，应用须可自托管、已发布、有文档；新帖须回复机器人说明 AI 参与情况才会放行。 | [规则 wiki 镜像](https://r.datuan.dev/r/selfhosted/wiki/rules)、[Megathread 2026-10-15 镜像](https://r.datuan.dev/r/selfhosted/comments/1x6ywou/new_project_megathread_week_of_15_oct_2026/)、[2026 Q2 规则公告](https://www.reddit.com/r/selfhosted/comments/1sey9ch/quarter_2_update_revisiting_rules_again/) |
| Reddit r/opensource | 允许分享自己的项目但不能过度（参考 Reddit 自宣传不超过 10%）；必须用 `Promotional` flair；仓库须有 OSI 许可证；不许 drive-by 发帖；规则 3 写明 AI 生成内容视为低质、可封禁（第三方镜像 2026-10-11 抓取）。 | [第三方规则镜像](https://threadfox.vip/rules/opensource)、[flair 说明](https://www.reddit.com/r/opensource/comments/xrw5s9/new_postflairs/) |
| Reddit 其他版（如 r/Scams） | 方案不投；scambaiting / 受害者求助类版块与「不主动钓骗子」的边界冲突，未查规则。 | — |
| 少数派 | 「投稿作品」：编辑部工作日上午集中审阅，尽合理努力 3 个工作日内通知，不承诺固定时间，节假日或征文期可能延长；超 3 个工作日可联系编辑部；投稿原则上要首发（个人渠道发表不超过一周仍算）。「新手上路」账号文章需人工审核，一般一个工作日内确认。 | [提交与审阅流程](https://manual.sspai.com/guides/review-procedure/)、[用户组别](https://manual.sspai.com/guides/types-of-accounts/) |
| 小红书 | 《交易导流违规管理细则》（2025-03-12 生效）适用于所有用户：禁止在笔记、评论、资料中发布其他平台的链接、口令、截图、水印、二维码，或引导至站外；处罚从警告、限流到封号。《社区公约 2.0》要求用 AI 辅助的内容主动标明。**非交易类开源项目链接是否同样处理：未能核实**，按最严理解不放任何链接。 | [新浪科技转述细则](https://finance.sina.com.cn/tech/discovery/2025-03-12/doc-inepkkxi8789428.shtml)、[IT之家](https://m.ithome.com/html/837049.htm)、[社区公约 2.0](https://pgy.xiaohongshu.com/help/detail?id=1eda0a065dd894063c2e029a49e8f6a1&userType=4) |

Reddit 官方页面从本机抓取被拦，上表 Reddit 两项用的是镜像或第三方转录，发帖前请负责人在 Reddit 上再看一眼侧栏规则。

### 4.1 V2EX（「分享创造」节点）

- 切入：程序员随手发的帖，讲起因和几个真踩过的坑，链接放最后。门槛见 4.0；营销内容要发「推广」节点。
- 文中坑点的出处：Caddyfile 单文件挂载（docs/DEPLOY.md）、UDP 被封走 443（#3）、中文打断（docs/VOICE_LATENCY.md）、冲突标记（#217）、大陆访问（#16）。
- 首发文案草稿：

> 标题：业余做了个反诈机器人，你演骗子，它演退休的王阿姨
>
> 起因挺简单的。骗子打一通电话也得花时间，他在一个假受害人身上多耗一分钟，就少打一个真人的电话。要是有个东西专门陪他们聊、慢慢耗，顺手把他们报出来的卡号和网址记下来，我觉得挺值得做。
>
> 于是有了 DeepSuck。网页上你扮演骗子，它扮演四个人设之一，王阿姨、小陈妈妈、小林、郑老板。它回得慢，老没听清，让你再说一遍，你报的账户、电话、网址会被提出来打码。默认是浏览器里跑的规则引擎，不用注册，也可以接云端大模型 API。
>
> 做的过程里踩了几个坑，顺便记一下：
>
> 自托管那套 compose 一开始把 Caddyfile 按单个文件挂进容器，git pull 之后容器里看到的还是旧文件，因为换了 inode，后来改成挂整个目录。
>
> 公司网络这类 UDP 被封的环境里语音连不上，最后让 TURN 跟 HTTPS 一起走 443。
>
> 语音那边，框架自带的「说够几个词才算打断」是按空格分词的，对中文完全没用，只好自己改成数字数。
>
> 还有一次合并把冲突标记留在了 CHANGELOG 里，CI 居然是绿的，现在 CI 第一步先扫冲突标记。
>
> 在线试：https://deepsuck.si/demo.html
> 代码：https://github.com/deepsucksi/deepsuck ，Apache-2.0，Node 18 以上直接 npm start。
>
> 语音演示放在海外机器上，国内可能连不上，这个还没解决。它不会主动联系任何人，只是给大家玩和研究用的。欢迎来当骗子，看能不能从王阿姨那儿套出信息。

### 4.2 掘金（技术长文）

- 切入：技术拆解，可转载博客「技术拆解：王阿姨的语音链路」（注明原文链接与许可）。下面是导语，正文用博客原文。
- 首发文案草稿（导语）：

> 标题：写一个会装糊涂的反诈机器人：规则引擎、情报打码和语音延迟
>
> 这是我业余写的开源项目 DeepSuck，你在网页上扮演骗子，它扮演受害人陪你聊。这篇主要记三件事。
>
> 第一是规则引擎。默认不调任何模型，人设回复全在浏览器里按情境挑，同一种拖法不会一直重复。
>
> 第二是情报提取和打码。银行卡会配合开户行和 Luhn 校验，「V信」「扣扣」「xxx点com」这类故意写歪的也要认出来。我给自己定的规矩是，页面展示、导出、发给云端大模型 API 之前都先打码。
>
> 第三是语音延迟。断句静音从服务端默认的大约 800ms 调到 450ms，打断判定按中文字数来算，这些在仓库的 docs/VOICE_LATENCY.md 里有实测记录。
>
> 沙盒可以直接玩：https://deepsuck.si/demo.html

### 4.3 少数派

- 切入：面向普通读者的反诈科普 + 工具体验，不讲代码。可以投稿博客「七类常见诈骗话术的识别信号」的改写版。
- 投稿须知见 4.0：投稿作品原则上要首发于少数派（个人渠道发表不超过一周仍算首发），所以若走投稿，博客原文要在少数派之后或一周内发；需负责人账号。
- 首发文案草稿（导语）：

> 标题：我写了个 AI 王阿姨，专门陪“骗子”聊天
>
> 冒充客服说要退款，刷单说先垫付，套路翻来覆去就那几种。我业余做了个开源小工具 DeepSuck，在网页上你来当骗子，它扮演退休的王阿姨，一边装没听清，一边把你报的账户记下来打码。
>
> 文末整理了七类常见话术的识别信号，可以转给家里长辈看。真遇到了，挂掉电话，打 110 或者 96110。

### 4.4 知乎

- 切入：回答已有问题（“怎么防止父母被电信诈骗”“AI 能用来反诈吗”这类，发帖前由负责人挑选具体问题），正文以科普为主，最后一段介绍工具；另发一篇文章转载博客「为什么用 AI 拖住骗子」。
- 首发文案草稿（回答结尾段）：

> 顺便说下，我自己业余写了个开源的小东西叫 DeepSuck，可以在浏览器里扮演骗子，看「王阿姨」这种 AI 人设怎么拖时间。想给家里人演示骗子一般怎么说话的话，可以拿它试试，比光讲道理直观。它不会去联系任何真人，就是个演示。地址是 deepsuck.si/demo.html

### 4.5 即刻

- 切入：短、轻，配对话截图（素材 A）。适合“独立开发 / 开源”相关圈子（具体圈子由负责人选）。
- 首发文案草稿：

> 业余做的开源反诈小玩意上线了。你当骗子，AI 当王阿姨，她老是没听清，还反过来问你卡号，最后把你报的账户打码列出来。浏览器里就能玩，不用注册：deepsuck.si/demo.html

### 4.6 小红书

- 切入：反诈科普，图文笔记（素材 D），项目只在最后一张图出现。按 4.0 的导流规则，笔记、评论、图片里**都不放任何站外链接、网址、二维码或其他平台账号**，只写项目名；用了 AI 辅助作图或写文案要在笔记里标明。
- 首发文案草稿：

> 标题：骗子电话里最常说的几句话，存一下发给爸妈
>
> 「您的快递丢了，给您理赔」「刷单日结，先垫付一下」，这类话我整理成了图，一共七类。
>
> 我自己业余还做了个开源小工具叫 DeepSuck，可以自己扮演骗子，看 AI 王阿姨怎么装糊涂。纯属学习和演示。
>
> 真接到这种电话，直接挂，打 110 或者 96110。

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

### 4.8 Reddit（r/opensource、r/selfhosted；规则见 4.0）

- 切入：r/opensource 讲项目本身；r/selfhosted 讲“零依赖、一条命令自托管、可选语音服务一台小 VPS 跑得动、自带隐私友好的统计和脱敏日志”。避免发到 scambaiting 类子版块去鼓励主动钓骗子。
- r/selfhosted：项目首次公开（首个 commit 2026-10-17）不满 3 个月，**不能发独立帖**，只能在当周 New Project Megathread 里发顶层评论，按其模板写 Project Name / Repo / Description / Deployment / AI Involvement。
- r/opensource：发帖要加 `Promotional` flair，仓库要有 OSI 许可证（Apache-2.0 满足），发完要留下来回复；该版规则把 AI 生成内容视为低质，帖子由负责人亲自写或改写。
- 首发文案草稿（r/selfhosted Megathread 顶层评论）：

> Project Name: DeepSuck – self-hostable anti-scam "time-waster" bot with masked intel extraction (Apache-2.0)
> Repo/Website Link: https://github.com/deepsucksi/deepsuck · https://deepsuck.si/demo.html
> Deployment / Description: The core is a zero-dependency Node app (`npm start`, no API key needed) that runs a rule-based persona engine in the browser. Optionally you can add a cloud LLM backend (any standard chat API) and a Docker Compose stack for a browser voice demo behind Caddy. Logs keep only masked IPs; analytics are self-hosted and cookie-free. Docs: docs/QUICKSTART.md and docs/DEPLOY.md.
> AI Involvement: （由负责人如实填写：项目开发中 AI 辅助的范围，以及帖子文字是否由 AI 起草）

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
| 日真实访客（deepsuck.si，7 日均值） | 无数据 | ≥ 80 | 自托管统计（#231 / #232 部署后，面板 live.deepsuck.si/stats/）的独立访客；开了 DNT/GPC 的不计，**VPS 从大陆连不通（#16），大陆访客会大量漏计**，所以同时看 GitHub traffic 的 `uniques` 做对照 |
| 沙盒演示会话数（两周累计） | 无数据 | ≥ 300 | 统计里的 `demo-session` 事件（每个会话第一条消息记一次，不含内容） |
| 语音演示通话数（两周累计） | 见服务器 | ≥ 50 | VPS 上 trace 目录的 `stats.json`（只有计数：calls、consent 等），负责人在服务器上看 |
| 外部 issue / PR | 0 | ≥ 5 | `gh issue list --search "-author:deepsucksi"` |
| 仓库访问独立访客（14 天） | 4 | ≥ 500 | `gh api repos/deepsucksi/deepsuck/traffic/views` |
| 各渠道带来的访问 | — | 记录排序即可 | 统计里的来源站点（只记域名）、GitHub `traffic/popular/referrers` |

注意：统计端点地址要等 #232 部署、#231 的 `endpoint` 填好后才开始计数，10-26 之前上线才能看到完整两周。上线晚了就把起算日顺延。

## 7. 需要负责人决定的

1. 是否按此时间表发，以及每个渠道用谁的账号（我们不注册账号）。
2. 素材 B（语音录屏）由谁录。
3. 统计服务与访问日志（#232，统计挂在 live.deepsuck.si/stats/，不需要新子域）何时部署。
4. README 首屏是否换成沙盒 GIF；仓库 description 是否改。
5. GROWTH.md 第 5 节写着“统计暂不上”（2026-10-19 决定），本次 #231 / #232 已按新安排推进，确认后在 GROWTH.md 里同步更新。
