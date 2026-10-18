# 5 分钟自托管上手（docs/QUICKSTART.md）

从 `git clone` 到在本机跑起沙盒、接入通义千问、打开语音演示，以及电话接入的现状。每一步都能单独停下：**不填任何 Key，项目照常以规则引擎运行。**

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

## 6. 电话接入：适配层已有，默认关闭，只接不拨

**现状（以仓库代码为准）**

- `voice/telephony/` 已有电话接入抽象层（`TelephonyAdapter` 接口与注册表）和两个适配器：
  - `ws-raw`：极简 WebSocket 协议，一条连接对应一通电话；SIP 协议栈放在独立进程里（FreeSWITCH、Asterisk 或自写 UAS）。
  - `pipecat-ws`：复用 Pipecat 内置的 Twilio、Telnyx、Plivo、Exotel 媒体流序列化器，适合海外部署或兼容 Twilio Media Streams 的网关。
- 入口**默认关闭**：不设置 `VOICE_TELEPHONY=1` 和 `VOICE_TELEPHONY_TOKEN` 时，路由根本不注册。
- 代码**只接听、不外呼**，仓库里没有任何发起呼叫的代码。电话入口和浏览器入口共用并发名额、每日预算，以及时长、轮数、静默护栏。
- `deploy/` 已带电话入口开关，默认关闭（`VOICE_TELEPHONY=0`）。
- 阿里云语音服务「智能语音交互呼入」适配器**只有设计稿**，尚未实现。阿里云 SIP Trunk（语音中继）是邀约制，需要企业实名与资质、固定公网 IP，个人一般开不了。

**本地联调**：启用方法、`ws-raw` 协议、`pipecat-ws` 的凭据变量和测试命令，统一以 [voice/telephony/README.md](../voice/telephony/README.md) 为准，这里不重复，避免两处不一致。单元测试走本地回环 WebSocket，不连服务商，也不拨打电话。

**已定政策**（标“计划”的是代码尚未实现的部分）

| 事项 | 决定 | 代码现状 |
|---|---|---|
| 号码 | 本轮不购买号码 | 不涉及代码 |
| 开场告知语 | 可配置，默认**不播** | **已实现**：网页和电话都默认不播；设 `VOICE_AI_DISCLOSURE=1` 才播，文案用 `VOICE_AI_DISCLOSURE_TEXT` 自定义。旧变量 `VOICE_TELEPHONY_DISCLOSURE` 已废弃 |
| 原始音频 | 默认不保留 | **已实现**：默认不保存；设 `KEEP_AUDIO=1` 才保存，最多保留 7 天（`KEEP_AUDIO_DAYS`），启动时和之后每小时清理过期文件 |
| 文字记录 | 只保留经共享脱敏模块 `python/deepsuck/redact.py` 处理后的文本 | **已实现**：每通结束保存一份，写盘前逐条经 `redact_text` 脱敏，文件名不含号码；`VOICE_TRANSCRIPTS=0` 可关闭，默认保留 30 天 |
| 公网部署 | `deploy/` 中的电话入口默认关闭，保留开关 | **已实现**：`deploy/.env.example` 暴露 `VOICE_TELEPHONY`、`VOICE_TELEPHONY_TOKEN`、`VOICE_AI_DISCLOSURE`、`KEEP_AUDIO` 等，默认全关，变量清单见 [PHONE.md 第 6 节](PHONE.md#6-环境变量清单供-deploy-使用)；`DATA_DIR` 挂命名卷 `voice-data` |
| 断句静音 | 网页暂保持 450ms | 已是默认值（`DEEPSUCK_LAT_ASR_MAX_SILENCE_MS`，见第 7 节） |

无论接入方式如何变化，底线不变：**只做防御，机器人从不主动外呼或联系真实的人**（见 [ETHICS.md](ETHICS.md)）。接入方案对比、推荐方案和月成本见 [PHONE.md](PHONE.md)：长期走阿里云 SIP 中继（需企业主体），现阶段海外号码接 `pipecat-ws` 只做联调演示；移动和电信不能呼转到境外号码，跨境转接走不通。

## 7. 语音延迟调参

填充音、打断、流式合成的做法、测量方法和前后对比数据见 [VOICE_LATENCY.md](VOICE_LATENCY.md)。以下可调参数取自该文档：网页用 `DEEPSUCK_LAT_<字段>`，电话用 `DEEPSUCK_PHONE_LAT_<字段>`。

| 字段 | 网页 | 电话 | 含义 |
|---|---|---|---|
| `ASR_MAX_SILENCE_MS` | 450 | 500 | Paraformer 断句静音（200–6000） |
| `VAD_CONFIDENCE` | 0.75 | 0.8 | Silero 置信度 |
| `VAD_START_SECS` | 0.3 | 0.3 | 判定开口所需语音时长 |
| `VAD_STOP_SECS` | 0.2 | 0.3 | 判定停说所需静音时长 |
| `VAD_MIN_VOLUME` | 0.6 | 0.5 | 最小音量 |
| `INTERRUPT_MIN_CHARS` | 2 | 3 | 机器人说话时打断所需有效字数 |
| `FILLER_DELAY_MS` | 650 | 650 | 停说后多久仍无首 token 就播填充音；0 关闭 |
| `TTS_CLAUSE_MIN_CHARS` | 6 | 6 | 逗号处切分前至少攒的字数 |

另有 `DEEPSUCK_TTS_STREAM=0`，可回退到旧的每句一连接合成。例如 `DEEPSUCK_LAT_ASR_MAX_SILENCE_MS=500` 就是把网页断句静音调到 500ms。

## 常见问题

| 现象 | 处理 |
|---|---|
| 网址显示“黑名单不可用” | 运行 `npm run blocklists` |
| 沙盒没切到大模型 | 看 `/api/health` 的 `llmConfigured`；`.env` 改完要重启 `npm start` |
| 明明没填 Key 却在计费 | shell 环境变量里有 Key，见第 2 节的提示 |
| 语音页一直“连接中” | 本机一般不会遇到；服务器上见 DEPLOY.md 的“故障排查” |
