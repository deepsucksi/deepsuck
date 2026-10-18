# voice/telephony：电话接入抽象层

> 状态：接口 + 第一个通用适配器（`ws-raw`）+ Pipecat 内置媒体流适配器（`pipecat-ws`）+ Asterisk chan_websocket 适配器（`asterisk-ws`，自建 SIP 软电话用）已实现并有单元测试；
> 阿里云适配器仅为设计稿。**默认关闭**，只接听、不外呼，没有任何发起呼叫的代码。
> 合规边界见 [docs/PHONE.md 第 6 节](../../docs/PHONE.md) 与 [docs/ETHICS.md](../../docs/ETHICS.md)。

```
运营商号码 / 云号码
     │ SIP（8 kHz PCMA/PCMU）
     ▼
SIP 侧（任选其一，独立进程，与 DeepSuck 只有一条 WebSocket）
  · FreeSWITCH + 音频流模块 / ESL 小程序
  · Asterisk（AudioSocket / chan_websocket）+ 小网关
  · 自写 UAS（sipgo、pjsua2）
  · Twilio / Telnyx / Plivo / Exotel 媒体流（海外）
     │ WebSocket：ws-raw 协议 或 Twilio 类协议
     ▼
voice/telephony   TelephonyAdapter（握手 → CallInfo；serializer 编解码 + 重采样 + DTMF/挂断/打断）
     │ Pipecat FastAPIWebsocketTransport
     ▼
voice/app.py 同一条管线：Paraformer → IntelProcessor → qwen3.7-flash → 输出守卫 → CosyVoice
```

## 接口

```python
@dataclass
class CallInfo:
    provider: str; call_id: str; stream_id: str = ""
    from_number: str = ""; to_number: str = ""
    encoding: str = "pcmu"      # pcmu / pcma / l16
    sample_rate: int = 8000
    extra: dict = {}

class TelephonyAdapter(ABC):
    name: ClassVar[str]
    async def accept(self, websocket) -> CallInfo            # 读握手
    def create_serializer(self, call) -> FrameSerializer     # 媒体编解码、DTMF、挂断、打断
    def create_transport(self, websocket, call, *, session_timeout=None)  # 默认 FastAPIWebsocketTransport
    async def hangup(self, call) -> None                     # 可选兜底

@register_adapter            # 注册；get_adapter(name) / list_adapters()
class MyAdapter(TelephonyAdapter): ...
```

帧映射（serializer 负责）：

| 电话侧 | Pipecat |
|---|---|
| 音频（8 kHz G.711 / L16） | `InputAudioRawFrame`（重采样到管线 16 kHz） |
| 机器人音频 | `OutputAudioRawFrame`（24 kHz）→ 重采样 + 编码回电话侧格式 |
| DTMF | `InputDTMFFrame` |
| 对方挂机 / WebSocket 断开 | transport `on_client_disconnected` → 取消任务 |
| 我方挂断（护栏/结束） | `EndFrame` / `CancelFrame` → `{"event":"hangup"}` 或服务商 REST 挂断 |
| 打断（barge-in） | `InterruptionFrame` → `{"event":"clear"}` 让对端清空播放缓冲 |

编解码和重采样直接用 Pipecat 自带的 `ulaw_to_pcm` / `alaw_to_pcm` / `pcm_to_ulaw` / `pcm_to_alaw` 与流式重采样器（soxr）。
注意：流式重采样器按约 100 ms 成块输出，单向会多出约 0.1 s 缓冲，是电话链路延迟的一部分。

## 已有适配器

### `ws-raw`（第一个落地的通用适配器）

一条 WebSocket = 一通电话。协议见 [`ws_raw.py`](ws_raw.py) 文件头：

```
桥接 → DeepSuck  文本 {"event":"start","call_id":"...","from":"...","to":"...","encoding":"pcma","sample_rate":8000}
                 二进制 音频（20 ms 一包）
                 文本 {"event":"dtmf","digit":"5"} / {"event":"stop"}
DeepSuck → 桥接  二进制 音频（同一编码/采样率）
                 文本 {"event":"clear"} / {"event":"hangup","reason":"end"}
```

选它做第一个的理由：国内云号码几乎都以 SIP 中继（8 kHz PCMA）交付，Twilio 类服务拿不到国内号码；
SIP 协议栈放在独立进程（FreeSWITCH/Asterisk/自写 UAS），DeepSuck 只需要这条极简 WebSocket，
不引入 GPL/AGPL 依赖，单元测试也不需要任何真实线路。

### `pipecat-ws`

复用 Pipecat 的 `parse_telephony_websocket` 与 `TwilioFrameSerializer` / `TelnyxFrameSerializer` /
`PlivoFrameSerializer` / `ExotelFrameSerializer`。适合海外部署或接入兼容 Twilio Media Streams 的网关（如 jambonz）。
主动挂断凭据只从环境变量读取（`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`、`TELNYX_API_KEY`、`PLIVO_AUTH_ID`/`PLIVO_AUTH_TOKEN`），
缺失时关闭 `auto_hang_up`。

### `asterisk-ws`（自建 SIP 软电话，docs/PHONE.md 第 10 节）

对接 Asterisk 22 的 chan_websocket（`Dial(WebSocket/deepsuck/c(slin16)f(json))`，Asterisk 作为 WebSocket 客户端
连 `WS /telephony/asterisk-ws`，用 HTTP Basic 带 token）。协议见 [`asterisk_ws.py`](asterisk_ws.py) 文件头：

```
Asterisk → DeepSuck  文本 {"event":"MEDIA_START","channel_id":"...","format":"slin16","optimal_frame_size":640,"channel_variables":{"__DS_FROM":"..."}}
                     二进制 原始音频（slin16 / slin / ulaw / alaw，无 RTP 头）
                     文本 {"event":"DTMF_END","digit":"5"}；挂机 = 关闭 WebSocket
DeepSuck → Asterisk  二进制 音频（只发 optimal_frame_size 的整数倍，Asterisk 负责 20 ms 定时）
                     文本 {"command":"FLUSH_MEDIA"}（打断）/ {"command":"HANGUP"}
```

编解码与重采样复用 `ws-raw` 的 `RawStreamSerializer`。SIP/RTP 全在独立的 Asterisk 容器里（GPLv2，官方 Alpine 包，
仓库里只有配置模板 `deploy/sip/`），DeepSuck 进程不链接任何 GPL 代码。部署、端口与安全措施见 docs/PHONE.md 第 10 节。

## 启用（本地联调）

```bash
export VOICE_TELEPHONY=1
export VOICE_TELEPHONY_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
# 可选：VOICE_TELEPHONY_ADAPTERS=ws-raw,pipecat-ws,asterisk-ws  VOICE_TELEPHONY_PERSONA=li  VOICE_TELEPHONY_SCENARIO=police
python -m voice.app
# 桥接连接 ws://127.0.0.1:7860/telephony/ws-raw，带 Authorization: Bearer <token>（或 HTTP Basic 密码 = token；
# ?token=... 也行，但会出现在访问日志里）
```

- 未设置 token 时路由不注册；token 用常量时间比较。
- 与浏览器入口共用并发名额（`VOICE_MAX_SESSIONS`）、每日预算、时长/轮数/静默护栏；主叫号码按“每 IP”规则限频。
- 开场 AI 告知语默认**不播**；`VOICE_AI_DISCLOSURE=1` 打开，`VOICE_AI_DISCLOSURE_TEXT` 自定义文案（与网页入口共用，见 `voice/disclosure.py`）。旧变量 `VOICE_TELEPHONY_DISCLOSURE` 已废弃。
- 留存：默认只保存脱敏文字记录，`KEEP_AUDIO=1` 才保存原始音频（最多 7 天）。全部电话相关环境变量见 [docs/PHONE.md 第 6 节](../../docs/PHONE.md#6-环境变量清单供-deploy-使用)。
- 日志里的号码只保留后 4 位。
- `deploy/` 已带这个入口的开关（`VOICE_TELEPHONY`，默认关闭）；公网开启前需要单独评审。

测试：`python -m pytest voice/tests/test_telephony.py voice/tests/test_asterisk_ws.py voice/tests/test_sip_deploy.py -q`（本地回环 WebSocket，直通管线，不连服务商、不拨打电话）。

---

## 设计稿：阿里云语音服务「智能语音交互呼入」适配器（未实现）

### 这个产品给的是什么

语音服务（VMS）把指定号码配置为“智能语音交互呼入”后，**阿里云自己做 ASR 和放音**，
通话中通过 HTTP 回调把**转写文本**推给我们，我们在响应里返回下一步动作。没有音频流可以接到 Pipecat。

| 回调 | `content_type` | 我们收到 | 我们返回（`data`） |
|---|---|---|---|
| 首次呼入 | `callin` | `call_id`，`content.caller/callee/orgcallee` | `action=answer` + 开场白（`action_code`/`action_code_param`），可设 `session_timeout`、`pause_time`（断句）、`mute_time`、`record_flag` |
| 后续 | `normal` | `content.words`（整句转写）、`is_playing`、时间偏移 | `action=play`（TTS 文本或预上传音频）/ `break` / `hangup` / `donothing` |
| 后续 | `mute` | 静默超时 | 追问或挂断 |
| 后续 | `dtmf` | `dtmf_digits` | 同上 |
| 后续 | `timebreak` | 骗子持续说话打断放音 | `break` 或 `continue` |

参考：[配置回调](https://help.aliyun.com/zh/vms/developer-reference/intelligent-voice-interaction-inbound/)、
[首次呼入回调](https://help.aliyun.com/zh/vms/developer-reference/inbound-correction-for-the-first-time)、
[后续呼入回调](https://help.aliyun.com/zh/vms/developer-reference/subsequent-incoming-callback)。字段以控制台最新文档为准。

### 因此它不是 TelephonyAdapter，而是“文本轮次适配器”

```python
class TextTurnAdapter(ABC):
    """平台负责 ASR/TTS/VAD，我们只做“听到一句 → 回一句”。"""
    name: ClassVar[str]
    async def on_call_start(self, call: CallInfo) -> TurnAction     # 开场白
    async def on_utterance(self, call_id: str, text: str, *, playing: bool) -> TurnAction
    async def on_silence(self, call_id: str) -> TurnAction
    async def on_dtmf(self, call_id: str, digits: str) -> TurnAction
    async def on_call_end(self, call_id: str) -> None

@dataclass
class TurnAction:
    kind: str                 # say / say_file / hangup / nothing
    text: str = ""            # 已过输出守卫的台词
    file_code: str = ""       # 预上传的填充音（“哎……你等一下啊”）
    interruptible: bool = True
```

- 内核复用：`deepsuck.engine.Session`（ingest → 话术/情报 → choose_intent）+ `voice.persona.system_prompt` + qwen3.7-flash +
  `guard_output/speakable`，与 `IntelProcessor` 同一套逻辑，只是没有 Pipecat 音频帧。可以先把 `IntelProcessor` 里
  “一句转写 → 策略 → 提示词”的部分抽成纯函数，两边共用。
- `AliyunVmsInboundAdapter(TextTurnAdapter)`：FastAPI `POST /telephony/aliyun-vms/callback`，按 `content_type` 分发，
  会话状态按 `call_id` 存内存（带 TTL），用 `dynamic_id` 带回轮次号做幂等。
- 时延：回调是同步 HTTP，必须在平台超时内返回整句，**不能流式**。做法：先返回一个预上传的填充音（`play` + 文件 code，
  `action_break=true`），同时后台调用大模型；下一次回调（或 `timebreak`/`mute`）时再返回正式回复。
  需要实测平台对回调超时、连续 `play` 的排队行为。
- 音色：`tts_style` 只能选平台音色，不能直接用 CosyVoice `longlaoyi_v3`；人设音色要么接受平台音色，
  要么把常用台词/填充音预合成成音频文件上传（需要审核），动态台词仍用平台 TTS。
- 安全：回调地址必须 HTTPS；校验来源（平台签名/IP 白名单，以控制台为准）；号码脱敏落日志；
  `session_timeout` 与 `VOICE_MAX_MINUTES` 对齐；预算按大模型 token 计，ASR/TTS/通话费走阿里云账单。

### 阿里云相关产品对照（2026-10 文档）

| 产品 | 接入粒度 | 能否把音频接到自建 Pipecat | 备注 |
|---|---|---|---|
| 语音服务 · 智能语音交互呼入 | 文本（HTTP 回调） | 否 | 上面的设计；需购买号码、企业资质 |
| 语音服务 · SIP Trunk（语音中继） | **媒体（SIP，8 kHz PCMA）** | **是**：SIP → FreeSWITCH/Asterisk → `ws-raw` | 邀约制，需商务打标、企业实名与资质、固定公网 IP |
| 云联络中心 · 数字员工三方大模型 | 文本（SSE：beginSession/dialogue/abortDialogue/endSession） | 否 | 支持流式文本、挂断、DTMF、可打断、CosyVoice 音色参数 |
| 智能媒体服务 IMS · AI 实时互动 | 文本（自研 LLM 走标准聊天接口规范）+ 平台 ASR/TTS | 否（可选第三方 SIP 呼入） | 可把 DeepSuck 包成标准聊天接口 LLM 端点，支持语义断句、VAD 抗扰 |
| 号码隐私保护（AXN/AXB） | 运营商侧转接 | 否 | 只有转接、录音、话单，无实时媒体 |
| 智能语音交互 ISI（NLS）实时识别 | 仅 ASR | — | 不是电话入口 |
