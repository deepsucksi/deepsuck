# DeepSuck 电话接入方案

> 现状（2026-10-18）：`voice/telephony/` 已有电话接入适配层（`ws-raw`、`pipecat-ws`），**默认关闭，只接听、不外呼**；项目没有购买任何号码；`deploy/` 已带电话入口开关（默认关闭）。本文回答“个人能用什么线路把骗子电话的**原始音频**接进来”，并整理所有电话相关环境变量。
>
> 价格只写从官方页面查到的数字，并注明链接与查询日期（全部为 **2026-10-18** 查询）；官方页查不到的写“未公开/需咨询”。标注“需实测”的是推断或社区经验，不是官方承诺。

## 目录

1. 结论速览
2. 云接入方案对比（国内 / 海外）
3. 用户自己手机的呼叫转移
4. 推荐方案与月成本估算
5. 自备硬件路线（EC20/EG25 模组 + 副卡）
6. 环境变量清单（供 `deploy/` 使用）
7. 录音与告知语策略
8. 合规边界
9. 待验证

---

## 1. 结论速览

- **国内云服务商能拿到原始音频的只有 SIP 中继类产品，而且全部要求企业资质。** 阿里云语音 SIP 为邀约制并需企业资质；腾讯云联络中心、华为云隐私保护通话明确只面向企业认证用户。容联云通讯有“个人开发者”认证，但呼入/号码业务是否对个人开放官方未写明（需咨询）。没有查到面向个人、能把媒体流交给自建服务的国内云号码。
- **海外服务商（Twilio、Telnyx、Plivo、Vonage）个人可注册，都提供 WebSocket 媒体流**，与现有 `pipecat-ws` 适配器基本即插即用；但**拿不到中国大陆号码**（Twilio 官方 China 页面：呼入呼出均不支持；Plivo 中国：呼入不支持），而且**大陆三大运营商不允许把手机呼叫转移到境外（含港澳台）号码**。所以海外线路只适合联调和测试，接不到转给你的大陆骗子电话。
- **个人当下唯一可行、能拿到原始音频的路线仍是“手机呼叫转移 → 本人实名副卡 → EC20/EG25 模组”**（第 5 节），呼转费按运营商官方价约 0.1 元/分钟（同地）。
- 如果项目以后有企业主体：**阿里云语音 SIP（号码 35 元/月，呼入 0.11 元/分钟）→ FreeSWITCH 等 SIP 网关 → `ws-raw` → 现有管线**，是云原生主线（第 4 节）。

---

## 2. 云接入方案对比

对接工作量以现有适配器为基准：`pipecat-ws` 已内置 Twilio / Telnyx / Plivo / Exotel 的媒体流协议；`ws-raw` 需要一个独立的 SIP 网关进程（FreeSWITCH、Asterisk 或自写 UAS）把 RTP 转成 WebSocket。

### 2.1 国内

| 服务商 / 产品 | 接入方式 | 个人能否开通、门槛 | 号码月费 | 呼入每分钟 | 对接工作量 | 合规风险 |
|---|---|---|---|---|---|---|
| 阿里云 语音服务 · 语音 SIP（语音中继号） | SIP 中继（媒体级，G.711） | **否**。邀约制，需商务打标、补签协议；需提交企业资质（营业执照、法人及管理员材料、入网承诺书、号码申请公函）[A2][A3] | 35 元/月（普通号码）[A1] | 0.11 元（≤5 万分钟/月，不满 1 分钟按 1 分钟）[A1] | 中：需自建 SIP 网关（固定公网 IP + IP 白名单）→ `ws-raw` | 低（企业实名、正规中继）；用途须与申报一致 |
| 阿里云 语音服务 · 400 号码（语音 SIP） | SIP，仅呼入 | 否（同上） | 套餐保底 120 元至 20 万元/月 [A1] | 0.11 元 [A1] | 中（同上） | 同上 |
| 阿里云 智能语音交互呼入 / 云联络中心数字员工 / IMS AI 实时互动 | 文本回调或平台 ASR/TTS，**拿不到原始音频** | 需企业资质（设计稿见 `voice/telephony/README.md`） | 未公开/需咨询 | 未公开/需咨询 | 大：需另写文本轮次适配器，失去自有 VAD/填充音/音色 | 低 |
| 腾讯云 云联络中心 | 平台呼叫中心；号码与 SIP 话机接入，媒体流是否开放给自建服务**未公开/需咨询** | **否**。需企业实名认证，个人认证不能申请号码；需提交企业资质、话术、用途证明 [T1][T2] | 未公开/需咨询（计费概述未列号码月租）[T3] | 未公开/需咨询 [T3] | 未知（需确认能否导出媒体流） | 低 |
| 华为云 隐私保护通话（PrivateNumber） | 运营商侧号码转接（AXB/AX），**拿不到原始音频** | **否**。仅面向企业实名认证用户，个人和个体工商户不能开通 [H1] | 15 元/月/个 [H2] | 0.06 元 [H2] | 不适用 | 低；且仅限订单类隐私通话场景 |
| 容联云通讯（云通讯平台） | 语音通知、IVR、呼入（DID/400）[R2]；是否提供原始媒体流**未公开/需咨询** | **部分**。有“个人开发者”认证（手持身份证），但“部分业务只面向企业开发者”[R1]，呼入是否对个人开放需咨询 | 未公开/需咨询 | 未公开/需咨询（官方写预付费、按需扣费）[R3] | 未知 | 中：个人主体做号码业务需核实是否允许 |
| 虚拟运营商 / 云总机（如 170/171 号段、各类企业云总机 SaaS） | 普通手机号或企业 PBX，**未查到向个人开放 SIP/媒体流的公开产品** | 手机号可个人实名办理；云总机未查到面向个人的公开开通渠道 | 以所选套餐为准 | 以所选套餐为准 | 作手机号用时等同第 5 节副卡；SIP 账号不可得 | 低（实名手机号）；不要用来源不明的“VoIP 账号” |

### 2.2 海外

| 服务商 | 接入方式 | 个人能否开通、门槛 | 号码月费（美国本地） | 呼入每分钟（美国本地） | 中国大陆来电 / 中国号码 | 对接工作量 | 合规风险 |
|---|---|---|---|---|---|---|---|
| Twilio | Media Streams（WebSocket，8 kHz μ-law）、SIP 接口 | 是，自助注册；号码需满足各国监管资料要求 [W3] | $1.15 [W1] | $0.0085 + Media Streams $0.0044 [W1] | **无中国号码**：China 页面呼入/呼出均为 No [W2]；香港号码可用，但从境外打入时主叫显示为 Anonymous [W4] | 小：`pipecat-ws` 已支持（`TWILIO_ACCOUNT_SID/AUTH_TOKEN`） | 中：境外号码；大陆运营商不允许呼转到境外 |
| Telnyx | Call Control + Media Streaming over WebSockets、SIP 中继 | 是，自助注册，“Card on file” [N1] | $1.00 [N1] | Voice API $0.002 + SIP 入站 $0.0032（官方页示例费率）+ 媒体流 $0.0035 [N1] | 中国号码：官方页未查到（需咨询） | 小：`pipecat-ws` 已支持（`TELNYX_API_KEY`） | 同上 |
| Plivo | Audio Streaming（WebSocket）、SIP | 是，自助注册（账号审核以官方为准） | $0.50 [P1] | $0.0055，音频流已含 [P1] | **中国呼入：Not Supported** [P2] | 小：`pipecat-ws` 已支持（`PLIVO_AUTH_ID/AUTH_TOKEN`） | 同上 |
| Vonage（Communications APIs） | Voice API WebSocket、SIP | 是，自助注册 | 官方 CLI 文档示例显示美国号码 €0.90/月 [V2]（实际以控制台为准） | 官方价格页动态加载，未取到（需在控制台查询）[V1]；转给 Voice API 应用或 SIP 的那一段免费，只收入站段 [V3] | 中国号码：未查到（需咨询） | 中：Pipecat 有 Vonage serializer，但 `pipecat-ws` 适配器尚未接入，需加一个分支和测试 | 同上 |

**海外方案的用途**：在不碰国内线路的情况下端到端验证电话链路（8 kHz 编解码、打断、挂断、延迟）。例如买一个美国号码，用 Web 软电话或境外 SIM 打进去测试。它不能接收大陆手机转来的电话。

---

## 3. 用户自己手机的呼叫转移

### 3.1 能转到哪里

| 目标 | 中国移动 | 中国电信 | 中国联通 |
|---|---|---|---|
| 国内手机号（含本人副卡、虚拟运营商号段） | 可以 [M1][M2] | 可以（13/14/15/18 等号段开放）[C1] | 可以（官方页需登录，以 10010 为准）[U1] |
| 国内固话 / 云号码（固话格式，需加区号） | 可以，需加区号 [M1] | 可以，需加区号 [C1] | 以 10010 为准 |
| IP 电话 | 上海移动：**暂不允许**；也不允许二次呼转 [M2] | 9 字头号码不允许 [C1] | 以 10010 为准 |
| 境外号码（含港澳台） | **不可以**：前转号码需为国内（不含港澳台）号码 [M2] | **不可以**：不能为国际长途（含港澳台）[C1] | 未在公开官方页查到（需咨询 10010） |

所以云号码只要是**国内号码**（如阿里云语音中继号这类固话格式号码），理论上可作为呼转目标；是否会被运营商当作“IP 电话”拒绝**需实测**。

### 3.2 费用（主号承担，按运营商官方页）

| 运营商（页面） | 呼转费 |
|---|---|
| 中国移动（黑龙江）| 功能费 0 元/月；基本呼转费 0.10 元/分钟（转固话、手机等）[M3] |
| 中国移动（上海）| 转上海 0.1 元/分钟，转外省 0.6 元/分钟（全包价）；呼转分钟**不能**用套餐内分钟抵扣 [M2] |
| 中国移动（福建）| 本地 0.1 元/分钟；转异地加收归属地至前转地长途费；有条件呼转漫游时 0.6 元/分钟 [M1] |
| 中国电信（广东）| 功能费 0 元/月；后付费 0.1 元/分钟，转非归属地另加国内长途 0.07 元/6 秒 [C1] |
| 中国联通 | 公开官方页未查到（需咨询 10010） |

各省资费不同，**以本人号码归属省份的官方页面或 10086/10000/10010 为准**。最省钱的做法是让呼转目标与主号同一归属地。

### 3.3 设置方法（GSM 补充业务码，三家通用，以运营商说明为准）

| 类型 | 设置 | 取消 |
|---|---|---|
| 无条件 | `**21*号码#` | `##21#` |
| 遇忙 | `**67*号码#` | `##67#` |
| 无应答 | `**61*号码#` | `##61#` |
| 不可及（关机/无信号） | `**62*号码#` | `##62#` |
| 取消全部 | | `##002#` |

来源：福建移动官方页 [M1]。上海移动说明无应答默认振铃 15 秒后转移 [M2]。中国电信广东页面说明呼叫等待优先级高于遇忙转移，开了呼叫等待会导致遇忙转移不生效 [C1]。

### 3.4 来电显示是否保留原主叫号码

情报提取需要骗子的真实主叫号码。官方页面**没有**写明呼转后被叫看到的是原主叫还是主号：中国电信广东页面只说“来电方不会获知你的转移号码”[C1]。实际经验通常是显示原主叫，但**需按运营商与目标号码类型（手机/固话/中继号）实测**；SIP 中继侧可在 INVITE 的 From/P-Asserted-Identity 或 Diversion 头里看到哪些号码，也要上线前确认。海外线路即使能接通，Twilio 香港页面已写明境外打入的主叫显示为 Anonymous [W4]。

### 3.5 只转陌生号是否可行

运营商呼转本身**不能按号码筛选**，只能借手机侧行为触发“有条件转移”：

| 做法 | 原理 | 可行性 |
|---|---|---|
| iPhone：设置 → 电话 → 静音未知来电 + 关闭实时语音留言 + 无应答转移 `**61*` | 陌生来电静音不应答，到时触发无应答转移 | 需实测；联系人未接也会被转走；对方要多等约 15 秒 |
| Android：骚扰拦截/黑名单 + 遇忙转移 `**67*` | 系统 `CallScreeningService` 的 `setRejectCall` 语义是“如同用户手动拒接”[G1]；手动拒接在多数网络上会触发遇忙转移 | **需实测**：各厂商“拦截”实现可能是静默挂断或不振铃，未必走遇忙；开呼叫等待会使遇忙转移失效 [C1] |
| 华为/荣耀等系统的“拦截陌生通话、高风险电话、海外号码来电”规则 [H3] | 拦截后是否触发运营商转移，官方页未说明 | 需实测 |
| 运营商侧防骚扰 / 境外来电拦截（如联通“国际电话拦截”） | 网络侧直接拦截 | 只拦截，**未查到**“拦截后转到指定号码”的公开选项 |
| 把副卡号码当“对外泄露号”，对它设无条件转移 | 不靠筛选，副卡本身只给陌生渠道 | 可行，最稳定 |

---

## 4. 推荐方案与月成本估算

假设：每月 60 分钟诈骗/营销来电被转走；主号与转移目标同一归属地；AI 费用按百炼目录价约 0.045 元/分钟（ASR 0.014 + TTS 0.016 + qwen-plus 0.015，见第 5.3 节）；汇率按 1 美元 ≈ 7.1 元粗算（仅用于比较，非官方）；云主机、电费、副卡月租未计入（以所选套餐为准）。

| 方案 | 适用 | 固定 | 每分钟 | 60 分钟/月合计 |
|---|---|---|---|---|
| **A. 个人推荐：主号呼转 → 本人副卡 → EC20/EG25 模组 → DeepSuck** | 现在就能做，个人实名即可 | 副卡月租（套餐价，未计）+ 模组一次性 | 呼转 0.1 元 + AI 0.045 元 | 约 8.7 元 + 副卡月租 |
| **B. 有企业主体时的云原生主线：主号呼转 → 阿里云语音 SIP 中继号 → SIP 网关 → `ws-raw`** | 有营业执照，能走阿里云邀约 | 号码 35 元 | 呼入 0.11 元 + 呼转 0.1 元 + AI 0.045 元 | 约 50.3 元 + 云主机 |
| **C. 联调/测试：海外号码 → `pipecat-ws`** | 只验证链路，不接大陆转入电话 | Plivo $0.50 / Telnyx $1.00 / Twilio $1.15 | Plivo $0.0055；Telnyx $0.0087；Twilio $0.0129（含媒体流） | Plivo 约 $0.83；Telnyx 约 $1.52；Twilio 约 $1.92（另加 AI 约 2.7 元） |

计算：A = 60 × (0.1 + 0.045) = 8.7 元；B = 35 + 60 × (0.11 + 0.1 + 0.045) = 50.3 元；C 例如 Twilio = 1.15 + 60 × (0.0085 + 0.0044) = $1.92。

理由：

1. **A 是个人唯一能拿到原始音频、又能接住大陆转入电话的路线**。号码本人实名、只接不拨，合规负担最轻；成本大头是呼转费。代价是需要一块模组和一台常开机器（第 5 节），且 EC20 适配器还没写（`ws-raw` 协议已经可以承接：模组桥接进程把 PCM 推给 `/telephony/ws-raw`）。
2. **B 是长期主线**，与浏览器版共用一套管线，可上云、可扩容；前提是企业资质和阿里云邀约，个人做不了。
3. **C 只用来测试**：几美元就能验证电话链路的延迟和打断；切勿把它当作接骗子电话的生产线路（大陆号码呼转不过去，主叫号码也可能丢失）。

---

## 5. 自备硬件路线（EC20/EG25 模组 + 副卡）

```
诈骗来电 ──► 你的主号
               │ 联系人：正常响铃
               │ 陌生号：静音/拒接 → 无应答/遇忙转移（第 3.5 节）
               ▼
          你本人实名的第二张 SIM（副卡）
               ▼
   EC20 / EG25 4G 模组（USB：AT 指令 + UAC 声卡，8 kHz PCM）
               ▼  桥接进程：PCM ↔ ws-raw
   DeepSuck voice（/telephony/ws-raw，Pipecat 级联管线）
```

### 5.1 硬件

| 物品 | 说明 |
|---|---|
| Quectel EC20 / EG25 USB 模组（带 UAC 语音固件） | 必须支持 **VoLTE**（国内 2G/3G 逐步退网，**需按运营商实测**）；价格以购买渠道为准 |
| 天线 + USB 转接板 | |
| 副卡（本人实名） | 被叫一般不收费，以套餐为准 |
| 常开的 Linux 机器（树莓派、旧笔记本、NAS） | 只需出网访问百炼 |

关键 AT 指令：`ATA` 接听、`ATH` 挂断、`AT+CLCC` 当前通话（含来电号码）、`AT+QPCMV=1,2` 打开 USB 语音（UAC）。以模组固件手册为准。可参考 [tianye1999/callpilot](https://github.com/tianye1999/callpilot)（Apache-2.0）的 AT 状态机与 UAC 音频桥。

旧安卓手机不适合接电话：Android 10 起普通 App 拿不到通话双向音频，只适合做短信通道（转发诈骗短信到 webhook）。

多线路（可选）：Asterisk + chan_quectel，再用 AudioSocket / chan_websocket 接 `ws-raw`。GPL 组件只作为独立进程通过网络对接，不进入仓库代码。

### 5.2 管线

与浏览器版相同：Silero VAD → Paraformer 实时 ASR → 拖延策略 + qwen-plus → CosyVoice 流式 TTS；电话链路有单独的延迟参数（`DEEPSUCK_PHONE_LAT_*`，见 [VOICE_LATENCY.md](VOICE_LATENCY.md)）。

### 5.3 AI 费用（阿里云百炼北京地域目录价，沿用本文旧版数据）

| 项目 | 单价 | 每通话分钟 |
|---|---|---|
| Paraformer 实时 ASR | 0.00024 元/秒 | 约 0.014 元 |
| CosyVoice TTS | 0.8 元/万字符（1 汉字 = 2 字符） | 每分钟约 100 字，约 0.016 元 |
| qwen-plus | 输入 0.0008 / 输出 0.002 元/千 token | 约 0.015 元 |

建议在百炼控制台设置费用告警；`VOICE_DAILY_BUDGET_CNY` 护栏对电话入口同样生效。

---

## 6. 环境变量清单（供 `deploy/` 使用）

电话入口默认关闭；下表的默认值就是不设置时的行为。`deploy/` 已接入这些变量（见 `deploy/.env.example`，默认全部关闭），容器内 `DATA_DIR=/data` 挂命名卷 `voice-data`。

### 6.1 电话入口

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_TELEPHONY` | `0` | `1` 才挂载 `WS /telephony/{adapter}` |
| `VOICE_TELEPHONY_TOKEN` | 空 | **必填**；为空时即使 `VOICE_TELEPHONY=1` 也拒绝连接。桥接方带 `?token=` 或 `Authorization: Bearer` |
| `VOICE_TELEPHONY_ADAPTERS` | `ws-raw` | 允许的适配器，逗号分隔：`ws-raw`、`pipecat-ws` |
| `VOICE_TELEPHONY_PERSONA` | `wang` | 电话默认人设 |
| `VOICE_TELEPHONY_SCENARIO` | `refund` | 电话默认场景 |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | 空 | 仅 `pipecat-ws` + Twilio，用于 REST 挂断 |
| `TELNYX_API_KEY` | 空 | 仅 `pipecat-ws` + Telnyx |
| `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` | 空 | 仅 `pipecat-ws` + Plivo |
| `DEEPSUCK_PHONE_LAT_<字段>` | 见 VOICE_LATENCY.md | 电话链路的 ASR 静音、VAD、打断、填充音参数 |

### 6.2 告知语（网页和电话共用）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_AI_DISCLOSURE` | `0` | `1` 时在开场白前先播告知语 |
| `VOICE_AI_DISCLOSURE_TEXT` | `本通话由智能助理接听。` | 自定义告知语文案，仅在 `VOICE_AI_DISCLOSURE=1` 时生效 |
| `VOICE_TELEPHONY_DISCLOSURE` | — | 旧变量，已废弃：设置了也不会播，只在日志里提示改用上面两个 |

### 6.3 留存

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATA_DIR` | `~/.local/share/deepsuck` | 数据根目录；留存文件在 `$DATA_DIR/voice/{transcripts,audio}/`。Docker 部署应挂卷 |
| `VOICE_TRANSCRIPTS` | `1` | 每通结束保存一份**脱敏**文字记录（JSON）；`0` 关闭 |
| `VOICE_TRANSCRIPT_DAYS` | `30` | 文字记录保留天数；`0` 表示不自动删除 |
| `KEEP_AUDIO` | `0` | `1` 才保存原始音频（对方、机器人各一个 WAV） |
| `KEEP_AUDIO_DAYS` | `7` | 音频保留天数，1 至 7，超过 7 按 7 处理 |

清理在服务启动时执行一次，之后每小时一次。关掉 `KEEP_AUDIO` 后，已有音频照样按期删除。

---

## 7. 录音与告知语策略（已实现）

- **默认不保存任何原始音频**，只保存脱敏后的文字记录。文字在进入会话时已脱敏，落盘前再逐条调用共享模块 `deepsuck.redact.redact_text(text, extract_sensitive(text))`（见 [INTEL.md「脱敏接口」](INTEL.md)），`voice/` 不另写脱敏规则。卡号等原值只在进程内存中。
- 记录文件名只含时间、通道和随机通话 ID，不含主叫号码；日志里的号码只保留后 4 位。
- `KEEP_AUDIO=1` 时保存的 WAV 是**未脱敏的原始声音**（可能包含卡号、姓名），只应在需要向 110 / 96110 提交证据时短期开启，最长 7 天。
- 开场 AI 告知语默认不播（负责人决定），可用 `VOICE_AI_DISCLOSURE=1` 打开。网页和电话入口都生效。

## 8. 合规边界

- **本人实名、只接不拨**：仓库没有任何外呼代码；不实现群呼、改主叫号码、多卡池（《反电信网络诈骗法》严禁猫池、GOIP、违规 VoIP 接入）。
- 不使用来源不明的 VoIP 账号或“虚拟号”转接，不把副卡借给他人。
- 对外只发布按[情报库发布策略](INTEL.md)处理过的指标；原始证据交给 110 / 96110 / 国家反诈中心 App。
- 人设不冒充真实机构或个人，不给出任何真实账户或验证码。
- 是否必须播报 AI 告知语、是否可以录音，随所在地法规和服务商条款变化；开启录音前请自行确认。

## 9. 待验证

- [ ] 三大运营商呼转到本人副卡 / 国内中继号时，被叫看到的是否为原主叫号码
- [ ] 呼转到阿里云语音中继号这类固话格式号码是否被当作 IP 电话拒绝
- [ ] Android 拦截/拒接是否触发遇忙转移（按品牌、运营商）；iPhone 静音未知来电 + 无应答转移的实际时长
- [ ] EC20/EG25 各型号 × 运营商的 VoLTE 兼容性；模组桥接到 `ws-raw` 的实现
- [ ] 腾讯云联络中心、容联云通讯能否向自建服务输出原始媒体流，以及个人开发者能否开通呼入

---

## 参考（均于 2026-10-18 查询）

- [A1] 阿里云 语音SIP和语音双呼定价：https://help.aliyun.com/zh/vms/voice-sip-and-voice-dual-pricing
- [A2] 阿里云 语音SIP接入流程：https://help.aliyun.com/zh/vms/voice-sip-access-process
- [A3] 阿里云 申请企业资质：https://help.aliyun.com/zh/vms/user-guide/enterprise-qualification-management
- [T1] 腾讯云 云联络中心 电话号码购买指引：https://cloud.tencent.com/document/product/679/63785
- [T2] 腾讯云 云联络中心 电话号码申请：https://cloud.tencent.com/document/product/679/73526
- [T3] 腾讯云 云联络中心 计费概述：https://cloud.tencent.com/document/product/679/95641
- [H1] 华为云 个人用户和个体用户能否使用隐私保护通话服务：https://www.huaweicloud.com/guide/productsdesc-bms_dd44dd346f2cea8faf292b5fbc093f3csupport0
- [H2] 华为云 隐私保护通话价格说明：https://support.huaweicloud.com/price-PrivateNumber/privatenumber_06_0001.html
- [H3] 华为 拦截骚扰电话：https://consumer.huawei.com/cn/support/content/zh-cn16093656/
- [R1] 容联云通讯 账号类型：https://console.yuntongxun.com/doc/ready/cooperation/1_2_1_3.html
- [R2] 容联云通讯 呼入服务：https://console.yuntongxun.com/product/huru.html
- [R3] 容联云通讯 账号及费用常见问题：https://console.yuntongxun.com/doc/ready/about/1_1_2_2.html
- [W1] Twilio Voice pricing (US)：https://www.twilio.com/en-us/voice/pricing/us
- [W2] Twilio China Voice Guidelines：https://www.twilio.com/en-us/guidelines/cn/voice
- [W3] Twilio Regulatory Guidelines：https://www.twilio.com/en-us/guidelines/regulatory
- [W4] Twilio Hong Kong Voice Guidelines：https://www.twilio.com/en-us/guidelines/hk/voice
- [N1] Telnyx Voice API Pricing：https://telnyx.com/pricing/call-control
- [P1] Plivo Voice Pricing (US)：https://www.plivo.com/voice/pricing/us/
- [P2] Plivo Voice Pricing (China)：https://www.plivo.com/voice/pricing/cn/
- [V1] Vonage Voice API pricing：https://www.vonage.com/communications-apis/voice/pricing/
- [V2] Vonage CLI 管理号码（含号码月费示例）：https://developer.vonage.com/en/vonage-cli/guides/numbers/managing-numbers
- [V3] Vonage 呼入呼出计费说明：https://api.support.vonage.com/hc/en-us/articles/204015203-How-does-voice-pricing-work-for-inbound-and-outbound-calls
- [M1] 福建移动 语音呼转：https://www.fj.10086.cn/products/txl/hjzy/index.html
- [M2] 上海移动 国内呼叫转移：https://www.sh.10086.cn/h5/common/doBusiness/callTransfer.html
- [M3] 黑龙江移动 呼叫转移设置：http://www.hl.10086.cn/apps/busi/call-shift/call-shift.html
- [C1] 广东电信 手机呼叫转移设置：http://gd.189.cn/service_new/byw/sj_hjzy.htm
- [U1] 中国联通 呼叫转移（网上营业厅，需登录）：http://iservice.10010.com/e4/transact/basic/call_shift.html
- [G1] Android Developers 过滤来电（CallScreeningService）：https://developer.android.com/develop/connectivity/telecom/dialer-app/screen-calls?hl=zh-cn
