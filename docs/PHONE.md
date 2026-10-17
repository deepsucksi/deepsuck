# DeepSuck 电话接入方案（v0.3 规划，写给爱折腾的技术玩家）

> **非官方项目，与 DeepSeek 无关。** 本文是路线图设计稿，代码尚未实现；欢迎在 Issue 里认领、实测和反馈。
> 价格为 2026-10 公开目录价，落地前请自行核对。标注“需实测”的地方是推断或社区经验，不是官方承诺。

目标：**把打到你手机上的陌生/诈骗电话，自动交给 AI 人设（王阿姨、李大爷……）接听**，拖住骗子，并像文字沙盒一样实时提取情报、默认脱敏。

```
诈骗来电 ──► 你的 iPhone 主号
               │ 联系人：正常响铃
               │ 陌生号：iOS 静音 → 无应答 → 运营商呼叫转移（**61*）
               ▼
          你本人实名的第二张 SIM（副卡）
               │
               ▼
   EC20 / EG25 4G 模组（USB：AT 指令 + UAC 声卡，8 kHz PCM）
               │
               ▼
   DeepSuck voice（Python · Pipecat 级联管线）
   VAD → Paraformer 实时 ASR → 拖延策略 + qwen-plus/turbo → CosyVoice TTS
               │
               └─► 转写 → DeepSuck core（同一套 core/*.json 规则：提取 / 话术 / 脱敏）→ 情报看板 / JSON / 情报库提交
```

---

## 0. 里程碑

| 阶段 | 内容 | 需要硬件？ |
|---|---|---|
| **V1 浏览器语音 Demo（第一步）** | 在网页里用麦克风扮演骗子，AI 阿姨/大爷用语音回你；Pipecat SmallWebRTC transport | ❌ 不需要，只要百炼 Key |
| V2 拖延策略层 | 把现有 20+ 种拖延意图映射为 Pipecat Flows 节点和“插播音频”（咳嗽、电视声、“喂？喂？听不清”、长时间沉默）；预合成音频缓存 | ❌ |
| V3 EC20 直连接电话 | AT 状态机（RING → ATA，`AT+CLCC` 取来电号码）+ UAC 音频桥，包装成 Pipecat transport | ✅ 一块 EC20/EG25 + 副卡 |
| V4 短信诱骗通道 | 旧安卓机装 SmsForwarder，把诈骗短信 webhook 给 DeepSuck，用文字引擎处理 | ✅ 一台旧安卓机 |
| V5（可选）多线路 | Asterisk + chan_quectel + `pipecat-asterisk` | ✅ 多块模组 |

---

## 1. iPhone 侧：只把“陌生来电”转出去

iOS 不允许第三方 App 接听或转接蜂窝来电（CallKit 在中国区也被禁用），所以只能靠**运营商呼叫转移**。运营商不区分号码，下面这套组合可以*近似*做到“只转陌生号”（**需实测**）：

1. 设置 → App → 电话 → **筛选未知来电 → 静音**；
2. **关闭「实时语音留言」**（否则 iPhone 本机会先应答，网络认为已接通，无应答转移不会触发）；
3. 在拨号盘输入 `**61*副卡号码#` 并拨出（无应答转移），可加 `**62*副卡号码#`（关机/无信号时也转）；
4. 输入 `*#61#` 查询是否生效，然后用一个不在通讯录里的号码实测。

| 操作 | 无应答 | 不可及 | 无条件 | 全部取消 |
|---|---|---|---|---|
| 设置 | `**61*号码#` | `**62*号码#` | `**21*号码#` | `##002#` |
| 取消 | `##61#` | `##62#` | `##21#` | |

注意：
- 联系人的**未接**来电也会被转走。AI 侧需要维护白名单，识别到熟人时礼貌结束并通知你；
- 骗子要先等十几秒（无应答超时），有的会挂断；
- 省事的替代做法：把副卡号码当作“对外泄露号”（注册网站、填快递），对它设**无条件转移**；
- 被叫方（副卡）通常能看到原始主叫号码，所以 AI 能拿到诈骗号码。

---

## 2. 硬件：EC20 / EG25 4G 模组（默认方案）

**为什么不用 Asterisk 作为默认方案**：单卡自用时，直接用 AT 指令控制模组，再通过 USB 声卡（UAC）读写 8 kHz PCM 就够了，少一整套 PBX。[tianye1999/callpilot](https://github.com/tianye1999/callpilot)（Apache-2.0）已经把 EC20 的 AT 状态机、UAC 音频桥和 DTMF 打通。DeepSuck 计划**复用它的硬件层模块**（以依赖或 vendoring 的方式引入并保留 NOTICE），把它们包装成 Pipecat transport，同时向上游贡献 Linux 实测。

| 物品 | 参考价 | 说明 |
|---|---|---|
| Quectel EC20 / EG25 USB 模组（带 UAC 语音固件，如 EC20CEFAG 系列） | ¥100–250 | 必须支持 **VoLTE**：国内 2G/3G 逐步退网后，通话依赖 VoLTE（**需按运营商实测**） |
| 天线 + USB 转接板 | ¥20–50 | |
| 副卡（**本人实名**，最低月租档） | ¥8–20/月 | 被叫免费 |
| 运行机器：树莓派 4/5、旧笔记本、NAS 或家用小主机 | 已有 / ¥0 | Linux 优先；只需出网访问百炼 |

关键 AT 指令：`ATA` 接听、`ATH` 挂断、`AT+CLCC` 当前通话（含来电号码）、`AT+QPCMV=1,2` 打开 USB 语音（UAC）、`AT+QTONEDET` / `AT+VTS` DTMF。具体以模组固件手册为准。

**旧安卓手机不能用来接电话**：Android 10 起，普通 App 拿不到通话的双向音频（`VOICE_CALL` 等音源只开放给系统应用），只能开免提靠麦克风“声学耦合”，效果和稳定性都很差。旧安卓机更适合做**短信通道**（见第 5 节）。

**多线路（可选）**：需要接多张卡或想用 SIP 软电话测试时，再上 Asterisk 22/23 + [chan_quectel](https://github.com/IchthysMaranatha/asterisk-chan-quectel) + chan_websocket，用 [pipecat-asterisk](https://github.com/NikolayShakin/pipecat-asterisk)（BSD-2）把通话接到同一条 Pipecat 管线。Asterisk 作为独立进程运行，与 DeepSuck 代码之间只有网络接口。

---

## 3. 语音管线：Pipecat 级联（DashScope 一个 Key 搞定）

框架选 [Pipecat](https://github.com/pipecat-ai/pipecat)（BSD-2-Clause，纯 Python，`pip install` 即可）。原因：许可证与 Apache-2.0 兼容；帧级流水线方便插入“拖延音频”；Pipecat Flows 适合编排拖延状态机；有浏览器（SmallWebRTC）和 Asterisk transport。

| 环节 | 默认 | 备选 |
|---|---|---|
| VAD | Silero（Pipecat 内置） | — |
| ASR | **DashScope Paraformer 实时**（`paraformer-realtime-v2`，WebSocket 流式） | 本地 FunASR / SenseVoice（免 Key） |
| 策略 + 回复 | DeepSuck 拖延策略层 → **qwen-plus / qwen-turbo**（OpenAI 兼容） | 任意国产 OpenAI 兼容模型 |
| 输出守卫 | 规则过滤：不说出任何数字串、验证码、卡号；不答应转账 | — |
| TTS | **DashScope CosyVoice 流式**（可做“老人音色”声音复刻） | 本地 CosyVoice 预合成拖延台词 |
| 极速模式（可选） | **Qwen-Omni Realtime** 端到端语音（延迟更低，音色和插播控制较弱） | — |

Pipecat 目前没有现成的 Paraformer 和 CosyVoice 服务，需要自己写两个 service（各约 200 行），写好后计划回馈上游。

**延迟**：级联首音约 1–1.5 秒。对“慢吞吞的老人”人设这反而是优点，可以用“嗯……”“啊？”等填充音掩盖。

**零成本兜底**（借鉴经典的 Lenny 机器人）：LLM 或网络不可用时，退化为“对方一停顿就播下一句预合成台词”的循环模式。台词音频用 CosyVoice 自己合成，**不使用 Lenny 原音频**（版权不明）。

---

## 4. 成本估算（阿里云百炼，北京地域原价）

| 项目 | 单价 | 每通话分钟 |
|---|---|---|
| Paraformer 实时 ASR | 0.00024 元/秒 | ≈ 0.014 元 |
| CosyVoice TTS（v3.5-flash） | 0.8 元/万字符（1 汉字 = 2 字符） | 每分钟约 100 字 ≈ 0.016 元 |
| qwen-plus | 输入 0.0008 / 输出 0.002 元/千 token | ≈ 0.015 元（qwen-turbo 更便宜） |
| 运营商呼转费（主号扣费） | 本地约 0.1 元/分钟 | **0.1 元** |
| 合计 | | **≈ 0.15 元/分钟** |

固定成本：副卡月租约 8–20 元；机器用家里已有的设备即可。成本大头是呼转费而不是 AI；个人每月的诈骗/营销来电通常只有几十分钟。百炼新用户一般有免费额度，**建议在控制台设置费用告警**。

---

## 5. 短信诱骗通道（旧安卓机的正确用途）

旧安卓机插上副卡，安装 [SmsForwarder](https://github.com/pppscn/SmsForwarder)（BSD-2），把收到的短信转发到 DeepSuck 的 webhook（计划中的 `POST /api/sms`）：

- 自动提取短信里的网址、电话、APP 名称、收款账户与话术，进入情报看板；
- 后续可选：通过 [android-sms-gateway](https://github.com/capcom6/android-sms-gateway)（Apache-2.0）以人设口吻回复**主动找上门的**诈骗短信。默认关闭，且永远不向未主动联系你的号码发送短信。

---

## 6. 合规边界（简版）

- **单卡、本人实名、只接不拨**：不实现外呼、群呼、改主叫号码，不支持多卡池（《反电信网络诈骗法》第十四条严禁猫池、GOIP、违规 VoIP 接入）；
- 接听开场提示“本通话由智能助理接听并可能录音”；单通设时长上限；对方要求挂断就挂断；
- 录音和转写默认只存本地，设留存期限（如 30 天），对外只发布按[情报库发布策略](INTEL.md)处理过的指标；原始证据交给 110 / 96110 / 国家反诈中心 App；
- 人设不冒充真实机构或真实个人，不给出任何真实账户或验证码。

---

## 7. 待验证 / 求助

- [ ] EC20/EG25 各型号 × 移动/联通/电信 的 VoLTE 通话兼容性表（欢迎提交实测）
- [ ] iPhone“静音未知来电 + 关闭实时语音留言 + `**61*`”组合在各运营商的实际效果与无应答时长
- [ ] Paraformer / CosyVoice 的 Pipecat service 实现
- [ ] CallPilot 硬件层在 Linux（树莓派）上的实测

相关开源项目见 [README「致谢 / Prior art」](../README.md#-致谢--prior-art)。
