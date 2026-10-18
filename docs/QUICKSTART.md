# 5 分钟自托管上手（docs/QUICKSTART.md）

从 `git clone` 到在本机跑起沙盒、接入通义千问、打开语音演示。每一步都能单独停下：**不填任何 Key，项目照常以规则引擎运行。**

## 0. 你需要

| 必需 | 可选 |
|---|---|
| Git、Node.js ≥ 18（项目零依赖，无需 `npm install`） | 阿里云百炼（DashScope）API Key，北京地域：<https://bailian.console.aliyun.com/> → API-KEY |
| | Python ≥ 3.11（只有语音演示需要） |

## 1. 只看效果：无 Key，约 30 秒

```bash
git clone https://github.com/deepsucksi/deepsuck.git && cd deepsuck
npm run blocklists   # 可选，约 3 秒：拉取公开钓鱼域名黑名单（destroylist、Phishing.Database，MIT）
npm start            # 打开 http://127.0.0.1:8787/demo.html
```

- `npm run blocklists` 生成 `site/data/blocklist/`（约 60 万域名、256 个分片、17 MB，已在 `.gitignore`）。不跑也能用，只是沙盒里网址会显示“黑名单不可用”。
- 不需要后端时也可以纯静态托管：`cd site && python3 -m http.server 8080`。这时沙盒不会请求任何 `/api/`。

**无 Key 时的行为**：`/api/health` 返回 `llmConfigured: false`；`/api/chat` 返回 503 并附中文提示；沙盒“引擎设置”里显示“代理在线，但未配置 API Key”，对话自动使用浏览器内的规则引擎。情报提取、脱敏和黑名单比对都照常在本地完成。

## 2. 接入通义千问（文字对话）：约 1 分钟

```bash
cp .env.example .env
# 编辑 .env，只需要填一行：DASHSCOPE_API_KEY=sk-...
npm start
curl -s http://127.0.0.1:8787/api/health   # llmConfigured: true
```

刷新沙盒，页面会自动切到“大模型 · 本地代理”。任何调用失败都会回退到规则引擎。

| 变量 | 默认 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 空 | 百炼 Key；为空就只用规则引擎 |
| `LLM_MODEL` | `qwen-plus` | 也可以填 `qwen-turbo`、`qwen-max` 等 |
| `LLM_BASE_URL` | 百炼兼容模式地址 | 任何 OpenAI 兼容接口都可以 |
| `CHAT_DAILY_BUDGET_CNY` | `0`（不限） | **本地也建议设一个**，例如 `1` |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | 监听地址 |

> **注意：进程环境变量优先于 `.env`。** `server/index.js` 和 `voice/app.py` 都只会用 `.env` 补上*尚未设置*的变量。如果你的 shell 里已经 `export` 了 `DASHSCOPE_API_KEY`（或 `LLM_API_KEY`），即使 `.env` 留空也会用它，并按量计费。只想跑规则引擎时，可以用 `env -u DASHSCOPE_API_KEY -u LLM_API_KEY npm start`。

## 3. 语音演示（浏览器麦克风）：约 3 分钟，需要 Key

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r voice/requirements.txt   # pipecat-ai 1.12 等，约 20 秒
python -m voice.app                     # 打开 http://localhost:7860
```

- 语音服务会依次读取 `voice/.env` 和根目录 `.env`，所以同一个 `DASHSCOPE_API_KEY` 就够了（ASR、LLM、TTS 都走百炼）。
- 没有 Key 时页面能打开，但点“开始通话”会提示 503：未配置 DASHSCOPE_API_KEY。
- 建议加上 `VOICE_DAILY_BUDGET_CNY=1`。默认每 IP 每小时 4 通、同时 2 路、每通 5 分钟。
- 想一条命令同时起文字代理和语音：在已激活的 venv 里运行 `npm run dev`（用 `npx concurrently` 并排启动两个进程；语音缺依赖时，代理照常运行）。

## 4. 验证

```bash
npm test                                  # JS 单元测试
cd python && python -m pytest -q && cd .. # Python 核心
python -m pytest voice/tests -q           # 语音（假 WebSocket，不联网、不要 Key）
curl -s http://127.0.0.1:7860/api/voice/health
```

## 5. 上线（可选）

静态站可以直接放在 GitHub Pages、Cloudflare Pages 或 OSS 上（发布 `site/` 目录即可）。要对公网开放大模型对话和语音，见 [DEPLOY.md](DEPLOY.md)（Docker Compose + Caddy 自动 HTTPS，带每日预算、限流和并发护栏）。部署时请把域名和证书邮箱换成**你自己的**。

## 6. 来电转接到 AI：目前只在设计中

现在**没有**可运行的电话接入代码，也不支持 Twilio、SIP 中继等云通信。已有的语音演示只用浏览器麦克风。

规划中的方案（iPhone 静音陌生来电 → 运营商无应答转移 `**61*` → 本人实名副卡 → EC20/EG25 4G 模组；多线路再用 Asterisk）、合规边界和待验证项见 [PHONE.md](PHONE.md)。欢迎在 Issue 里认领和实测。

## 常见问题

| 现象 | 处理 |
|---|---|
| 网址显示“黑名单不可用” | 运行 `npm run blocklists` |
| 沙盒没切到大模型 | 看 `/api/health` 的 `llmConfigured`；`.env` 改完要重启 `npm start` |
| 明明没填 Key 却在计费 | shell 环境变量里有 Key，见第 2 节的提示 |
| 语音页一直“连接中” | 本机一般不会遇到；服务器上见 DEPLOY.md 的“故障排查” |
