# 更新记录

## 未发布

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
