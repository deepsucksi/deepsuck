# 更新记录

## 未发布

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
