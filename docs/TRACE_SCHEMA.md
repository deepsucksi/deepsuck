# 通话追踪 schema（v3）

当前版本：`schema_version = 3`。字段名按 10-19 与情报分析师、负责人定稿的名字（`docs/` 以外的原始记录见 #94）。代码在 `voice/trace.py`（`SCHEMA_VERSION`），测试在 `voice/tests/test_trace_schema.py`，
测试会检查本文档列全了下面的字段。语音工程（#5）、磁盘监控（#18）、成本监控（#20）共用这一份。

- 每通电话一个文件 `<TRACE_DIR>/<call_id>.jsonl`，每行一个 JSON 对象，`type` 区分行的种类。
- 每一行都带 `schema_version` 和 `call_id`。v1（6ccede1 的旧格式）没有这两个字段，读的时候按 v1 处理。
- 时间一律 ISO 8601、毫秒精度、带 `+08:00`（UTC+8）。按天汇总以通话开始时间（start 行的 `t`）的日期为准。
- 新增字段只加不改；改字段含义或删字段时 `schema_version` 加 1，并在本文档末尾记一笔。

## 通话编号

`call_id`：8 位 base32（`A-Z2-7`，40 bit 随机），`/api/offer` 生成，接通后页面显示「通话编号 XXXXXXXX」并可复制，
用户报问题时引用。同一通电话重协商不换编号。电话线路（SIP）由服务端生成，不对外显示。

## 没同意的通话（#96）

网页通话没勾选同意时，仍然写同一份 trace（不另建 voice-usage.jsonl），但只存编号、时间、人设、渠道和用量 / 延迟字段，
不存任何文字。start 行 `text_stored` 为 `false`。写盘前按 `voice/trace.py` 的 `TEXT_FIELDS` 去掉：

| 行 | 去掉的字段 |
|---|---|
| `turn` | `asr`、`reply`、`filler`、`intent`、`intents`、`intel`、`tactics`、`prompt` |
| `bot` | `text`（只留 `kind`） |
| `feedback` | `note`、`turn`（只留编号和 `flagged`） |
| `client_error` / `client_connected` | `reason`；`detail` 里的字符串只留 `ice`、`conn`、`gather`、`path` 这几个枚举 |

用量字段（token、ASR 秒数、TTS 字数、模型、音色、延迟、是否打断、`usage_total`、`cost_cny`、v3 的 call 行）照留，`--usage` 照常汇总。
这些 trace 和同意的通话一样按 `TRACE_DAYS` 保留、按修改时间清理，`--usage --since` 能跨天查到，所以不单独做 `voice-usage.jsonl`。
不录音。电话线路（`sip-text-only`）行为不变。上线前写下的旧记录用
`python -m voice.trace_cli --scrub-no-consent`（dry-run）/ `--apply` 清理：只命中没同意且没有录音的通话，已同意的一律跳过。

## 每轮（`type = "turn"`）

一个用户回合（对方说完一段 → 人设回复）一行。为了让跨回合补打码（卡号分几句报）生效，落盘会晚 3 个回合，挂断时全部写完。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | 整数 | 3（v2 的记录为 2） |
| `call_id` | 字符串 | 通话编号 |
| `turn` | 整数 | 轮次，从 1 开始（旧字段 `n` 同值，保留兼容） |
| `ts` | 字符串 | 本轮开始时间（对方这一段的转写到达时刻；旧字段 `t` 同值） |
| `persona_id` | 字符串 | 人设 id（`wang` / `chen` / `lin` / `zheng`，见 `site/assets/core/personas.json`） |
| `model` | 字符串 | 大模型名（环境变量 `DEEPSUCK_LLM_MODEL`）；规则模式为 `rule` |
| `llm_in_tokens` | 整数 | 大模型输入 token 数，取接口返回的 usage（`prompt_tokens`）累加 |
| `llm_out_tokens` | 整数 | 大模型输出 token 数，取接口返回的 usage（`completion_tokens`）累加 |
| `llm_first_token_ms` | 整数或 null | 大模型首字延迟：开始请求 → 第一个文字（`latency.llm_ttft`） |
| `llm_full_ms` | 整数或 null | 大模型整句延迟：开始请求 → 回复结束 |
| `first_audible_ms` | 整数或 null | 对方说完 → 听到第一个声音（含口头语） |
| `e2e_reply_ms` | 整数或 null | 对方说完 → 正式回复首包 |
| `asr_audio_sec` | 小数 | 本轮送去识别的音频秒数（按发送的音频时长计，与计费口径一致） |
| `tts_chars` | 整数 | 本轮合成的字数（含口头语、填充音的合成） |
| `tts_billed_chars` | 整数 | v3：本轮 TTS 计费字符数（汉字算 2，其他算 1，见「调用行」） |
| `tts_voice` | 字符串 | 本通人设使用的音色 id |
| `interrupted` | 布尔 | 人设在说话时对方开口（打断）为 `true` |
| `asr` | 字符串 | 对方这一段的识别文字（已脱敏） |
| `reply` | 字符串 | 人设回复（已脱敏） |
| `intent` / `intents` | 字符串 / 数组 | 本轮策略意图 |
| `intel` | 数组 | 本轮新抽到的情报，只有 `type` / `label` / `masked`（打码值） |
| `tactics` | 数组 | 识别出的话术 id |
| `latency` | 对象 | 延迟拆解原样（字段见 `voice/latency.py`：`asr`、`turn_ms`、`llm_ttft`、`agg`、`tts_ttfb`、`e2e_reply`、`first_audible`、`filler`） |
| `prompt` / `promptVersion` / `code` | 字符串 | 本轮系统提示词短哈希、提示词模板版本、代码版本 |
| `persona` / `scenario` / `consent` | | 旧字段，保留兼容 |

用量口径：每轮的 `llm_*_tokens`、`asr_audio_sec`、`tts_chars` 是「上一轮收尾到本轮收尾」之间计量的增量
（第 1 轮含开场白，最后一轮含挂断前的告别语）。各轮相加 = 每通合计；以 end 行的 `usage_total` 为准。
规则模式、没有计量的通话这几项为 0。

## 每通汇总（`type = "end"`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | 整数 | 3（v2 的记录为 2） |
| `call_id` | 字符串 | 通话编号 |
| `started_at` | 字符串 | 开始时间（与 start 行一致） |
| `ended_at` | 字符串 | 结束时间 |
| `duration_sec` | 小数 | 时长（秒） |
| `exit_reason` | 字符串 | 退出原因：`client_hangup`（网页挂断）、`caller_hangup`（电话挂断）、`time`（时长上限）、`turns`（轮数上限）、`idle`（静默）、`budget`（额度）、`connect_timeout`、`error`、`pipeline_end`（旧字段 `reason` 同值） |
| `consent` | 布尔或字符串 | 是否同意录音：网页 `true` / `false`；电话线路为 `"sip-text-only"` |
| `audio` | 布尔 | 这通是否录了音 |
| `turns` | 整数 | 轮数 |
| `interrupted_turns` | 整数 | 被打断的轮数 |
| `usage_total` | 对象 | 各项用量合计：`llm_in_tokens`、`llm_out_tokens`、`asr_audio_sec`、`tts_chars`；v3 加 `tts_billed_chars` 和定稿名 `prompt_tokens`、`completion_tokens`、`asr_seconds`（与前面同值） |
| `cost_cny` | 小数 | 按 `VOICE_PRICE_*` 单价估算的本通花费（元），没有计量时不写 |
| `persona_id` / `model` / `tts_voice` | 字符串 | 同每轮，便于只读 end 行做汇总 |
| `persona` | 字符串 | v3：同 `persona_id` |
| `channel` | 字符串 | v3：`web`（网页）/ `phone`（电话线路，即 SIP；沿用 start 行已有的取值，不改含义） |
| `asr_model` / `tts_model` | 字符串 | v3：语音识别模型、实际合成用的模型（设计音色走它自己的模型，例如 `cosyvoice-v3.5-flash`） |
| `stats` / `latency` / `usage` | 对象 | 会话统计、延迟分位、计量原样（旧字段） |

## 调用行（`type = "call"`，v3）

每轮按调用用途各写一行，只有用量、模型和音色，**没有任何文字**（没同意的通话也一样写）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` / `call_id` / `t` | | 同上 |
| `turn` | 整数 | 记在第几轮（与 turn 行同一个切点）；开场白算第 1 轮 |
| `kind` | 字符串 | `reply`（正式回复：大模型 + 合成）、`filler`（口头语 / 填充音合成）、`opening`（开场白）、`disclosure`（开头的说明）、`farewell`（挂断前的告别语）、`asr`（对方语音识别）；`intent`、`guard` 预留（现在意图判断和输出守卫都是规则，不调接口，不会出现） |
| `llm_model` | 字符串或 null | 有大模型 token 时为模型名，否则 null |
| `prompt_tokens` / `completion_tokens` | 整数 | 大模型接口返回的 usage，不估算 |
| `asr_seconds` | 小数 | 送去识别的音频秒数 |
| `tts_chars` | 整数 | 送去合成的字数（`len`） |
| `tts_billed_chars` | 整数 | CosyVoice 计费字符数：汉字（含繁体、日文汉字、韩文汉字）算 2 个，标点、字母、数字、空格、假名、谚文算 1 个；用实际送去合成的原文在脱敏前算好（`voice/guard.py` 的 `tts_billed_chars`，注释里有官方文档出处） |
| `tts_voice` | 字符串或 null | 有合成时为音色 id，否则 null |
| `tail` | 布尔 | 只在最后一轮之后的用量（告别语、挂断前的尾音识别）上出现，`true`，`turn` 记最后一轮的编号 |

- 同一轮同一 `kind` 只有一行（这一轮该用途的所有调用合计）；某个 `kind` 这一轮没有用量就不写。
- 一通里所有 call 行相加 = end 行的 `usage_total`（`prompt_tokens`、`completion_tokens`、`asr_seconds`、`tts_chars`、`tts_billed_chars`）；
  同一 `turn` 不带 `tail` 的 call 行相加 = 这一轮 turn 行的用量。
- 规则模式、没有计量（没有预算票据）的通话不写 call 行。

## v2 → v3 字段对照

只加不改：v2 的字段全部保留、含义不变，v3 新增的是下表右列。

| 位置 | v2 字段 | v3 定稿字段 | 说明 |
|---|---|---|---|
| end 行 | `persona_id` | `persona` | 同值；start 行本来就有 `persona` |
| end 行 | （仅 start 行有 `channel`） | `channel` | `web` / `phone`（SIP） |
| end 行 | （仅 start 行有） | `asr_model`、`tts_model` | `tts_model` 现在记实际合成用的模型 |
| end 行 | `tts_voice` | `tts_voice` | 不变 |
| end.`usage_total` | `llm_in_tokens` | `prompt_tokens` | 同值 |
| end.`usage_total` | `llm_out_tokens` | `completion_tokens` | 同值 |
| end.`usage_total` | `asr_audio_sec` | `asr_seconds` | 同值 |
| end.`usage_total` | `tts_chars` | `tts_chars` | 不变 |
| end.`usage_total` / turn 行 | — | `tts_billed_chars` | 新增 |
| turn 行 | `turn` / `model` / `tts_voice` | — | 不变（call 行里对应 `turn`、`llm_model`、`tts_voice`） |
| — | — | call 行：`turn`、`kind`、`llm_model`、`prompt_tokens`、`completion_tokens`、`asr_seconds`、`tts_chars`、`tts_billed_chars`、`tts_voice` | 新增行类型 |
| end.`usage`（计量原样） | `asr_sec`、`tts_chars`、`llm_in`、`llm_out` | + `tts_billed_chars` | 新增一项 |

读 v2 / v3 的程序：优先读 v3 名字，没有再退回 v2 名字（`voice/cost.py` 就是这么读的）；`tts_billed_chars` 缺失时只能按 `tts_chars × 2` 估算。

## 其他行

| `type` | 说明 |
|---|---|
| `start` | 第一行：`text_stored`（是否存文字）、`started_at`、`channel`（`web` / `phone`）、`consent`、`persona_id`、`scenario`、`model`、`asr_model`、`tts_model`、`tts_voice`、`code`、`promptVersion`；网页通话另有 `fk`（反馈口令的哈希，不是口令本身）；电话另有打码的 `caller` |
| `bot` | 开场白 / 说明 / 告别语（`kind` = `opening` / `disclosure` / `hangup`，文字已脱敏） |
| `interrupt` | 还没有回合时被打断（例如开场白），`during` = `opening` / `filler` |
| `feedback` | 「这通有问题」：`flagged`（恒为 `true`）、`note`（脱敏、最多 200 字）、`turn`（可选，用户填的第几轮）；没同意的通话只有 `flagged` |
| `audio` | 录音收尾：每轨 `file`、`bytes`、`seconds` |
| `audio_stopped` | 录音因磁盘上限或剩余不足停止（文字照存） |
| `client_connected` / `client_error` | 页面上报的接通 / 失败（#3） |
| `latency` | 没有对应回合的延迟记录 |

## 脱敏

文字（`asr`、`reply`、`bot.text`、`filler`、`feedback.note`、页面上报的原因）落盘前一律经过：

1. 共享核心 `deepsuck.redact_text(text, extract_sensitive(text))`，规则在 `site/assets/core/extractors.json`，
   与网页版 `redact.js` 一致：银行卡（PCI：保留前 6 后 4）、身份证（保留前 6 后 4）、手机号、QQ、微信、支付宝、
   邮箱、收款人姓名、网址、钱包地址、验证码类短数字等。
2. 自报 / 转述姓名补充规则（`voice/trace.py`）：「我叫张伟」「我是李明警官」「他叫王强」「姓名是王小红」，
   姓氏表、称呼表复用 `extractors.json` 的 `nameRules`，打码用共享的 `mask_name`（`张*`）。「王经理」「李总」这类称呼不打码。
3. 跨分段验证码（#92）：同一说话方（对方：`asr`；人设：`reply`、`filler`）的相邻分段连起来再判断一次（共享 `deepsuck.redact.redact_otp_segments`，前后各 2 段），「验证码是 38」「27 15」两段都打码。历史文件用 `docker exec deepsuck-voice-1 python -m voice.redact_backfill --dry-run`（只统计）/ 不带 `--dry-run`（改写）重跑：只改 start 行 `consent` 为 `true` 或 `"sip-text-only"`（电话线路，#254）的通话，只把命中的数字换成 `*`，保留修改时间，输出只有计数。
   线上由 `deepsuck-redact.timer` 每天 20:30（+08:00）自动跑一次兜底（`deploy/redact-backfill.sh`，不留备份，`journalctl -t deepsuck-redact`：改动 0 条 INFO，>0 条 WARN，失败 ERROR；见 docs/DEPLOY.md 第 8 节）。
4. 两边说话人、卡号片段、人设侧兜底（#120）：落盘时两边的分段按时间连起来再判断一次（共享 `deepsuck.redact.redact_dialog_segments`）：骗子问验证码、人设下一句报数字也打码；卡号语境下的「6222开头」「尾号0123」全部换成 `*`；人设侧（`reply`、`filler`、`bot` 行 `text`）连续 3 位及以上逐位数字一律换成 `*`（含「138开头」「零零幺三」）。对方说的电话号码等情报仍按实体规则公开。开场白 / 告别语 `bot` 行即时写入，只过人设兜底，跨说话方的补打码由每日回填完成。

**残留风险（跨分段验证码）**：脱敏是逐段实时做的。验证码的前半段（如「验证码是 38」）单独看不够长、判断不了时，这一段已经按原样实时发给大模型（作为对方的话）和看板；等后面的分段到了，`Session.ingest` 只能回头修正会话里的文字，trace / 文字记录落盘前再按相邻分段补打码，**已经发出去的部分收不回，只能事后修正存储**。trace 每轮晚 3 段落盘，看得到后面 2 段；关键词在更后面才出现、或规则以后再收紧时，已落盘的记录靠上面的每日重跑事后修正。打码规则本身的局限（关键词附近不带单位的普通数字会被多打、分段报的手机号不按验证码处理）见 docs/INTEL.md「脱敏接口」。

卡号等原值只在进程内存里，不进文件。

## 存储与保留

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_TRACE` | `1` | `0` 全部关闭（什么都不存，页面不显示同意选项） |
| `TRACE_DIR` | `DATA_DIR/voice/traces` | 文字（`<call_id>.jsonl`）和无内容计数（`stats.json`）。容器里是命名卷 `voice-traces:/traces` |
| `TRACE_DAYS` | `30` | 文字保留天数 |
| `TRACE_AUDIO` | `1` | `0` 不录音 |
| `TRACE_AUDIO_DIR` | 同 `TRACE_DIR` | 录音（`<call_id>-scammer.ogg`、`<call_id>-persona.ogg`，16k 单声道 opus，约 2 KB/秒/轨）。容器里必须在挂载的卷内（如 `/traces/audio`） |
| `TRACE_AUDIO_DAYS` | 同 `TRACE_DAYS` | 录音保留天数 |
| `TRACE_MAX_MB` | `1024` | 录音和文字目录总量上限，超过停录音（文字照存） |
| `TRACE_MIN_FREE_MB` | `1024` | 磁盘剩余低于此值停录音 |
| `TRACE_FEEDBACK_HOURS` | `6` | 通话开始后多少小时内还能提交「这通有问题」 |
| `TRACE_ADMIN_TOKEN` | 空 | 读取接口口令；留空则接口 404 |

- 勾选同意：存录音和脱敏文字；没同意：只存用量、不存文字、不录音（#96）；电话线路只存文字。
- 清理：服务启动时一次、之后每 24 小时一次，按文件修改时间删除超过保留天数的 `*.jsonl` / `*.ogg`；`stats.json` 只有计数，不删。
- 文件权限 0600。#18 做按天清理或监控时：文件名是 `<call_id>` 不含日期，按修改时间（或 start 行 `t`）判断天数；
  录音目录大小即 `TRACE_AUDIO_DIR` 下 `*.ogg` 的总和。

## 「这通有问题」

- 页面：通话页「通话编号」旁的「这通有问题」，可填一句说明和第几轮，提交后原位显示结果。
- 接口：`POST /api/feedback/<call_id>`，JSON `{"key", "note", "turn"}`。`key` 是 `/api/offer` 只发给这个页面的一次性口令
  （`feedback_key`，服务端只存哈希）。
- 防滥用：同一 IP 每分钟 6 次（429）；口令不对 403；没有这通或是电话线路 404；通话开始超过 `TRACE_FEEDBACK_HOURS` 小时 410；
  每通最多 5 条（429）；校验 `VOICE_ALLOWED_ORIGINS`。

## 读取

只在服务器本机（Caddy 对公网的 `/api/traces*` 一律 404，接口还要 `Authorization: Bearer $TRACE_ADMIN_TOKEN`）：

    docker exec deepsuck-voice-1 python -m voice.trace_cli --list            # 最近的通话
    docker exec deepsuck-voice-1 python -m voice.trace_cli <call_id> --audio # 一通的逐轮记录和录音路径
    docker exec deepsuck-voice-1 python -m voice.trace_cli <call_id> --json  # 原始 JSONL
    docker exec deepsuck-voice-1 python -m voice.trace_cli --flagged [--since 2026-10-19] [--json]
    docker exec deepsuck-voice-1 python -m voice.trace_cli --usage [--since 2026-10-01] [--until 2026-10-19] [--days 7]

- `--flagged`：只列被点了「这通有问题」的通话，附每条说明。
- `--usage`：按天汇总用量，输出 JSON（同 `GET /api/traces-usage?since=&until=`），#20 直接用：

```json
{"schema_version": 3, "generated_at": "2026-10-19T12:00:00.000+08:00", "tz": "+08:00",
 "days": [{"date": "2026-10-19", "calls": 12, "consent_calls": 9, "audio_calls": 9, "sip_calls": 0,
           "flagged_calls": 1, "turns": 85, "interrupted_turns": 7, "duration_sec": 1830.5, "cost_cny": 0.42,
           "llm_in_tokens": 152000, "llm_out_tokens": 4100, "asr_audio_sec": 1790.2, "tts_chars": 5200, "tts_billed_chars": 9800,
           "by_model": {"qwen-flash": {"calls": 12, "llm_in_tokens": 152000, "llm_out_tokens": 4100}},
           "by_persona": {"wang": 5, "lin": 7}, "exit_reasons": {"client_hangup": 10, "idle": 2}}]}
```

没有 end 行的通话（进行中或异常退出）用各轮相加，`exit_reasons` 记为 `unfinished`。
v3 起每天另有 `by_kind`：call 行按 `kind` 汇总（`rows`、`prompt_tokens`、`completion_tokens`、`asr_seconds`、`tts_chars`、`tts_billed_chars`），v2 记录没有 call 行，不计入。

## 版本记录

- v3（#94）：只加字段。新增 `type="call"` 调用行；end 行加 `persona`、`channel`、`asr_model`、`tts_model`；
  `usage_total` 加 `tts_billed_chars` 和定稿名 `prompt_tokens`、`completion_tokens`、`asr_seconds`；turn 行加 `tts_billed_chars`。对照见上表。

- v2 补丁（#96）：没同意的网页通话不存文字（见上），start 行加 `text_stored`，清理过的旧记录 start 行有 `scrubbed_at`。字段名不变，`schema_version` 仍为 2。
- v2（#5）：每行加 `schema_version`、`call_id`；每轮加 token、ASR 秒数、TTS 字数和音色、首字 / 整句延迟、是否打断；
  end 行加起止时间、时长、`exit_reason`、`usage_total`、`cost_cny`；反馈加口令、`flagged`。
- v1（6ccede1）：初版，只在同意时存文字和录音。
