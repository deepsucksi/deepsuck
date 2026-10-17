<p align="center"><img src="site/assets/logo.svg" width="88" alt="DeepSuck logo"></p>

<h1 align="center">DeepSuck</h1>

<p align="center"><b>开源 AI 反诈“拖住”机器人：让骗子把时间浪费在 AI 身上，同时提取脱敏的诈骗情报。</b></p>

<p align="center">
  <b>⚠️ 非官方项目，与 DeepSeek 无关</b> · Apache-2.0 · 纯静态可运行 · 无需 API Key
</p>

> **非官方项目，与 DeepSeek 无关。** DeepSuck 是独立的开源社区项目，与 DeepSeek（深度求索）及其关联公司没有任何关联，未获其授权或背书；名称仅为谐音玩梗，项目不使用其商标、标志或视觉风格。
> *Unofficial project, not affiliated with or endorsed by DeepSeek.*

DeepSuck 是 [apate.ai](https://apate.ai) 思路的开源中文实现：用会聊天的“潜在受害人”人设（糊涂的王阿姨、耳背的李大爷、好奇的大学生小林……）陪骗子周旋——故意误解、请求重复、假装手机卡顿、慢吞吞去找老花镜——消耗骗子的时间，同时自动提取对方暴露的**收款银行卡、支付宝/微信/QQ、手机号、BTC/ETH/TRON 钱包地址、网址**以及**诈骗话术模式**，脱敏后生成结构化情报，用于预防与早期预警。

首个版本：**中文场景优先、文字聊天优先**（语音/电话在路线图中）。

---

## ✨ 功能

- **沙盒演示**：访客扮演骗子，机器人扮演受害人；3 个场景 × 3 个人设，内置一键样例台词。
- **规则/模板人设引擎（默认）**：纯浏览器运行，零成本、零依赖、无需 Key；带打字延迟与 19 种拖延/诱导策略。
- **情报提取**：银行卡（16–19 位，开户行识别 + Luhn 校验）、手机号/400 热线/座机、QQ、微信号、支付宝账号、BTC/ETH/TRON 地址、URL/裸域名、邮箱、身份证、收款户名；以及金额、APP 名称、渠道等上下文线索。
- **话术分类器**：制造紧迫感、冒充公检法、冒充客服、索要验证码、安全账户、诱导下载 APP/屏幕共享、高收益承诺、要求保密、威胁恐吓、情感操控、套取个人信息、加密货币、引流私聊等 15 类，带 0–100 风险评分。
- **默认脱敏**：`6222 **** **** 1234`、`138****5678`、`0x12ab...9f3e`、`https://re***fu.top/***`……展示、导出、甚至发给大模型的内容都先脱敏。
- **情报看板**：“结束对话”后生成迷你情报看板——完整（脱敏）对话记录、情报卡片、话术画像、拖延时长；可导出脱敏 JSON 报告。
- **可选大模型引擎（默认关闭）**：OpenAI 兼容协议，默认对接**阿里云百炼 DashScope（通义千问 qwen-plus）**，也可换成其他国产大模型；自带零依赖 Node 代理，Key 只留在服务器 `.env`。

## 🚀 快速开始

### 方式 A：纯静态（无需任何 Key）

```bash
git clone https://github.com/deepsucksi/deepsuck.git
cd deepsuck/site
python3 -m http.server 8080
# 打开 http://127.0.0.1:8080/  与  http://127.0.0.1:8080/demo.html
```

### 方式 B：接入通义千问（阿里云百炼 / DashScope）

需要 Node.js ≥ 18，**无需 `npm install`**（零依赖）。

```bash
git clone https://github.com/deepsucksi/deepsuck.git
cd deepsuck
cp .env.example .env
# 编辑 .env，填写：DASHSCOPE_API_KEY=sk-xxxxxxxx
npm start
# 打开 http://127.0.0.1:8787/demo.html —— 页面会自动检测到代理并切换到大模型引擎
```

`.env` 可用配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 空 | 百炼 API Key；为空时只用规则引擎 |
| `LLM_API_KEY` | 空 | 其他 OpenAI 兼容服务的 Key（优先级高于上项） |
| `LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 任何 OpenAI 兼容地址 |
| `LLM_MODEL` | `qwen-plus` | 如 `qwen-turbo`、`qwen-max` 或其他厂商模型名 |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | 监听地址 |
| `RATE_LIMIT_PER_MIN` | `20` | 每 IP 每分钟 `/api/chat` 上限，防止 Key 被刷 |

> 也可以在演示页“⚙ 引擎设置”中选择“浏览器直连”，填入 Key 直接从浏览器调用（仅适合本机自用，Key 会存在浏览器里，部分服务商不支持跨域）。推荐使用代理方式。
> 无论选哪种引擎，**情报提取与脱敏始终在本地完成**；大模型失败时自动回退规则引擎。

### 运行测试

```bash
npm test        # 等同于 node --test tests/
```

## 🧱 架构

```
deepsuck/
├── site/                     # 纯静态站点（可直接部署到任意静态托管）
│   ├── index.html            # 首页（中文，支持 EN 切换）
│   ├── demo.html             # 沙盒演示 + 情报看板
│   └── assets/
│       ├── logo.svg          # 原创标志：对话气泡 + 沙漏
│       ├── css/style.css     # 暖琥珀 + 深炭色主题
│       └── js/
│           ├── redact.js     # 脱敏模块（所有展示/导出必经）
│           ├── extractors.js # 情报提取器（正则 + 上下文 + 区间去重）
│           ├── tactics.js    # 话术分类器 + 风险评分
│           ├── scenarios.js  # 场景定义与样例台词（虚构数据）
│           ├── personas.js   # 人设与话术模板
│           ├── engine.js     # 会话状态机 / 规则引擎 / 报告生成
│           ├── llm.js        # 可选：OpenAI 兼容大模型（提示词、脱敏、输出过滤）
│           ├── demo.js       # 演示页 UI
│           └── i18n.js       # 首页中英切换
├── server/index.js           # 可选：零依赖 Node 后端（静态托管 + /api/chat 代理 + 限流）
├── tests/                    # node:test 单元测试
├── docs/ETHICS.md            # 伦理与使用规范
├── .env.example              # 大模型配置模板
└── LICENSE                   # Apache-2.0
```

数据流：

```
骗子消息 ─► extractors（提取）─► redact（脱敏）─► 会话记录（只存脱敏文本）
          └► tactics（话术标签/风险分）
                         │
                         ▼
           engine.chooseIntent（可解释的优先级规则：
           拿到新情报→复述追问；要验证码→拖延；要转账→诱导暴露账户……）
                         │
         ┌───────────────┴────────────────┐
   规则引擎：人设模板                 大模型（可选）：服务端生成系统提示词，
   + 打字延迟                         只发送脱敏记录，输出再过滤长数字串并脱敏
                         │
                         ▼
             侧栏实时情报 / 情报看板 / 脱敏 JSON 报告
```

所有模块都是 UMD 风格的纯 JS，浏览器中挂在 `window.DeepSuck`，Node 中可直接 `require`，测试与后端共用同一套代码。

导出报告格式（节选）：

```json
{
  "schema": "deepsuck.intel-report/v0.1",
  "session": { "scenario": { "id": "police" }, "persona": { "id": "wang" }, "engine": "rule" },
  "stats": { "messages": 13, "estimatedScammerSeconds": 608, "intelCount": 4, "riskScore": 90 },
  "intel": [{ "type": "bank_card", "masked": "6222 **** **** 3445", "meta": { "bank": "工商银行", "luhn": false } }],
  "tactics": [{ "id": "safe_account", "label": "要求转账至安全账户", "count": 1 }],
  "transcript": [{ "role": "scammer", "text": "……6222 **** **** 3445，户名王**……" }]
}
```

## ☁️ 部署（零/低成本）

纯静态部分（`site/` 目录）可直接部署，无需构建：

- **GitHub Pages**：将 `site/` 作为发布目录（已含 `.nojekyll`），或用 Actions 发布。免费。
- **Cloudflare Pages**：构建命令留空，输出目录 `site`。免费，自带 HTTPS/CDN。
- **阿里云 OSS 静态网站托管**：上传 `site/` 内容并开启静态页面（默认首页 `index.html`），可配合 CDN；按量计费、流量很小时几乎零成本。注意：中国大陆地域绑定自定义域名需要 ICP 备案。
- **小型云服务器（阿里云 ECS/轻量应用服务器）**：需要大模型代理时，用 `npm start`（建议 systemd/pm2 守护），前面放 Nginx + HTTPS，`HOST` 保持 `127.0.0.1` 由 Nginx 反代；务必设置 `RATE_LIMIT_PER_MIN` 并在百炼控制台设置费用告警。

> `.si` 域名（deepsuck.si）目前尚未上线，本仓库不包含任何部署或 DNS 操作。

## 🛡️ 伦理与使用声明（底线）

详见 [docs/ETHICS.md](docs/ETHICS.md)。要点：

1. **只防御，不出击**：机器人永不主动联系任何真实的人；演示中由访客自己扮演骗子。
2. **默认脱敏**：情报在展示、导出、发送给大模型前一律打码；原文仅存在于页面内存。
3. **不提供真实信息**：人设绝不给出真实验证码、卡号、密码、身份证；大模型输出经过安全过滤。
4. **禁止滥用**：不得用于骚扰、人肉、报复、“反向诈骗”、攻击任何系统或任何违法用途。
5. **交给专业力量**：遇到诈骗请拨打 **110** 或全国反诈专线 **96110**，并通过“国家反诈中心”APP 举报。
6. **合规优先**：接入真实渠道前，请评估《个人信息保护法》《反电信网络诈骗法》等要求并取得必要授权。

## 🗺️ 路线图

- [x] v0.1 纯静态沙盒、规则人设引擎、提取器/分类器/脱敏、情报看板、可选百炼代理
- [ ] **大模型人设引擎**：多轮记忆、人设一致性评测、提示词注入防护、本地模型（Ollama 等）支持
- [ ] **更多场景与人设**：刷单返利、虚假贷款/征信修复、冒充熟人/领导、游戏交易、网络购物
- [ ] **情报共享 API**（规划中）：统一 schema、只共享脱敏或哈希化指标（加盐、可撤回）、来源可信度评分；优先对接官方反诈渠道而非公开曝光
- [ ] **蜜罐集成**（规划中，需伦理评审）：仅接入**自有/授权**的诱饵号码与诱饵账号；不冒用他人身份、不诱导第三方、不留存无关个人信息；保留审计日志
- [ ] **电话接入**（规划中，详细方案另行研究）：
  - 语音：流式 ASR（语音转文字）+ TTS（人设音色）+ 打断/延迟控制
  - 呼叫转移：将陌生/疑似诈骗来电转接给 AI 接听
  - SIP/VoIP 网关对接
  - 需满足电信与录音合规要求，默认告知与最小化留存

## 🤝 参与贡献

欢迎 Issue 与 PR！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。几个好上手的方向：

- 在 `scenarios.js` 增加场景与**虚构**样例台词；
- 在 `personas.js` 增加更“磨人”的人设或模板；
- 在 `extractors.js` / `tactics.js` 改进规则，并在 `tests/` 补充用例；
- 改进无障碍、移动端体验与英文翻译。

提交前请运行 `npm test`。请勿在 Issue/PR 中提交任何真实、未脱敏的个人信息或账户。

## ⚖️ 免责声明

本项目按“现状”提供，仅用于防诈研究与公众教育，不构成法律或安全建议。演示中的所有账号、电话、地址与网址均为虚构测试数据，如与真实信息雷同纯属巧合。提取结果可能存在误报/漏报，仅可作为线索参考。使用者须自行遵守所在地法律法规，因不当使用造成的任何后果由使用者自行承担。**DeepSuck 为非官方项目，与 DeepSeek 无关。**

## 📄 许可证

[Apache License 2.0](LICENSE) © DeepSuck contributors
