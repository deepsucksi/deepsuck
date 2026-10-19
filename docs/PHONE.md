# DeepSuck 电话接入方案

> 现状（2026-10-18）：`voice/telephony/` 已有电话接入适配层（`ws-raw`、`pipecat-ws`、`asterisk-ws`），**默认关闭，只接听、不外呼**；项目没有购买任何号码；`deploy/` 已带电话入口开关（默认关闭），并新增默认关闭的自建 SIP 软电话 profile（第 10 节，零成本，只用于自己手机演示）。本文回答“用什么云原生线路把骗子电话的**原始音频**接进来”，并整理所有电话相关环境变量。
>
> 价格只写从官方页面查到的数字，并注明链接与查询日期（全部为 **2026-10-18** 查询）；官方页查不到的写“未公开/需咨询”。标注“需实测”的是推断或社区经验，不是官方承诺。

## 目录

1. 结论速览
2. 云接入方案对比（国内 / 海外）
3. 用户自己手机的呼叫转移
4. 推荐方案与月成本估算
5. 已排除方案
6. 环境变量清单（供 `deploy/` 使用）
7. 录音与告知语策略
8. 合规边界
9. 待验证
10. 自建 SIP 软电话接入（零成本）

---

## 1. 结论速览

- **国内云服务商能拿到原始音频的只有 SIP 中继类产品，而且全部要求企业资质。** 阿里云语音 SIP 为邀约制并需企业资质；腾讯云联络中心、华为云隐私保护通话明确只面向企业认证用户。容联云通讯有“个人开发者”认证，但呼入/号码业务是否对个人开放官方未写明（需咨询）。没有查到面向个人、能把媒体流交给自建服务的国内云号码。
- **海外服务商（Twilio、Telnyx、Plivo、Vonage）个人可注册，都提供 WebSocket 媒体流**，与现有 `pipecat-ws` 适配器基本即插即用；但**拿不到中国大陆号码**（Twilio 官方 China 页面：呼入呼出均不支持；Plivo 中国：呼入不支持），而且**大陆三大运营商不允许把手机呼叫转移到境外（含港澳台）号码**。所以海外线路只适合联调和测试，接不到转给你的大陆骗子电话。
- **跨境转接走不通**：中国移动、中国电信官方页写明呼叫转移不能转到境外（含港澳台）号码；中国联通公开官方页查不到，待咨询 10010（第 3.1 节）。所以“手机呼转到海外号码”不能作为方案。
- **推荐（第 4 节）**：长期走**阿里云语音 SIP 中继（需企业主体；号码 35 元/月，呼入 0.11 元/分钟）→ SIP 网关 → `ws-raw` → 现有管线**；当前没有企业主体时，只用**海外号码接 `pipecat-ws` 做联调演示**，不接真实转入电话。**容联云通讯个人开发者**列为待咨询候选。
- 项目只用云原生接入，不用实体 SIM、4G 模组或旧手机，相关方案见第 5 节“已排除方案”。
- **零成本演示（第 10 节）**：`deploy/` 新增默认关闭的 `sip` profile（Asterisk 22 + chan_websocket → `asterisk-ws` 适配器），自己手机上的 Linphone/Zoiper 注册后拨一个分机就能用电话音质跟 AI 对话，不花号码费。它**不是电话号码**：没有接入任何运营商或外线，骗子打不进来，也不能被呼叫转移，只能自己演示、调延迟和打断。

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
| 虚拟运营商 / 云总机（如 170/171 号段、各类企业云总机 SaaS） | 普通手机号或企业 PBX，**未查到向个人开放 SIP/媒体流的公开产品** | 手机号可个人实名办理；云总机未查到面向个人的公开开通渠道 | 以所选套餐为准 | 以所选套餐为准 | 实体 SIM 路线已排除（第 5 节）；SIP 账号不可得 | 低（实名手机号）；不要用来源不明的“VoIP 账号” |

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
| 国内手机号（含虚拟运营商号段） | 可以 [M1][M2] | 可以（13/14/15/18 等号段开放）[C1] | 可以（官方页需登录，以 10010 为准）[U1] |
| 国内固话 / 云号码（固话格式，需加区号） | 可以，需加区号 [M1] | 可以，需加区号 [C1] | 以 10010 为准 |
| IP 电话 | 上海移动：**暂不允许**；也不允许二次呼转 [M2] | 9 字头号码不允许 [C1] | 以 10010 为准 |
| 境外号码（含港澳台） | **不可以**：前转号码需为国内（不含港澳台）号码 [M2] | **不可以**：不能为国际长途（含港澳台）[C1] | 未在公开官方页查到（需咨询 10010） |

中国移动、中国电信不能转境外，联通待咨询，因此**跨境转接走不通**，海外号码只能接直接拨打它的电话。云号码只要是**国内号码**（如阿里云语音中继号这类固话格式号码），理论上可作为呼转目标；是否会被运营商当作“IP 电话”拒绝**需实测**。

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
| 把一个云号码当“对外泄露号”直接公布 | 不靠呼转筛选，号码本身只给陌生渠道 | 可行（需先有国内云号码，即第 4 节长期方案） |

---

## 4. 推荐方案与月成本估算

假设：每月 60 分钟诈骗/营销来电；主号与转移目标同一归属地；AI 费用按百炼目录价约 0.045 元/分钟（ASR 0.014 + TTS 0.016 + qwen3.8-flash 约 0.015（非思考），见第 4.3 节）；云主机未计入（以所选实例为准）。海外价格以美元列出，不做汇率换算。

| 方案 | 定位 | 固定 | 每分钟 | 60 分钟/月合计 |
|---|---|---|---|---|
| **长期：主号呼转 → 阿里云语音 SIP 中继号 → SIP 网关 → `ws-raw`** | 生产主线；**需企业主体**、阿里云邀约 | 号码 35 元 [A1] | 呼入 0.11 元 [A1] + 呼转约 0.1 元 [M3][C1] + AI 0.045 元 | 约 50.3 元 + 云主机 |
| **当前：海外号码 → `pipecat-ws`** | **仅联调演示**，直接拨打海外号码测试；不接大陆转入电话 | Plivo $0.50 / Telnyx $1.00 / Twilio $1.15 | Plivo $0.0055；Telnyx $0.0087；Twilio $0.0129（含媒体流） | Plivo 约 $0.83；Telnyx 约 $1.52；Twilio 约 $1.92（另加 AI 约 2.7 元） |
| 待咨询候选：容联云通讯（个人开发者） | 有个人开发者认证 [R1]，但呼入/号码与原始媒体流是否对个人开放未公开 | 未公开/需咨询 | 未公开/需咨询 | 无法估算 |
| **演示：自建 SIP 软电话 → Asterisk → `asterisk-ws`（第 10 节）** | **个体户/个人现在就能用**；只能自己手机软电话拨分机，不是真实号码，骗子打不进来 | 0（复用现有服务器，多占约 20 MB 内存） | 只有 AI 费用约 0.045 元 + 手机流量 | 约 2.7 元（仅 AI） |

计算：长期 = 35 + 60 × (0.11 + 0.1 + 0.045) = 50.3 元；Twilio = 1.15 + 60 × (0.0085 + 0.0044) = $1.92；Telnyx = 1.00 + 60 × (0.002 + 0.0032 + 0.0035) ≈ $1.52；Plivo = 0.50 + 60 × 0.0055 = $0.83。

### 4.1 理由

1. **阿里云 SIP 中继是唯一查到的、能拿到原始媒体流的国内正规线路**，号码是国内号码，用户手机可以呼转过去（是否会被当作 IP 电话拒绝、主叫号码是否保留需实测，见第 9 节）。与浏览器版共用一套管线，可上云扩容。前提是企业资质和阿里云邀约，个人做不了。
2. **海外号码只做联调演示**：几美元就能端到端验证电话链路（8 kHz 编解码、打断、挂断、延迟），`pipecat-ws` 已支持 Twilio/Telnyx/Plivo。但大陆号码转不过去（移动、电信不能转境外，联通待咨询），境外打入时主叫号码还可能显示为匿名 [W4]，不能作为接骗子电话的生产线路。
3. **容联云通讯个人开发者**是目前唯一可能面向个人的国内候选，需要先向官方咨询个人能否开通呼入号码、能否把媒体流交给自建服务，再决定是否投入。
4. **在没有企业主体之前，演示和调参用自建 SIP 软电话（第 10 节）**：零成本、国内手机直接能用、走真实的 SIP/RTP 和电话编解码（Opus/G.722/G.711），能验证电话链路上的延迟、打断和挂断，比海外号码更省事。但它只是“自己的手机软电话拨进自己的服务器”，**不能接骗子来电**；拿到企业主体后，阿里云 SIP 中继可以接到同一台 Asterisk（加一个中继端点和号码路由），后面的 `asterisk-ws` 与管线不用改，那是另一项工作。

### 4.2 管线

与浏览器版相同：Silero VAD → Paraformer 实时 ASR → 拖延策略 + qwen3.8-flash → CosyVoice 流式 TTS；电话链路有单独的延迟参数（`DEEPSUCK_PHONE_LAT_*`，见 [VOICE_LATENCY.md](VOICE_LATENCY.md)）。

### 4.3 AI 费用（阿里云百炼北京地域目录价，沿用本文旧版数据）

| 项目 | 单价 | 每通话分钟 |
|---|---|---|
| Paraformer 实时 ASR | 0.00024 元/秒 | 约 0.014 元 |
| CosyVoice TTS | 0.8 元/万字符（1 汉字 = 2 字符） | 每分钟约 100 字，约 0.016 元 |
| qwen3.8-flash（非思考） | 输入 0.0008 / 输出 0.0027 元/千 token | 约 0.015 元（2026-10-19 起统一用 Qwen 最新系列，见 [LLM_AB.md](LLM_AB.md)） |

建议在百炼控制台设置费用告警；`VOICE_DAILY_BUDGET_CNY` 护栏对电话入口同样生效。

---

## 5. 已排除方案

| 方案 | 排除原因 |
|---|---|
| 实体 SIM 副卡 + 4G 模组（如 EC20/EG25） | 项目原则只用云原生接入，不用实体 SIM、4G 模块；需要自备硬件和常开机器，无法随服务一起部署与扩容 |
| 旧安卓手机接听 | 同上；且 Android 10 起普通 App 拿不到通话双向音频，只能靠免提声学耦合，质量和稳定性差 |
| 手机呼转到海外号码（Twilio/Telnyx/Plivo/Vonage） | 中国移动、中国电信不允许呼转到境外（含港澳台）号码 [M2][C1]，联通待咨询；Twilio 无中国号码 [W2]，Plivo 中国呼入不支持 [P2] |
| 腾讯云联络中心、华为云隐私保护通话 | 只面向企业认证用户 [T1][H1]；华为隐私号拿不到原始音频，腾讯是否开放媒体流未公开 |
| 来源不明的 VoIP 账号、“虚拟号”转接、多卡设备 | 合规风险（见第 8 节） |

---

## 6. 环境变量清单（供 `deploy/` 使用）

电话入口默认关闭；下表的默认值就是不设置时的行为。`deploy/` 已接入这些变量（见 `deploy/.env.example`，默认全部关闭），容器内 `DATA_DIR=/data` 挂命名卷 `voice-data`。

### 6.1 电话入口

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_TELEPHONY` | `0` | `1` 才挂载 `WS /telephony/{adapter}` |
| `VOICE_TELEPHONY_TOKEN` | 空 | **必填**；为空时即使 `VOICE_TELEPHONY=1` 也拒绝连接。桥接方带 `?token=`、`Authorization: Bearer` 或 HTTP Basic（密码 = token；Asterisk 用这种）。推荐用请求头：`?token=` 会出现在访问日志的 URL 里 |
| `VOICE_TELEPHONY_ADAPTERS` | `ws-raw` | 允许的适配器，逗号分隔：`ws-raw`、`pipecat-ws`、`asterisk-ws`（自建 SIP，第 10 节） |
| `VOICE_TELEPHONY_PERSONA` | `wang` | 电话默认人设 |
| `VOICE_TELEPHONY_SCENARIO` | `refund` | 电话默认场景 |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | 空 | 仅 `pipecat-ws` + Twilio，用于 REST 挂断 |
| `TELNYX_API_KEY` | 空 | 仅 `pipecat-ws` + Telnyx |
| `PLIVO_AUTH_ID` / `PLIVO_AUTH_TOKEN` | 空 | 仅 `pipecat-ws` + Plivo |
| `DEEPSUCK_PHONE_LAT_<字段>` | 见 VOICE_LATENCY.md | 电话链路的 ASR 静音、VAD、打断、填充音参数 |
| `DEEPSUCK_BACKCHANNEL` | `1` | 短口头语（网页和电话共用）：回合结束即播预合成的"嗯……""啊？"；`0` 回到按延迟触发的填充音。音频 24k 预合成，电话输出时统一重采样到 8k |
| `DEEPSUCK_FILLER_CACHE_DIR` | 空（= `$DATA_DIR/voice/fillers`） | 口头语音频缓存目录 |
| `DEEPSUCK_TURN_DIGITS` | `1` | 回合判定（网页和电话共用）：对方念数字时多等（`DEEPSUCK_PHONE_LAT_TURN_DIGIT_HOLD_MS`，默认 1800）、完整句不等 Smart Turn 3 s 兜底（`DEEPSUCK_PHONE_LAT_TURN_TEXT_COMPLETE_MS`，默认 1200）；见 VOICE_LATENCY.md |

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

### 6.4 自建 SIP 软电话（`docker compose --profile sip`，第 10 节）

只有 `sip` 容器读取这些变量（它不读整份 `.env`，拿不到 `DASHSCOPE_API_KEY`）。开启前提：`VOICE_TELEPHONY=1`、`VOICE_TELEPHONY_TOKEN` 已设、`VOICE_TELEPHONY_ADAPTERS` 含 `asterisk-ws`，否则 `sip` 容器拒绝启动。`bootstrap.sh` 用 `WITH_SIP=1` 会自动补齐。

| 变量 | 默认 | 说明 |
|---|---|---|
| `SIP_USER` | 空 | **必填**。手机软电话的分机账号，3–32 位字母/数字/`_.-`；建议不好猜（bootstrap 生成 `ds` + 8 位随机十六进制） |
| `SIP_PASSWORD` | 空 | **必填**，至少 16 位，只能含字母/数字/`._~+=-`；为空、太短或与账号相同时拒绝启动（bootstrap 生成 32 位随机十六进制） |
| `SIP_PORT` | `25060` | SIP 信令端口（UDP）；不要用 5060 |
| `SIP_TCP` | `0` | `1` 时同一端口再开 SIP over TCP |
| `SIP_AI_EXTEN` | `9000` | 唯一能接通 AI 的分机号（3–8 位数字）；拨其他号码一律 404 |
| `SIP_RTP_PORTS` | `40100-40199` | Asterisk 的 RTP 端口段；开 SIP 时 `VOICE_UDP_PORTS` 改成 `40000-40099`，两段不重叠 |
| `SIP_MAX_CALLS` | `1` | 同时通话数（1–9），超出回 486 忙；voice 侧的并发、预算、时长护栏照常生效 |
| `SIP_CODECS` | `opus,g722,ulaw,alaw` | 手机侧允许的编码（按优先级）；进 voice 前统一转成 16 kHz 线性 PCM |
| `SIP_ALLOW_CIDR` | 空 | 可选，只允许这些来源 IPv4 段注册/呼叫（逗号分隔 CIDR），其余 403；留空不限制 |
| `SIP_PUBLIC_IP` | 空 | 可选，SDP 和 Contact 里写的公网 IP；留空用 `VOICE_PUBLIC_IP` |
| `SIP_LOG_DIR` | `/var/log/deepsuck-sip` | 宿主机上的 Asterisk security 日志目录（fail2ban 读取） |
| `SIP_MEM_LIMIT` | `64m` | `sip` 容器内存上限 |
| `VOICE_UDP_PORTS` | `40000-40199` | 已有变量；开 SIP 时改为 `40000-40099` |

bootstrap 开关：`WITH_SIP=1`（启用 `sip` profile、补齐上面的变量、装 fail2ban 与 logrotate），`SKIP_FAIL2BAN=1`（不装 fail2ban）。

---

## 7. 录音与告知语策略（已实现）

- **默认不保存任何原始音频**，只保存脱敏后的文字记录。文字在进入会话时已脱敏，落盘前再逐条调用共享模块 `deepsuck.redact.redact_text(text, extract_sensitive(text))`（见 [INTEL.md「脱敏接口」](INTEL.md)），`voice/` 不另写脱敏规则。卡号等原值只在进程内存中。
- 记录文件名只含时间、通道和随机通话 ID，不含主叫号码；日志里的号码只保留后 4 位。
- `KEEP_AUDIO=1` 时保存的 WAV 是**未脱敏的原始声音**（可能包含卡号、姓名），只应在需要向 110 / 96110 提交证据时短期开启，最长 7 天。
- 开场 AI 告知语默认不播（负责人决定），可用 `VOICE_AI_DISCLOSURE=1` 打开。网页和电话入口都生效。

## 8. 合规边界

- **本人实名、只接不拨**：仓库没有任何外呼代码；不实现群呼、改主叫号码、多卡池（《反电信网络诈骗法》严禁猫池、GOIP、违规 VoIP 接入）。
- 不使用来源不明的 VoIP 账号或“虚拟号”转接，不使用实体 SIM、4G 模组或多卡设备接入。
- 对外只发布按[情报库发布策略](INTEL.md)处理过的指标；原始证据交给 110 / 96110 / 国家反诈中心 App。
- 人设不冒充真实机构或个人，不给出任何真实账户或验证码。
- 是否必须播报 AI 告知语、是否可以录音，随所在地法规和服务商条款变化；开启录音前请自行确认。

## 9. 待验证

- [ ] 三大运营商呼转到国内中继号时，被叫看到的是否为原主叫号码；联通能否呼转到境外号码（咨询 10010）
- [ ] 呼转到阿里云语音中继号这类固话格式号码是否被当作 IP 电话拒绝
- [ ] Android 拦截/拒接是否触发遇忙转移（按品牌、运营商）；iPhone 静音未知来电 + 无应答转移的实际时长
- [ ] 容联云通讯（待咨询候选）：个人开发者能否开通呼入号码、能否向自建服务输出原始媒体流、价格；腾讯云联络中心能否输出媒体流
- [ ] 自建 SIP 软电话（第 10 节）：在真实服务器上用 Linphone/Zoiper 经 4G/5G 和家用 Wi-Fi 各打一次，确认双向有声、无单通；测运营商 NAT 下注册保持（`qualify_frequency=30`）

---

## 10. 自建 SIP 软电话接入（零成本）

> 定位：**只让自己手机上的 SIP 软电话拨进来演示**。它不是电话号码，没有接入任何运营商、中继或外线，骗子打不进来，也不能被手机呼叫转移过来；接真实骗子来电仍要走第 4 节的 SIP 中继（需企业主体）。默认关闭。

### 10.1 架构

```
手机 Linphone / Zoiper（注册分机 SIP_USER，拨 SIP_AI_EXTEN）
   │  SIP 信令：UDP SIP_PORT（默认 25060；可选同端口 TCP）
   │  RTP 媒体：UDP 40100-40199（Opus / G.722 / PCMU / PCMA）
   ▼
sip 容器：Asterisk 22（andrius/asterisk:22.11.0-alpine-3.24，host 网络）
   │  PJSIP 摘要认证 → 拨号计划 deepsuck-in：只有一个分机
   │  Dial(WebSocket/deepsuck/c(slin16)f(json))   ← chan_websocket，Asterisk 负责抖动缓冲、转码和 20 ms 定时
   │  WebSocket 客户端 → ws://127.0.0.1:7860/telephony/asterisk-ws（HTTP Basic，密码 = VOICE_TELEPHONY_TOKEN）
   ▼
voice 容器：TelephonyAdapter "asterisk-ws"（复用 ws-raw 的编解码/重采样）→ 与网页、电话共用的同一条管线
   Silero VAD → Paraformer ASR → 拖延策略 + qwen3.8-flash → CosyVoice TTS → 回到 Asterisk → 手机
```

- 不经过 Caddy：Asterisk 和 voice 都在 host 网络，走本机回环；Caddyfile 对公网请求 `/telephony/asterisk-ws*` 一律回 404。
- `asterisk-ws` 适配器（`voice/telephony/asterisk_ws.py`）解析 chan_websocket 的 `MEDIA_START`（JSON 格式），音频按 `optimal_frame_size` 整帧回送；打断时发 `FLUSH_MEDIA`，结束或护栏触发时发 `HANGUP`；DTMF 走 `DTMF_END`。默认用 `slin16`（16 kHz 线性 PCM），进管线不用重采样；也支持 `slin`、`ulaw`、`alaw`。
- 每通电话照常受 `VOICE_MAX_SESSIONS`、`VOICE_DAILY_BUDGET_CNY`、时长/轮数/静默护栏约束，结束后按第 7 节留存脱敏文字记录。

### 10.2 为什么选 Asterisk + chan_websocket

| 方案 | 镜像 | 音频回放 | 是否要编译 | 结论 |
|---|---|---|---|---|
| **Asterisk 22 + chan_websocket**（本方案） | `andrius/asterisk` Alpine 版，压缩约 25 MB，直接拉；内置 `chan_websocket`、`res_websocket_client`、开源 Opus 编解码 | 双向：二进制帧收发，Asterisk 自动重新分帧、定时，支持 `FLUSH_MEDIA` 打断 | 否 | 选用：最轻、免编译、协议是 WebSocket，正好落在现有 `WS /telephony/{adapter}` 上 |
| Asterisk + AudioSocket | 同上 | 双向，但是 TCP 自定义帧，应用要自己按 20 ms 定时发包 | 否 | 要另起 TCP 服务和自定义 transport，不能复用现有 WebSocket 入口 |
| FreeSWITCH + mod_audio_stream（amigniter） | 官方 FreeSWITCH 包要 SignalWire 令牌；模块需对着 FreeSWITCH 源码编译 | 开源版只把音频推到 WebSocket，回放靠 JSON 里的 base64 写临时文件再播放；双向流在商业版 v1.1.0 | 是 | 不选：要编译、内存大、开源版没有实时双向流 |
| FreeSWITCH + mod_audio_fork（drachtio） | 同上，需编译 | 回放同样以文件为主 | 是 | 不选 |

chan_websocket 从 Asterisk 20.16、21.11、22.6 开始提供，JSON 控制格式从 22.8 开始；镜像固定在 22.11.0（LTS 22 系列），`andrius/asterisk` 仓库持续维护（2026-10 仍在发版）。

### 10.3 内存占用（2026-10-18，本机 Docker 26 实测）

| 状态 | cgroup memory.current | Asterisk 进程 RSS | 说明 |
|---|---|---|---|
| 空闲（已加载 56 个模块） | 5–6 MB | 约 19 MB（含共享库） | `docker stats` 显示约 5.7 MiB |
| 1 路通话（Opus，AI 正常对话） | 约 6 MB | 约 19 MB | 通话后 `memory.peak` 18 MB（含启动时的页缓存） |

- `docker-compose.yml` 给 `sip` 设了 `mem_limit: 64m`（`SIP_MEM_LIMIT`）和 `pids_limit: 256`。
- fail2ban（宿主机）常驻约 20–40 MB（Python 进程，按发行版而定，未在目标服务器实测）。
- 对 1.6 GB 内存 + 2 GB swap 的服务器：现有 voice（上限 700 MB）+ proxy + caddy 的实测峰值约 0.6 GB，加上 SIP 约 20 MB、fail2ban 约 30 MB，余量充足。

### 10.4 部署

前提：已经按 [DEPLOY.md](DEPLOY.md) 部署好实时服务。

```bash
# 新服务器：bootstrap 一步到位（会自动生成分机账号/密码、打开电话入口、拆分 UDP 端口段、装 fail2ban）
LIVE_DOMAIN=... ACME_EMAIL=... DASHSCOPE_API_KEY=... WITH_SIP=1 bash bootstrap.sh
# 已部署的服务器：重新运行 bootstrap 并带上 WITH_SIP=1（已有 .env 只补空值，不覆盖 Key 和已有账号）
WITH_SIP=1 bash bootstrap.sh
# 以后更新时记得带上 profile
cd /opt/deepsuck && git pull && cd deploy && docker compose --profile sip up -d --build
```

手动开启（不用 bootstrap）：在 `deploy/.env` 设 `VOICE_TELEPHONY=1`、`VOICE_TELEPHONY_TOKEN=$(openssl rand -hex 24)`、`VOICE_TELEPHONY_ADAPTERS=asterisk-ws`（已有其他适配器就追加）、`VOICE_UDP_PORTS=40000-40099`、`SIP_USER=ds$(openssl rand -hex 4)`、`SIP_PASSWORD=$(openssl rand -hex 16)`，然后 `docker compose --profile sip up -d`。fail2ban 需另装（见 10.7）。变量含义见第 6.4 节。

关闭：`docker compose stop sip && docker compose rm -f sip`，再把 `VOICE_TELEPHONY` 改回 `0`、`VOICE_UDP_PORTS` 改回 `40000-40199` 后 `docker compose up -d`。

### 10.5 防火墙（云控制台 + ufw）

| 端口 | 协议 | 用途 | 必需 |
|---|---|---|---|
| `SIP_PORT`（默认 25060） | **UDP** | SIP 信令（注册、呼叫） | 开 SIP 时必需 |
| `SIP_PORT`（默认 25060） | TCP | SIP over TCP（仅 `SIP_TCP=1`） | 可选 |
| 40100–40199 | UDP | SIP 通话的 RTP 音频（`SIP_RTP_PORTS`），在服务器已开的 40000–40199 之内 | 已开则不用动 |
| 40000–40099 | UDP | 网页语音 WebRTC（开 SIP 后 `VOICE_UDP_PORTS` 缩到这一段） | 已开则不用动 |

- 不支持 SIP over TLS（5061/TLS）与 SRTP：需要证书和额外配置，演示用途暂不提供；信令有摘要认证，媒体只是演示通话。
- 不用开放任何 Asterisk 管理端口：AMI、ARI、内置 HTTP 都关闭，没有 TCP 监听（`SIP_TCP=1` 时只有 SIP 端口）。
- bootstrap 检测到 ufw 启用时会自动放行上表的端口；云控制台的防火墙要自己加。

### 10.6 手机配置

先在服务器上查账号：`grep -E '^SIP_(USER|PASSWORD|PORT|AI_EXTEN)=' /opt/deepsuck/deploy/.env`（不要截图外发）。

**Linphone（Android / iOS，免费开源）**

1. 首次打开选“使用 SIP 账号”（Use SIP account），不要用 Linphone 自家账号。
2. 用户名 = `SIP_USER`；密码 = `SIP_PASSWORD`；域名 = `服务器公网IP:SIP_PORT`（例如 `203.0.113.7:25060`）；显示名随意。
3. 传输选 **UDP**（服务器开了 `SIP_TCP=1` 才可选 TCP），点登录，状态变为“已连接/Connected”。
4. 设置 → 音频：保持 Opus、G722、PCMU 开启；设置 → 网络：可关闭 ICE/STUN（服务器有公网 IP，不需要）；媒体加密选“无”。
5. 拨号盘输入 `SIP_AI_EXTEN`（默认 9000）拨出，听到 AI 开场白即接通。

**Zoiper 5（免费版即可）**

1. 添加账号 → “是，我有账号” → 输入 `SIP_USER@服务器公网IP:SIP_PORT` 和 `SIP_PASSWORD`。
2. 主机名/服务商页直接下一步；若自动探测卡住，手动选 **SIP UDP**。
3. 账号设置 → 高级：关闭 STUN；编码保留 G.711 µ-law / a-law（有 Opus、G.722 就勾上）。
4. 拨 `SIP_AI_EXTEN`。

常见问题：注册返回 401/403 → 账号密码或 `SIP_ALLOW_CIDR`；连续输错 5 次会被 fail2ban 封 1 小时（`fail2ban-client set deepsuck-sip unbanip <手机公网IP>` 解封）。能接通但听不到声音 → 云防火墙没放行 UDP 40100–40199，或 `VOICE_PUBLIC_IP` 不对。拨通立即 503 → voice 没开电话入口或没启动（`docker compose logs voice`）。486 忙 → 已有一路在通话（`SIP_MAX_CALLS`）。

### 10.7 安全说明（防盗打）

| 风险 | 措施 |
|---|---|
| 盗打外线、被当跳板拨国际长途 | **没有任何外线**：不加载 `res_pjsip_outbound_registration`，没有中继端点、没有 `Dial(PJSIP/...)`；拨号计划只有一个分机，唯一的 `Dial` 是连本机 voice 的 WebSocket |
| 匿名/未认证呼入 | 不加载 `res_pjsip_endpoint_identifier_anonymous` 和按 IP 识别的模块；端点只按用户名识别，所有 INVITE/REGISTER 先 401 质询，认证失败一直 401，到不了拨号计划 |
| 账号密码弱或缺失 | 账号密码只从环境变量读，缺失、少于 16 位、含特殊字符或与账号相同时 `sip` 容器拒绝启动；bootstrap 生成随机账号和 32 位随机密码，日志里不打印密码 |
| 拨其他号码 | 除 `SIP_AI_EXTEN` 外没有任何分机或通配规则，PJSIP 直接回 404；`allow_overlap=no`、`allow_transfer=no`、`allow_subscribe=no` |
| 暴力破解 / 扫号 | 非 5060 端口；fail2ban 用自带 asterisk 过滤器读 security 日志（`InvalidPassword`、`InvalidAccountID`、`ChallengeResponseFailed` 等），10 分钟 5 次失败封该 IP 全部端口 1 小时，重犯翻倍（最长 1 周）；可选 `SIP_ALLOW_CIDR` 白名单；`max_contacts=1` 并替换旧注册 |
| 管理接口暴露 | `modules.conf` 白名单加载（`autoload=no`）；AMI、ARI、内置 HTTP 全部 `enabled=no`；容器内只剩 Unix 控制套接字；`disable_remote_console_shell`、`live_dangerously=no` |
| 并发和话费 | `SIP_MAX_CALLS`（默认 1，超出 486）、`maxcalls`、`TIMEOUT(absolute)` = `VOICE_MAX_MINUTES` + 30 秒；voice 侧的每日预算、并发、时长、静默护栏同样生效 |
| token 泄露 | Asterisk 用 HTTP Basic 头带 `VOICE_TELEPHONY_TOKEN`，不放进 URL（不会进访问日志）；只连 `127.0.0.1`（entrypoint 拒绝其他地址）；Caddy 对公网屏蔽 `/telephony/asterisk-ws*` |
| 容器权限 | 不读整份 `.env`（拿不到 DashScope Key）；`cap_drop: ALL` 只补回改属主/降权所需的 5 项能力，`no-new-privileges`，Asterisk 以 `asterisk` 用户运行 |

### 10.8 本地验证记录（2026-10-18）

在开发机上用 Docker 起 `sip` 容器（与 compose 同一镜像和配置），命令行 SIP 客户端 baresip（播放 `scammer16k.wav`、录下机器人声音）与 sipp（异常用例）：

| 用例 | 结果 |
|---|---|
| 正确账号注册 | 200 OK |
| 拨 9000（Opus 宽带），真实 DashScope | 接通；AI 播开场白，ASR 识别出“淘宝客服 / 双倍理赔 / 下载理赔 app”，3 轮回复，端到端回复延迟 3.3–4.5 秒；机器人语音回到客户端 |
| 拨 9000（只开 PCMU 窄带），真实 DashScope | 接通，2 轮回复，识别正常，端到端 3.1–3.3 秒 |
| 拨 9000，回声管线（不调 API） | 客户端收到的回声与原音相关系数 0.99，往返约 0.37 秒 |
| 未认证 / 匿名 INVITE、错误密码、不存在的账号 | 始终 401，未进入拨号计划，voice 没有收到连接 |
| 正确账号拨 1234、110、13800000000、+8613800000000、9001 | 404 |
| 已有一路通话时再拨 | 486 Busy |
| `SIP_ALLOW_CIDR` 不包含来源 IP | 403 |
| voice 未启动 | 503 |
| `SIP_TCP=1` | TCP 注册 200 OK |
| fail2ban（dummy 动作） | 7 条失败记录被识别，触发封禁 |
| 缺密码、密码太短、没开电话入口等 17 种错误配置 | 容器拒绝启动（退出码 64），不打印密码 |

未在真实服务器和真实手机上验证（负责人部署后按下一节检查）：公网 NAT 下的双向音频、运营商网络下的注册保持、Linphone/Zoiper 实机。

### 10.9 部署后自检

1. `docker compose --profile sip ps`：`sip` 为 `Up (healthy)`；`docker compose logs sip | grep deepsuck-sip` 能看到“分机账号 …，AI 分机 9000；SIP UDP 端口 25060 …，公网 IP x.x.x.x”。
2. `docker compose exec sip asterisk -rx "pjsip show endpoints"`：只有一个端点；手机注册后 `pjsip show contacts` 出现一条 Contact。
3. `ss -lntup | grep -E '25060|5038|8088'`：只有 UDP 25060（`SIP_TCP=1` 时多一个 TCP 25060），没有 5038/8088。
4. 手机拨 9000：听到开场白、说话后有回复；`docker compose logs voice | grep "phone call ended"` 有一条 `provider=asterisk-ws` 记录。
5. 手机拨 1234：立即失败（404）。在 Linphone 里故意输错密码：注册失败；连续 5 次后 `fail2ban-client status deepsuck-sip` 能看到该 IP，再解封。
6. 网页语音照常可用（`VOICE_UDP_PORTS` 已改为 40000–40099）。

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
- [S1] Asterisk WebSocket 通道驱动（chan_websocket）：https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/
- [S2] Asterisk res_websocket_client 配置：https://docs.asterisk.org/Latest_API/API_Documentation/Module_Configuration/res_websocket_client/
- [S3] andrius/asterisk 镜像：https://github.com/andrius/asterisk
- [S4] amigniter/mod_audio_stream（开源版与商业版功能说明）：https://github.com/amigniter/mod_audio_stream
