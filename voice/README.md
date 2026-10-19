# DeepSuck 语音演示（voice/）

> 仅供防诈研究与教育：**只在浏览器里自己扮演骗子**，不要接入电话网络、不要拨打或接听任何真实号码。

一个本地跑的级联语音管线：你对着浏览器麦克风扮演骗子，DeepSuck 用四位人设（王阿姨 / 小陈妈妈 / 小林 / 郑老板，与首页同一组编号、身份和头像）的声音陪你周旋，同时在看板上实时显示抽取到的（已脱敏）情报、识别出的话术和本轮策略。

```
浏览器麦克风 ──SmallWebRTC──▶ Paraformer 实时 ASR ──▶ IntelProcessor ──▶ qwen3.7-flash ──▶ 输出守卫 ──▶ CosyVoice TTS ──SmallWebRTC──▶ 浏览器扬声器
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
| 环境变量 `DEEPSUCK_LLM_MODEL` / `DEEPSUCK_LLM_THINKING` | 语音大模型，默认 `qwen3.7-flash`、思考关（显式发 `enable_thinking=false`）；单价按模型查 `guard.py` 的 `LLM_PRICES`，选型见 [docs/LLM_AB.md](../docs/LLM_AB.md) |
| `--engine rule` | 不调用大模型，用规则引擎（与网页版同一套模板）出话；仍需 ASR/TTS |
| `--host` / `--port` | 默认 `127.0.0.1:7860` |

## 组成

| 文件 | 作用 |
|---|---|
| `dashscope_ws.py` | DashScope WebSocket 协议（run-task / continue-task / finish-task）的最小实现：`synthesize()` 流式 TTS、`ParaformerStream` 实时识别。不依赖 dashscope SDK |
| `services.py` | Pipecat 自定义服务 `ParaformerSTTService`、`CosyVoiceStreamTTSService`（长连接、边吐字边合成、打断取消；旧的每句一连接 `CosyVoiceTTSService` 保留作回退） |
| `processors.py` | `IntelProcessor`（情报/话术/策略）、`FillerProcessor`（回合结束播预合成短口头语；`DEEPSUCK_BACKCHANNEL=0` 时按延迟触发填充音）、`BotTextTap`、`GuardTextFilter` |
| `backchannel.py` | 短口头语：说不说的规则（话太短/催促/短追问不说）、随机轮换不连续重复、缓存目录与裁静音 |
| `interrupt.py` / `tuning.py` / `textagg.py` | 中文打断策略（"嗯/对"不打断）、网页/电话两套延迟参数、流式分句器 |
| `llm_ab.py` | `python -m voice.llm_ab`：同一组诈骗脚本对比几个大模型（抢话、口语风格、守卫触发、首字延迟、每通成本），会真实计费 |
| `latency.py` | 每轮延迟拆解（`LatencyObserver`） |
| `persona.py` | 由 `site/assets/core/personas.json` 生成系统提示词；填充音台词；输出守卫 |
| `app.py` | FastAPI + SmallWebRTC 信令（`/api/offer`）+ 管线组装；`python -m voice.app` |
| `static/` | 浏览器端（原生 WebRTC，无构建步骤） |
| `guard.py` | 费用护栏：每日预算（预占 + 实时记账 + 持久化）、并发/每 IP 限制、时长/轮数/静默看门狗 |
| `netpatch.py` | UDP 端口段限制、公网 IP 候选（服务器部署用） |
| `probe.py` | `python -m voice.probe`：aiortc 端到端探针（部署后验证 UDP/ICE；`--json-out` 输出逐句端到端延迟） |
| `smoke.py` | `python -m voice.smoke --out x.wav`：真实调用 qwen-plus → CosyVoice → Paraformer 的冒烟测试 |
| `telephony/` | 电话接入抽象层（默认关闭）：`TelephonyAdapter` 基类 + 注册表，`ws-raw` 通用 SIP/WebSocket 适配器、`pipecat-ws`（Twilio/Telnyx/Plivo/Exotel）；阿里云呼入适配器设计稿。见 [telephony/README.md](telephony/README.md) |

人设音色：王阿姨 `longlaoyi_v3`（龙老姨），小林 `longanyang`。小陈妈妈、郑老板的音色等负责人试听后再定，在此之前用默认音色 `longlaoyi_v3`，见下文“新人设音色与底噪（待语音工程师接手）”。

人设选项：页面按 `/api/config` 的 `personas`（`id`、`no`、`role`、`name`、`photo`）渲染成与首页一样的头像卡片；`?persona=<id>` 直达某个人设，首页卡片的“体验”链接就带这个参数。别名按 `aliases` 解析：`li`（已下线）→ `wang`，`xiaochen` / `mom` → `chen`，`shop_owner` → `zheng`。

设计音色（可选）：CosyVoice 支持按一段文字描述生成专属音色，生成的音色只属于你自己的百炼账号。
`python -m voice.design_voice wang --preview wang.wav` 会生成王阿姨的设计音色并打印一行 `DEEPSUCK_VOICE_WANG=...`。本地运行（`python -m voice.app`）填进 `voice/.env`；用 `deploy/` 的 Docker Compose 自托管时填进 `deploy/.env`（compose 的 voice 服务只读 `deploy/.env`，改完 `docker compose up -d` 重建容器）；
模型会按音色 ID 自动选（如 `cosyvoice-v3.5-flash`），也可用 `DEEPSUCK_VOICE_WANG_MODEL` 指定。
`DEEPSUCK_VOICE_WANG_INSTRUCTION` 可给设计音色加朗读指令（如「请用东北话表达。」），默认不加，填 `0` 或 `off` 也是不加；系统音色不会发送指令。
其他人设同理（`DEEPSUCK_VOICE_LI`、`DEEPSUCK_VOICE_LIN`）。不设置时用上面的系统音色。

设计音色费用（2026-10-18 查询阿里云百炼官方公开价格页，华北 2（北京）原价，不含限时优惠，**以百炼控制台计费页为准**）：

- 创建设计音色：CosyVoice 系列免费（[声音设计](https://help.aliyun.com/zh/model-studio/voice-design-user-guide)「计费说明」）；
- 用设计音色合成：按目标模型 `cosyvoice-v3.5-flash` 计费，**0.8 元/万字符**（[cosyvoice-v3.5-flash 模型信息](https://help.aliyun.com/zh/model-studio/cosyvoice-v3-5-flash)），一句 50 字左右的回复约 0.004 元；原来的系统音色走 `cosyvoice-v3-flash`，1 元/万字符（[cosyvoice-v3-flash 模型信息](https://help.aliyun.com/zh/model-studio/cosyvoice-v3-flash)）；
- 音色保有费：官方页面未列出，以百炼控制台计费页为准。每个账号自定义音色（复刻 + 设计）上限 1000 个，不用的可以删掉。

费用护栏 `guard.py` 默认按 0.8 元/万字符记账（`PRICE_TTS_PER_10K_CHARS`，对应现用的设计音色）；换回系统音色时可设成 1，偏保守。

## 隐私与安全

- 交给大模型的只有**脱敏后**的转写文本；卡号等原值只在本进程内存里用于黑名单比对，不写盘、不上报。
- 浏览器看板只收到脱敏值。默认**不保存原始音频**；每通结束只在 `$DATA_DIR/voice/transcripts/` 写一份脱敏文字记录（落盘前调用 `deepsuck.redact.redact_text`，默认保留 30 天）。`KEEP_AUDIO=1` 才保存双方 WAV，最多保留 7 天，启动时和每小时自动清理（`voice/records.py`）。口头语音频缓存在 `$DATA_DIR/voice/fillers/`（无 `DATA_DIR` 时 `~/.cache/deepsuck/voice/`，可用 `DEEPSUCK_FILLER_CACHE_DIR` 指定），只是机器人自己的台词。
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

短口头语（默认开，`DEEPSUCK_BACKCHANNEL=0` 关）：回合结束即播预合成的"嗯……""啊？你说啥"，并告诉大模型别再以语气词开头。本地 4 次 probe 客户端首个声音 P50 约 1280 ms（开关相同，首个声音由回合判定决定；比上午约 1650 ms 快的部分来自裁掉合成音频开头 0.34–0.47 s 静音）；正式回复以语气词开头从 9/14 降到 3/14。详见 VOICE_LATENCY.md「短口头语」。

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

## 断续停顿与环境底噪

- **断续停顿**：回复里的「…」不再读成逗号，而是当停顿。流式 TTS 遇到以「…」结尾的分句，就把这一句单独合成，结束后插 300 到 900 毫秒的随机静音，再接下一句。每个回合的第一句走原来的路径，所以首包延迟不变。`DEEPSUCK_PAUSE_MS=300-900` 调范围，`DEEPSUCK_PAUSES=0` 关闭（省略号退回读成逗号）。CosyVoice 的 SSML `<break>` 要求整段文字一次发完，没法边生成边合成，所以没有用它。
- **环境底噪**：`voice/ambience.py` 按人设给发出去的音频混一层低音量循环底噪：王阿姨是厨房，小林是街道；小陈妈妈、郑老板的建议底噪写在 `personas.json` 的 `ambience`（`living_room`、`shop`），素材批准前用默认的厨房。网页通话和 SIP 电话都会混。底噪只加在发给对方的音频上，不进 ASR，也不影响打断。`DEEPSUCK_AMBIENCE=0` 关闭，填 `kitchen`、`street` 或 `tv` 可以强制用某一段；`DEEPSUCK_AMBIENCE_VOLUME` 调音量，默认 0.2，大约比说话低 28 dB。素材出处和授权见 `voice/assets/ambience/SOURCES.md`。

## 新人设音色与底噪（待语音工程师接手）

#11 把人设统一成四位，数据都在 `site/assets/core/personas.json`。王阿姨的说话风格、音色和厨房底噪是已批准的质量线，不动。小陈妈妈（`chen`）和郑老板（`zheng`）的文字部分已上线，音色和底噪要等负责人试听后再上：

| 字段 / 位置 | 小陈妈妈 `chen` | 郑老板 `zheng` | 说明 |
| --- | --- | --- | --- |
| `personas.json` → `ambience` | `living_room` | `shop` | 建议底噪名。`voice/ambience.py` 只采用 `SOUNDS` 里已有的名字，没有素材时退回 `DEFAULT_SOUND`（厨房） |
| `personas.json` → `voiceHint` | 见文件 | 见文件 | 建议音色描述（性别、语速、口音），供挑系统音色或用 `voice.design_voice` 设计音色 |
| `personas.json` → `voiceTraits` | 已填 | 已填 | 口头语 `backchannel`、听错反问、语速与停顿；`voice/persona.py` 运行时读取 |
| `personas.json` → `voiceStyle` / `voiceShots` | 已填 | 已填 | 语音线说话风格与 15 条示范句，照王阿姨的标准写 |
| 环境变量 | `DEEPSUCK_VOICE_CHEN` | `DEEPSUCK_VOICE_ZHENG` | 试听用，不改代码就能换音色（同样支持 `_MODEL`、`_INSTRUCTION`） |
| `voice/dashscope_ws.py` → `PERSONA_VOICES` | 未设 | 未设 | 试听通过后把选定音色写进来；未设时用 `DEFAULT_VOICE` |
| `voice/ambience.py` → `SOUNDS` | 加 `living_room` | 加 `shop` | 素材放 `voice/assets/ambience/`，24 kHz 单声道 Ogg，-26 dBFS RMS，出处写进 `SOURCES.md` |

上线顺序：语音工程师准备音色和素材 → 负责人试听 → 写进 `PERSONA_VOICES` 与 `SOUNDS` → 部署。

## 通话追踪与问题反馈

代码在 `voice/trace.py`，字段表（schema v2，与 #18 磁盘监控、#20 成本监控共用）在 [docs/TRACE_SCHEMA.md](../docs/TRACE_SCHEMA.md)。

- 每通一个 8 位通话编号（base32），页面显示、可复制，每行 trace 都带 `call_id`。
- 文字每通都存：每轮一行 JSONL（ASR 文本、人设回复、意图、情报、延迟拆解、模型名、大模型输入/输出 token、首字/整句延迟、ASR 音频秒数、TTS 字数和音色、是否被打断、提示词和代码版本）；结束写一行汇总（起止时间、时长、退出原因、是否同意录音、用量合计、估算花费）。
- 录音：网页「开始通话」旁的复选框（默认勾选）随 `/api/offer` 的 `consent` 传给服务端（只认 JSON `true`），勾选才录两轨（对方、人设），由 Pipecat `AudioBufferProcessor` 分轨回调，后台线程边收边编码成 16k 单声道 ogg/opus（约 2 KB/秒/轨）。
- 「这通有问题」：页面带 `/api/offer` 发的一次性 `feedback_key` POST `/api/feedback/<编号>`（同一 IP 每分钟 6 次、每通 5 条、通话开始 6 小时内），写成 `feedback` 行（`flagged: true`）。
- 电话线路（SIP）：只存脱敏文字、不录音，主叫号码按 `mask_phone` 打码，consent 记为 `sip-text-only`。
- 文字落盘前都过一遍共享的 `redact_text(text, extract_sensitive(text))`，再补自报姓名规则（「我叫张伟」→「我叫张*」）。

读取（不对公众）：`GET /api/traces?since=&limit=`、`GET /api/traces/<编号>`、`GET /api/traces/<编号>/audio/<scammer|persona>`，需 `Authorization: Bearer $TRACE_ADMIN_TOKEN`（常量时间比较）；没配 token 或请求带 `X-Forwarded-For`（经 Caddy 进来）时一律 404；Caddy 对 `/api/traces*` 直接 404。服务器上直接用命令行：

    docker exec deepsuck-voice-1 python -m voice.trace_cli --list
    docker exec deepsuck-voice-1 python -m voice.trace_cli <编号> --audio
    docker exec deepsuck-voice-1 python -m voice.trace_cli --flagged          # 被标记有问题的通话
    docker exec deepsuck-voice-1 python -m voice.trace_cli --usage --days 7   # 按天用量汇总（JSON）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_TRACE` | `1` | `0` 关闭追踪（页面不显示同意选项） |
| `TRACE_DIR` | `DATA_DIR/voice/traces` | compose 里固定为命名卷 `voice-traces:/traces` |
| `TRACE_DAYS` | `30` | 文字保留天数；启动时和之后每天清理一次 |
| `TRACE_AUDIO` | `1` | `0` 只存文字不录音 |
| `TRACE_AUDIO_DIR` | 同 `TRACE_DIR` | 录音目录（容器里须在挂载的卷内） |
| `TRACE_AUDIO_DAYS` | 同 `TRACE_DAYS` | 录音保留天数 |
| `TRACE_FEEDBACK_HOURS` | `6` | 通话开始后多少小时内能提交「这通有问题」 |
| `TRACE_MAX_MB` | `1024` | 录音和文字目录总量上限，超过停录音（文字照存），打 warning |
| `TRACE_MIN_FREE_MB` | `1024` | 磁盘剩余低于此值停录音 |
| `TRACE_ADMIN_TOKEN` | 空 | 读取接口口令；留空则接口 404。生成：`openssl rand -hex 24` |
| `GIT_SHA` | 空 | 构建参数，可选；不传时读镜像里的 `.gitmeta` |

## 连不上时：TURN 走 443 与连接状态

UDP 被封的网络（公司/校园网、不转发 UDP 的代理或 VPN）里，WebRTC 直连会超时。部署时启用 coturn 后，浏览器拿到
`turn:域名:443?transport=tcp` 和 `turns:域名:443?transport=tcp` 两条中继，经 Caddy 的 443 转进本机 coturn，不用另开端口
（分流规则见 `deploy/caddy/Caddyfile` 开头和 docs/DEPLOY.md）。

- 凭据：页面在点「开始通话」后 `POST /api/ice` 现取，coturn REST 临时凭据，有效期 `TURN_TTL`（默认 600 秒），不落盘、不进 `/api/config`。
- 页面状态：正在连接… → 已接通 · 通话中；20 秒没接通或 ICE 失败显示「连接失败」和建议（换网络、关代理/VPN、换浏览器），有通话编号时一并显示。
- 上报：失败或接通时 `POST /api/client-report`（阶段、原因、候选类型计数、选中路径、耗时、浏览器名；不含 IP、SDP）。
  一律只计数（`stats.json`）；拿到编号的网页通话，再写进同一编号的追踪，`python -m voice.trace_cli <编号>` 可见「前端上报失败 / 前端已接通」。
- 实测中继：`python -m voice.probe ... --relay tcp`（或 `tls`），只收集 relay 候选，退出码 6 表示没拿到中继。

| 变量 | 默认 | 说明 |
|---|---|---|
| `TURN_SECRET` | 空 | coturn `static-auth-secret`；空则不下发 TURN |
| `TURN_URLS` | 空 | 逗号分隔，例 `turn:live.deepsuck.si:443?transport=tcp,turns:live.deepsuck.si:443?transport=tcp` |
| `TURN_TTL` | 600 | 临时凭据有效期（秒，60–3600） |
| `TURN_PORT` | 3478 | coturn 在 127.0.0.1 上监听的端口（Caddy 转发目标） |
