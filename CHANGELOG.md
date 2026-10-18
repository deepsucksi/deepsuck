# 更新记录

## 未发布

### 盲测加大模型评委代理指标（默认关闭）

- `eval/realism_blind.py score` 新增 `--judge llm`：用百炼 DashScope 的 `qwen-plus`（OpenAI 兼容接口，非思考模式，temperature 0，固定 seed，JSON 输出）对 A、B 两份表逐题判断真人 / 机器人并打 1–5 像真人分，结果与人工评分走同一个 `score()` 汇总（露馅率、配对差与 95% 区间、像真人分）。逻辑在新文件 `eval/realism_judge.py`，只用标准库。
- 成本控制：默认 60 个句对（120 题），每次请求 10 题；调用前按 qwen-plus 官方单价（常量注明来源）估算费用，超过 1 元拒绝运行，`--dry-run` 只估算；请求与回复缓存在 `eval/.judge-cache/`（已 gitignore），重跑不重复计费。Key 只从 `DASHSCOPE_API_KEY` 或根目录 `.env` 读取，不打印、不落盘。
- docs/EVAL.md「像不像真人」新增「自动评委基线」：2026-10-18 种子 1 跑 120 题，实际约 0.017 元；露馅率 raw 16.7%、humanized 26.7%，差 +0.10（95% 区间 −0.033 到 0.233）。注明是代理指标，不能代替人工盲测，并列出观察到的评委偏差（错别字被当机器信号、跨题比较、文字相同的句对判断不一致）。
- 测试：`corpus/tests/test_realism_judge.py` 用假客户端，不联网（批次不跨表、确定性参数、缓存不重复计费、超预算拒绝、上限不能超过 1 元、Key 不外泄、默认关闭）。

### 真实话术语料、提取器噪声鲁棒性与跨回合拼接（情报分析）

- 新增 `site/assets/core/scam_scripts.json`（CC BY 4.0，含 JSON Schema 与 node / pytest 校验）：7 类 × 5 阶段共 181 条骗子侧话术，据公开反诈宣传、公安 / 网信部门通报、法院与检察院典型案例和 TeleAntiFraud（Apache-2.0）归纳后重写，不含原文，号码网址一律占位符；只有确实对应具体案例、通报段落或数据集条目的 40 条标注案例 / 通报 / 数据集并给出 `sourceRef`，其余标“据公开反诈宣传改写”。来源与许可见 `corpus/SOURCES.md`、`DATA_LICENSE`。
- 演示页样例台词（`site/assets/core/scenarios.json` 的 `samples`）据语料改写，字段结构不变，新增一一对应的 `sampleSources`；虚构值统一为 `.example` 域名、`某某` 户名。
- 模拟器默认改用语料台词（`python -m deepsuck.sim --lines corpus|legacy`），固定种子可复现，语料缺失时退回手写台词；手写台词下的结果与 v0.5 逐项相同。
- 提取器（JS / Python 同步）：异体字与由 `personas/humanize` 混淆表生成的错字归一（`scripts/sync_typo_keywords.py`）；数字夹空格 / 横杠 / 换行 / 中文标点、中文数字夹标点、腰 / 溜 / 酒等同音数字、分段钱包地址；户名在常见后续字处截断；“13900112233两小时”的量词不并入号码；新增跨回合拼接 `stitch()` 并接入 `Session`（拼接情报带置信度，前一回合回溯打码）。
- 新增 `eval/noise_eval.py` 与 `eval/results-noise.json`、`eval/results-sim-corpus.json`；数字混淆 18 种写法的提取率由平均 66.7% 升到 100%，跨回合拆分由 0 升到 96%（2 回合银行卡 83–87%），600 组对抗负例误拼 0；话术分类器 F1 不变（0.949 / test 0.946）。详见 docs/EVAL.md。
- 新增首页示例对话回归测试（动态读取 `corpus/examples/hero_rewrite.json`，只依赖 lines 的 r / s / i）。

### bootstrap 重跑不再重复首次部署提示

- `bootstrap.sh` 结尾的「下一步」（加 DNS、放行防火墙、改 `live-config.js`）只在首次部署时显示，判断依据是本次运行新建了 `deploy/.env`；重跑只打印一行「已更新」摘要。只是脚本输出的变化，已部署的服务器不需要做任何操作。

### 部署修复：bootstrap 重跑 WITH_SIP=1、Caddyfile 目录挂载

- 修复 `bootstrap.sh` 在 `deploy/.env` 已存在且没有 `SIP_LOG_DIR` 时用 `WITH_SIP=1` 重跑会静默退出：`getv` 用 `grep` 取值，没匹配时返回 1，在 `set -euo pipefail` 下 `sip_log="$(getv SIP_LOG_DIR)"` 直接终止脚本。`getv KEY [默认值]` 现在不会返回非零，缺失时返回默认值；SIP_* 调用处补上 docs/PHONE.md 6.4 节的默认值（`SIP_LOG_DIR=/var/log/deepsuck-sip`、`SIP_PORT=25060`、`SIP_RTP_PORTS=40100-40199`、`SIP_AI_EXTEN=9000`、`SIP_TCP=0`），`LIVE_DOMAIN`、`VOICE_UDP_PORTS` 也改用 `getv`。
- Caddyfile 移到 `deploy/caddy/Caddyfile`，compose 挂载整个目录到 `/etc/caddy`，`git pull` 后 `caddy reload` 或重启容器即可生效。已部署的服务器需要执行一次 `docker compose up -d --force-recreate caddy`（bootstrap 会自动检测旧的单文件挂载并重建），见 docs/DEPLOY.md。
- 新增 `deploy/tests/test_bootstrap.sh`：桩替换 docker、systemctl、apt-get 等，覆盖已有 `.env` + `WITH_SIP=1`、重跑不覆盖密码、caddy 挂载迁移；已接入 CI 与 `python -m pytest voice/tests`。

### 自建 SIP 软电话接入（零成本演示）

- `deploy/` 新增默认关闭的 `sip` profile：Asterisk 22（`andrius/asterisk:22.11.0-alpine-3.24`，免编译）+ chan_websocket，手机 Linphone/Zoiper 注册后拨一个分机即可跟 AI 通话。只是演示用的分机，不是电话号码，没有外线、没有外呼。见 docs/PHONE.md 第 10 节。
- 新增电话适配器 `asterisk-ws`（`voice/telephony/asterisk_ws.py`），复用 `ws-raw` 的编解码与重采样；电话入口 token 新增 HTTP Basic 方式（Asterisk 用它，token 不进访问日志的 URL）。
- 安全：账号密码只从环境变量读取，缺失或太弱拒绝启动；只允许认证呼入、只有一个分机；模块白名单加载，AMI/ARI/HTTP 关闭；非 5060 端口；fail2ban 防暴力注册；Caddy 屏蔽 `/telephony/asterisk-ws*`；容器内存上限 64 MB（实测空闲约 6 MB）。
- `bootstrap.sh` 新增 `WITH_SIP=1`（自动生成账号密码、打开电话入口、拆分 UDP 端口段、装 fail2ban/logrotate）；开 SIP 时网页语音改用 UDP 40000–40099，SIP RTP 用 40100–40199。

### 语料与人设框架（v0.1）

- 新增 `corpus/`：来源与脱敏原则（不收集真实个人身份信息、引用一律改写、仅限防御研究与教育）；`corpus/SOURCES.md` 调研可复用的公开数据集与 scam-baiting 项目（链接、许可证、能否入库）；`corpus/scripts/` 7 类话术库 YAML（冒充客服、冒充公检法、冒充领导熟人、杀猪盘、刷单返利、投资理财、贷款征信），含流程阶段、常用词、施压手法、识别要点和改写示例，情报一律用 `{占位符}`。
- 新增 `personas/`：4 个人设提示词（周伯 · 退休老人、小陈妈妈 · 宝妈、小宇 · 刚毕业学生、郑老板 · 个体小老板）与共用硬性规则；`personas.humanize` 真人化后处理（同音/形近错别字、标点缺失乱用、语音转文字断句、重复确认、跑题、方言词），带随机种子与强度参数，不改动数字、打码值、占位符和网址，零依赖。
- 新增 `personas/voice_traits.yaml`（7 个人设的语音说话特征：8–12 条 backchannel，格式与 `voice/persona.py` 的 `FILLERS` 相同、现有 3 个人设前 8 条不变；听错词对与反问；语速、方言词、口音；开口前停顿与扯家常频率；不含错别字）与读取模块 `personas/voice_traits.py`；`docs/REALISM.md` 分“文字打字特征”“语音说话特征”两章。`voice/` 代码未改动。
- 真人感文档移到 `docs/REALISM.md`（保留“文字打字特征”“语音说话特征”两章），新增第三章“首页示例对话改写前后”：以 `hero-chat.js` 现有 3 段为改写前，换成新人设（周伯、小陈妈妈、小宇）重写骗子与人设两侧，并用 humanize 固定种子真人化；生成脚本 `corpus/examples/build_hero_rewrite.py`，输出 `corpus/examples/hero_rewrite.json`（`after` 严格按 `SCRIPTS` 结构：`title`「诈骗类型 · 人设名」、`source`「据公开反诈宣传改写」、`lines` 每条 `r`/`s` 二选一并可选 `t`/`i`/`w`，`i` 必须已打码，每段 4–6 条、每条不超过 40 字，生成时校验；`site/` 未改动）。改写前的首页原版 3 段固定在 `corpus/examples/hero_before.json`（取自 `420a81f`），生成脚本与测试不再依赖 `hero-chat.js` 的当前内容，只检查字段名；humanize 混淆表去掉刻意错字（神马、孩纸、好滴、手鸡、钱→前）。
- 评测：docs/EVAL.md 新增“像不像真人”一节与盲测工具 `eval/realism_blind.py`（A/B 两份表交叉分配 raw / humanized，可选真人回复参照；指标：像真人分、露馅率与配对差、看不懂率、评测者一致率、自动指标）。骗子消息默认取自 `corpus/scripts`，`--scammer-file` 可换成情报分析师的真实语料（`deepsuck.core.scam-scripts/v1` 或 JSON/YAML/JSONL 列表）。humanize 的重复确认只复述完整的短分句（不再截断长分句），并去掉“？，”这类双标点。
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
