# DeepSuck 语音演示（voice/）

> 仅供防诈研究与教育：**只在浏览器里自己扮演骗子**，不要接入电话网络、不要拨打或接听任何真实号码。

一个本地跑的级联语音管线：你对着浏览器麦克风扮演骗子，DeepSuck 用"王阿姨/李大爷/小林"的声音陪你周旋，同时在看板上实时显示抽取到的（已脱敏）情报、识别出的话术和本轮策略。

```
浏览器麦克风 ──SmallWebRTC──▶ Paraformer 实时 ASR ──▶ IntelProcessor ──▶ qwen-plus ──▶ 输出守卫 ──▶ CosyVoice TTS ──SmallWebRTC──▶ 浏览器扬声器
                                                     │ 情报抽取 / 话术识别 / 黑名单比对
                                                     │ 规则引擎选策略 → 改写系统提示词
                                                     │ 插播拖延填充音（"哎……你等一下啊"）
                                                     └──数据通道──▶ 浏览器实时看板
```

## 需要什么

- **DashScope（阿里云百炼）API Key**：ASR、TTS、大模型三项都走它。**没有 key 时页面能打开，但无法开始通话。** 按量计费，费用以百炼控制台为准。
- Python ≥ 3.11（Pipecat 1.12 的要求），以及能访问 `dashscope.aliyuncs.com` 的网络。
- 一个支持 WebRTC 的浏览器（Chrome / Edge / Firefox / Safari）。

## 一条命令跑起来

```bash
# 在仓库根目录
python -m venv .venv && source .venv/bin/activate
pip install -r voice/requirements.txt
cp voice/.env.example voice/.env   # 填入 DASHSCOPE_API_KEY
python -m voice.app                 # 打开 http://localhost:7860
```

选择人设和场景 → 点「开始通话」→ 允许麦克风。机器人会先开口，然后你可以试着用"退款理赔""冒充公检法""刷单返利"等话术"诈骗"它，说出（编造的）卡号、网址、钱包地址，看板会实时出现脱敏后的情报。

可选参数：

| 参数 | 说明 |
|---|---|
| `--engine rule` | 不调用大模型，用规则引擎（与网页版同一套模板）出话；仍需 ASR/TTS |
| `--host` / `--port` | 默认 `127.0.0.1:7860` |

## 组成

| 文件 | 作用 |
|---|---|
| `dashscope_ws.py` | DashScope WebSocket 协议（run-task / continue-task / finish-task）的最小实现：`synthesize()` 流式 TTS、`ParaformerStream` 实时识别。不依赖 dashscope SDK |
| `services.py` | Pipecat 自定义服务 `ParaformerSTTService`、`CosyVoiceStreamTTSService`（长连接、边吐字边合成、打断取消；旧的每句一连接 `CosyVoiceTTSService` 保留作回退） |
| `processors.py` | `IntelProcessor`（情报/话术/策略）、`FillerProcessor`（按延迟触发的填充音）、`BotTextTap`、`GuardTextFilter` |
| `interrupt.py` / `tuning.py` / `textagg.py` | 中文打断策略（"嗯/对"不打断）、网页/电话两套延迟参数、流式分句器 |
| `latency.py` | 每轮延迟拆解（`LatencyObserver`） |
| `persona.py` | 由 `site/assets/core/personas.json` 生成系统提示词；填充音台词；输出守卫 |
| `app.py` | FastAPI + SmallWebRTC 信令（`/api/offer`）+ 管线组装；`python -m voice.app` |
| `static/` | 浏览器端（原生 WebRTC，无构建步骤） |
| `guard.py` | 费用护栏：每日预算（预占 + 实时记账 + 持久化）、并发/每 IP 限制、时长/轮数/静默看门狗 |
| `netpatch.py` | UDP 端口段限制、公网 IP 候选（服务器部署用） |
| `probe.py` | `python -m voice.probe`：aiortc 端到端探针（部署后验证 UDP/ICE；`--json-out` 输出逐句端到端延迟） |
| `smoke.py` | `python -m voice.smoke --out x.wav`：真实调用 qwen-plus → CosyVoice → Paraformer 的冒烟测试 |
| `telephony/` | 电话接入抽象层（默认关闭）：`TelephonyAdapter` 基类 + 注册表，`ws-raw` 通用 SIP/WebSocket 适配器、`pipecat-ws`（Twilio/Telnyx/Plivo/Exotel）；阿里云呼入适配器设计稿。见 [telephony/README.md](telephony/README.md) |

人设音色：王阿姨 `longlaoyi_v3`（龙老姨），李大爷 `longlaobo_v3`（龙老伯），小林 `longanyang`。

## 隐私与安全

- 交给大模型的只有**脱敏后**的转写文本；卡号等原值只在本进程内存里用于黑名单比对，不写盘、不上报。
- 浏览器看板只收到脱敏值。默认**不保存原始音频**；每通结束只在 `$DATA_DIR/voice/transcripts/` 写一份脱敏文字记录（落盘前调用 `deepsuck.redact.redact_text`，默认保留 30 天）。`KEEP_AUDIO=1` 才保存双方 WAV，最多保留 7 天，启动时和每小时自动清理（`voice/records.py`）。填充音缓存在 `~/.cache/deepsuck/voice/`，只是机器人自己的台词。
- 开场 AI 告知语默认不播，`VOICE_AI_DISCLOSURE=1` 打开、`VOICE_AI_DISCLOSURE_TEXT` 自定义（网页和电话都生效）。电话与留存相关环境变量清单见 [docs/PHONE.md 第 6 节](../docs/PHONE.md#6-环境变量清单供-deploy-使用)。
- 输出守卫会去掉括号动作 / Markdown，抹掉 5 位以上数字串，防止机器人编造"验证码""卡号"。
- 黑名单比对默认读 `https://deepsuck.si/data/blocklist/`（destroylist、Phishing.Database、OFAC 等，见 `docs/INTEL.md`）。

## 公开部署与费用护栏

部署到服务器见 [docs/DEPLOY.md](../docs/DEPLOY.md)（`deploy/` 下 Docker Compose + Caddy）。护栏（`guard.py`，全部可用环境变量调）：
每日预算 `VOICE_DAILY_BUDGET_CNY`（按 ASR 秒数 / TTS 字符 / LLM token 实时记账，开局按最坏花费预占）、
同时通话 `VOICE_MAX_SESSIONS=2`、每局 `VOICE_MAX_MINUTES=5` / `VOICE_MAX_TURNS=30`、静默 `VOICE_IDLE_SECONDS=60`、
每 IP `VOICE_PER_IP_PER_HOUR=4` / `VOICE_PER_IP_PER_DAY=10`、`/api/offer` Origin 白名单 `VOICE_ALLOWED_ORIGINS`。
本地开发不设这些变量时不限额。触发上限时机器人会说一句告别语再挂断，浏览器看板显示原因。

WebRTC 网络（`netpatch.py`）：`VOICE_UDP_PORTS=40000-40199` 把 aioice 的 UDP 端口限制在一段内（防火墙只开这段）；
`VOICE_PUBLIC_IP` 在应答 SDP 里追加“公网 IP + 同端口”候选（云服务器 1:1 NAT 下不依赖 STUN/TURN）。

端到端探针（aiortc 充当浏览器，真实调用、计费）：

```bash
python -m voice.probe --url http://127.0.0.1:7860 --wav scammer16k.wav --seconds 30
```

## 延迟

2026-10-18 一轮优化（同一段 6 句合成骗子音频，客户端测"骗子停说 → 听到机器人"，毫秒）：

| | P50 | P90 |
|---|---|---|
| 优化前（回复本身） | 5842 | 6282 |
| 优化后，首个可听音频（填充音） | 1653 | 2803 |
| 优化后，回复本身（关闭填充音，3 句） | 4162 | 5827 |

TTS 首包 P50 2781 → 1385，ASR 判停到最终结果 P50 1382 → 1060。做法、参数、测量方法和已知副作用见 [docs/VOICE_LATENCY.md](../docs/VOICE_LATENCY.md)。

## 测试

```bash
pip install -r voice/requirements.txt
python -m pytest voice/tests -q    # 全部用假 WebSocket，不联网、不需要 key
```

## 已知限制

- ~~Paraformer 的数字规整（ITN）会把"张三"转成"张3"，导致姓名抽取漏掉~~：v0.4 起收款户名里的单个阿拉伯数字会还原为汉字（`张3` → `张三`，JS/Python 一致）。
- 打断（barge-in）：机器人说话时需要说出 2 个以上有效字（电话 3 个）才打断，"嗯/对/好的"不打断；门槛是按合成音频定的，没用真人通话校准过。
- 只在 Linux + Chrome（伪造麦克风输入）下做过端到端测试；真实麦克风、回声消除、移动端浏览器未测。
- 使用 Pipecat 1.12 的 `PipelineTask` / 上下文内 system 消息（2.0 将移除），已在 requirements 中锁 `<2`。
