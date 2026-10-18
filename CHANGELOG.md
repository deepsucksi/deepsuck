# 更新记录

## 未发布

### 自建 SIP 软电话接入（零成本演示）

- `deploy/` 新增默认关闭的 `sip` profile：Asterisk 22（`andrius/asterisk:22.11.0-alpine-3.24`，免编译）+ chan_websocket，手机 Linphone/Zoiper 注册后拨一个分机即可跟 AI 通话。只是演示用的分机，不是电话号码，没有外线、没有外呼。见 docs/PHONE.md 第 10 节。
- 新增电话适配器 `asterisk-ws`（`voice/telephony/asterisk_ws.py`），复用 `ws-raw` 的编解码与重采样；电话入口 token 新增 HTTP Basic 方式（Asterisk 用它，token 不进访问日志的 URL）。
- 安全：账号密码只从环境变量读取，缺失或太弱拒绝启动；只允许认证呼入、只有一个分机；模块白名单加载，AMI/ARI/HTTP 关闭；非 5060 端口；fail2ban 防暴力注册；Caddy 屏蔽 `/telephony/asterisk-ws*`；容器内存上限 64 MB（实测空闲约 6 MB）。
- `bootstrap.sh` 新增 `WITH_SIP=1`（自动生成账号密码、打开电话入口、拆分 UDP 端口段、装 fail2ban/logrotate）；开 SIP 时网页语音改用 UDP 40000–40099，SIP RTP 用 40100–40199。

### 语料与人设框架（v0.1）

- 新增 `corpus/`：来源与脱敏原则（不收集真实个人身份信息、引用一律改写、仅限防御研究与教育）；`corpus/SOURCES.md` 调研可复用的公开数据集与 scam-baiting 项目（链接、许可证、能否入库）；`corpus/scripts/` 7 类话术库 YAML（冒充客服、冒充公检法、冒充领导熟人、杀猪盘、刷单返利、投资理财、贷款征信），含流程阶段、常用词、施压手法、识别要点和改写示例，情报一律用 `{占位符}`。
- 新增 `personas/`：4 个人设提示词（周伯 · 退休老人、小陈妈妈 · 宝妈、小宇 · 刚毕业学生、郑老板 · 个体小老板）与共用硬性规则；`personas.humanize` 真人化后处理（同音/形近错别字、标点缺失乱用、语音转文字断句、重复确认、跑题、方言词），带随机种子与强度参数，不改动数字、打码值、占位符和网址，零依赖。
- 测试：`python -m pytest personas corpus`（话术库格式与脱敏检查、人设格式、真人化确定性与保护规则），已加入 CI。

### 情报数据改用 CC BY 4.0

- 情报数据（`site/data/intel.json`、`intel.csv`、`intel.rss`、`intel.stix.json` 及其生成物）改为 CC BY 4.0 许可，署名「DeepSuck (deepsuck.si)」；新增根目录 `DATA_LICENSE`（适用范围、署名方式与 CC BY 4.0 法律文本全文）。代码仍为 Apache-2.0。
- `intel.json` 顶层改为 `license: "CC-BY-4.0"`，新增 `licenseUrl`、`attribution`；`intel.schema.json` 把三者列为必填并固定取值。
- STIX 导出（`python -m deepsuck.stix`）新增 statement 类型的 marking-definition `DeepSuck data license: CC BY 4.0`，identity 与其余全部对象都引用它（与 TLP:WHITE 并列）；OASIS validator `Valid`，0 警告。已导入旧版 Bundle 的平台请整包重新导入（对象的 `modified` 仍取条目日期，未因加标记而变化）。
- RSS 的 `<copyright>` 改为 CC BY 4.0 与署名，channel 说明里注明各导出文件的许可；CSV 不加注释行（保持可解析、与页面导出逐字节一致），许可在 `DATA_LICENSE` 与 docs/INTEL.md 中注明。
- 情报页数据区与页脚注明数据许可与署名，JSON-LD 的 Dataset `license` 改为 CC BY 4.0；情报提交模板的确认项改为按 CC BY 4.0 公开发布。

### GitHub 自动收录与公开订阅源

- 新增结构化情报提交模板 `intel-intake.yml`，以及工作流 `intel-intake.yml`：解析 issue → 脱敏 → 去重 → 公开黑名单比对 → 生成更新 `intel.json` 等文件的待审核 PR，并在 issue 下回复结果。不自动合并；每个 job 单独声明最小权限；Action 锁定到 SHA；issue 正文不进入 shell。核心逻辑在 `python/deepsuck/intake.py`，测试不联网。
- 新增公开订阅源 `site/data/intel.rss`（RSS 2.0）和 `site/data/intel.csv`（`python -m deepsuck.feeds` / `npm run build:intel`），只含公开中的条目，用打码值。
- 银行卡新增仅用于展示的分组格式 `formatCardGroups` / `format_card_groups`（`622202*********3445` → `6222 02** **** ***3 445`），情报页卡片改用分组展示；存储与 STIX 不变。

### 银行卡 PCI 打码

- 银行卡打码改为 PCI DSS 标准：16–19 位保留前 6 位（BIN）与后 4 位，中间全部打码；8–15 位只留后 4 位，少于 8 位全部打码。JS（`redact.js`）与 Python（`deepsuck/redact.py`）同步，fixtures 覆盖 7–19 位与带空格/连字符写法。
- 情报库与提交附 BIN 推断的发卡行 `issuer` 与卡种 `cardType`；schema 与校验器只接受 PCI 打码格式。
- STIX 2.1 导出现在包含银行卡 Indicator（`payment-card:card_number LIKE`，仅用打码值），并带 `x_deepsuck_bank / issuer / card_type` 扩展属性；OASIS 校验通过。
- 模拟器泄露率不再把紧挨 `*` 的打码值数字段计为泄露（结果数字不变）。
- 姓名、身份证、QQ、微信、支付宝打码方式不变。

### 其他

- 情报：STIX 2.1 导出（`python -m deepsuck.stix`，发布 [`site/data/intel.stix.json`](site/data/intel.stix.json)，姓名、账号、身份证不导出，银行卡只导出 PCI 打码值）；银行卡 BIN 本地查询（数据 [hexindai/bcbc](https://github.com/hexindai/bcbc)，MIT），提取到卡号时补充发卡行与卡种。见 [docs/INTEL.md](docs/INTEL.md)。
- 站点打磨：WCAG AA 文字对比度；手机端原生 `<details>` 折叠菜单（保留 EN 切换）；沙盒场景/人设折叠进对话头，首屏即见输入框；原生 `<dialog>` 弹窗；情报库分页与 4 列统计；首页示例对话首帧不空。
- SEO：三页补齐 description、canonical、OG/Twitter 卡片，按页面生成 OG 图（`npm run og`）；新增 robots.txt、sitemap.xml、404.html 与 JSON-LD（WebSite、SoftwareSourceCode、Dataset）。
- 纯静态托管时不再请求 `api/health`（由 `npm start` 托管时服务器注入 `local = true`）；GitHub 星标改用 shields.io 徽章。
- 截图改为 `npm run screenshots` 生成的 WebP；logo/favicon 统一为墨黑 + 纸白 + 铜色点缀。
- 文档：新增 [docs/QUICKSTART.md](docs/QUICKSTART.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，README 精简。

## v0.4 公开部署包

Docker Compose（Caddy 自动 HTTPS + Node 代理 + Pipecat 语音 + 可选 coturn）、一键 bootstrap、费用护栏（每日预算预占记账、每 IP/全站限流、并发/时长/轮数/静默上限、CORS 白名单）、WebRTC UDP 端口段 + 公网 IP 候选、`voice.probe` 端到端探针；修复 Paraformer 数字规整导致的姓名漏抽（`张3` → `张三`）。见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## v0.3

Python 核心（共享 fixtures，CI 跑 pytest）；destroylist / Phishing.Database 域名黑名单 + OFAC / ScamSniffer 钱包黑名单；骗子模拟器与 TeleAntiFraud 评测（[docs/EVAL.md](docs/EVAL.md)）；语音演示（Pipecat 级联：Paraformer 实时 ASR → qwen-plus → CosyVoice，SmallWebRTC 浏览器麦克风，填充音插播，实时情报看板）；语音输出守卫。

## v0.2

7 个场景（新增刷单返利、虚假贷款/征信修复、冒充领导熟人、注销校园贷）；情境台词与反向核验；公开诈骗情报库 + 提交/申诉流程；规则数据抽成 `core/*.json`；中文去武装写法识别；首页动画与 OG 图。

## v0.1

纯静态沙盒、规则人设引擎、提取器/分类器/脱敏、情报看板、可选百炼代理。
