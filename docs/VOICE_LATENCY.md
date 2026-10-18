# 语音延迟：填充音、打断与首字延迟（2026-10-18）

本页记录 voice/ 这一轮延迟优化做了什么、怎么测的、测到了什么。所有数字都是实测，不是估算。

## 改动

| 项 | 做法 | 位置 |
|---|---|---|
| 指标 | `PipelineParams(enable_metrics=True, enable_usage_metrics=True)`；`LatencyObserver` 按用户回合拆解 ASR / 大模型首 token / 分句等待 / TTS 首包 / 端到端，通话结束写日志并推给看板 | `voice/latency.py`、`voice/app.py`、`voice/telephony/server.py` |
| ASR 断句 | Paraformer `max_sentence_silence` 从服务端默认（约 800ms）调到网页 450ms、电话 500ms。比"本地 VAD 判停后强制出最终结果"改动小：不改协议流程，出问题可用环境变量调回 | `voice/dashscope_ws.py`、`voice/services.py` |
| 流式合成 | `CosyVoiceStreamTTSService`：每通会话一条长连接（开局就建连）；每个大模型回合一个 DashScope 任务，回合一开始就发 run-task，大模型边吐字边按子句 continue-task；打断时若服务端仍在合成就断连取消并立即重连，已合成完只清本地队列。`ClauseTextAggregator` 在句末标点立即切、在逗号等处攒够 6 字就切，括号/引号未闭合不切（保证输出守卫拿到完整片段）。`DEEPSUCK_TTS_STREAM=0` 回退到旧的每句一连接实现 | `voice/services.py`、`voice/textagg.py` |
| 填充音 | 去掉"每句 60% 随机插播"，改为 `FillerProcessor`（放在大模型之后）：播放时刻 = max(真实停说 + 650ms, 回合判定结束)，到时仍无大模型首 token 才播；首 token、TTS 出声、机器人开口或对方接着说都会取消；每回合最多一次 | `voice/processors.py` |
| 打断 | `ChineseMinCharsUserTurnStartStrategy`：Pipecat 的 `MinWordsUserTurnStartStrategy` 用空格分词，对中文无效，这里改数"有效字"（去掉标点和"嗯/对/好/是的"等应答词，"不是/不对"算反驳）。机器人说话时有效字达到门槛才打断，机器人没说话时任何文字都开启回合。VAD 默认 start 0.3s、confidence 0.75 | `voice/interrupt.py` |
| rule 模式打断 | 管线加 `VADProcessor`（STT 前）和 `UserTurnProcessor`（STT 后），开口达到门槛就广播打断 | `voice/app.py` |
| 参数 | 网页 / 电话两套，电话线路 VAD 更保守、打断门槛 3 字、断句静音 500ms；`build_pipeline(profile="phone")` 由电话接入层使用 | `voice/tuning.py` |

### 可调参数

网页用 `DEEPSUCK_LAT_<字段>`，电话用 `DEEPSUCK_PHONE_LAT_<字段>`：

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

## 测量方法

- 探针：`python -m voice.probe`（aiortc 充当浏览器），同一段合成骗子音频 `scammer16k.wav`（6 句，每句 3.5–5 秒，句间 9 秒以上静音），人设 wang、场景 refund。
- 客户端端到端：骗子音频里每句话的能量结束点 → 探针收到第一帧有声机器人音频（int16 RMS > 200）。这是用户真正感受到的等待，包含 WebRTC 传输。
- 分阶段：Pipecat 自带的 TTFB 指标（日志 `... TTFB: x.xxxs`），优化前后同一种口径。STT 为 VAD 判停到最终转写；LLM 为请求到首 token（剔除被打断后不足 300ms 的残留指标）；TTS 为送出文本到首包音频（剔除开场白）。
- 环境：测量机到 DashScope 的 TLS 握手约 0.58s，离 DashScope 更近的服务器上绝对值会更低；前后两次在同一台机器上测，对比有效。
- 优化前：1 次 6 句。优化后：开启填充音 1 次 6 句（产品默认配置），关闭填充音（`DEEPSUCK_LAT_FILLER_DELAY_MS=0`）1 次前 3 句，用来单独测回复本身的延迟。每次都是真实计费调用，样本量小，P90 只作参考。

## 结果

客户端端到端（毫秒）：

| | 逐句 | P50 | P90 |
|---|---|---|---|
| 优化前，首个可听音频（这次没有听到填充音，即回复本身） | 6562, 6002, 5042, 5482, 5682, 6002 | 5842 | 6282 |
| 优化后，首个可听音频（6 句都先听到填充音） | 1544, 1423, 1723, 1683, 1623, 3882 | 1653 | 2803 |
| 优化后，回复本身（关闭填充音，前 3 句） | 6243, 4162, 3462 | 4162 | 5827 |
| 同 3 句优化前，回复本身 | 6562, 6002, 5042 | 6002 | 6450 |

分阶段（Pipecat TTFB，毫秒，n 为样本数）：

| 阶段 | 优化前 P50 / P90（n=6） | 优化后 P50 / P90（n=9） |
|---|---|---|
| ASR：VAD 判停 → 最终转写 | 1382 / 1762 | 1060 / 1285 |
| 大模型首 token | 831 / 1287 | 1065 / 1790 |
| TTS：文本 → 首包音频 | 2781 / 3004 | 1385 / 1460 |

解读：

- 收益主要来自 TTS：长连接省掉每句约 0.9s 的建连，回合开始预开任务，按子句流式送字，首包从 P50 2.8s 降到 1.4s。剩下约 1.2s 是 CosyVoice 服务端从收到文本到吐出首包的时间（单独直连测量也是 1.2–1.5s）。
- ASR 断句静音 800→450ms 让最终转写提前约 0.3s。
- 大模型首 token 两次测量在 0.6–2.2s 之间波动，没有改动这部分，差异属于服务端波动。
- 填充音让对方停说后约 1.4–1.7s 就能听到机器人出声（第 6 句 3.9s 是因为回合判定等了较久）。

已知副作用：断句静音调短后，合成音频里逗号处约半秒的停顿有时会被 Pipecat 的回合判定当成说完（第 1 句就是这样）：大模型先被调用一次，对方接着说时被打断再重新调用，这一句的回复反而更慢，还多一次大模型调用。若线上发现这种情况多，可把 `DEEPSUCK_LAT_ASR_MAX_SILENCE_MS` 调到 500–600 再测。

## TTS 首包拆解（2026-10-18，第二轮）

线上（live.deepsuck.si，69b3ad5）外部 probe 3 回合：e2e_reply 2469 / 2627 / 2484 ms；ASR 约 650 ms，大模型首 token 430–680 ms，TTS 首包 1050–1340 ms，是最大的一段。按三部分拆：

| 部分 | 数据 | 结论 |
|---|---|---|
| 等分句（大模型首 token → 首个分句送进 TTS，`agg`） | 本地 4 次 probe：9–232 ms，多数在 70 ms 以内 | 已经很小；首句在句末标点立即切、逗号处 6 字切，再缩短收益有限 |
| CosyVoice 服务端：continue-task → 首个音频包 | 直连脚本 28 次（任务已 task-started，等价于管线里的预开任务）：P50 1182 ms，最小 410，最大 1657 | 呈两档：8 次在 410–461 ms，其余 897–1657 ms，随机出现 |
| 重采样 / 传输 | CosyVoice 直接输出 24 kHz，与 WebRTC 输出采样率一致，TTS 路径上没有重采样；直连时 run-task → task-started 约 190 ms（含一次网络往返） | 不是瓶颈 |

直连对比（每组 2–4 次，单位 ms，均为 continue-task 到首包）：

| 变量 | 结果 |
|---|---|
| 基线 cosyvoice-v3-flash / longlaoyi_v3 / 24 kHz，逗号结尾不发 finish | 1475, 1657, 1489 |
| 同上，紧接着发 finish-task | 1152, 1057, 1497 |
| 句末问号结尾 | 1513, 1212, 1473 |
| 去掉 `X-DashScope-DataInspection` 头 | 1423, 427, 1531 |
| 16 kHz | 1253, 410 |
| 音色 longanyang | 897, 440 |
| cosyvoice-v2 / longxiaochun_v2 | 446, 992 |
| cosyvoice-v3-plus / longlaoyi_v3 | 任务失败（该音色不支持 v3-plus） |
| task-started 后先等 1.5 s / 3 s 再发文本（排除引擎冷启动） | 1501, 1219, 447, 1518 / 461, 1149 |
| 同一条连接连续 4 个任务（排除连接粘性） | 1125, 1493, 428, 440 |

结论：首包延迟主要由 CosyVoice 服务端决定，快慢两档与模型、音色、采样率、是否 finish、是否预热、连接复用都无明显关系；客户端已有的长连接、预开任务、按子句流式送字都已在位。

尝试过但**未合入**的方案：

- **首包两路赛跑**（每回合两条连接各开一个任务，谁先出声用谁）。按上面 28 个样本两两取快模拟，P50 可从 1182 降到约 897 ms，P90 基本不变（1518 → 1473）。实现后本地 probe 实测：第一版在真实服务上出现整回合无音频（“哎？”这类极短首句会让服务端等后续文本，而赛跑期间后续文本被暂存，两边互相卡死），修正后再测 3 个回合，备用连接一次也没赢（首包 1301 / 463 / 1136 ms，与不赛跑时的 2535 / 1927 / 1285 ms 差异属于随机波动）。收益没有实测证据，又增加一条连接和并发状态，按“收益不显著不合入”的原则没有进 main。
- 首句更短切分、改用其他模型/音色/采样率：直连数据显示首包与文本长度、模型、音色、采样率无明显关系，不改。

后续可做：在线上（香港服务器到北京地域）累积更多 `tts_ttfb` 样本（服务端每回合都会记 `latency turn N` 日志），若快慢两档比例与本地一致，再评估赛跑方案；或关注 DashScope 是否提供首包更稳定的模型/地域。

## 复现

```bash
python -m voice.app --port 7863 &
python -m voice.probe --url http://127.0.0.1:7863 --wav scammer16k.wav --seconds 96 --json-out after.json
# 只测回复本身：服务端加 DEEPSUCK_LAT_FILLER_DELAY_MS=0
# 生成同款骗子音频（计费，约 150 字）：python -m voice.probe --make-wav scammer16k.wav
```
