# DeepSuck 语音演示（voice/）

> 非官方项目，与 DeepSeek 无关。仅供防诈研究与教育：**只在浏览器里自己扮演骗子**，不要接入电话网络、不要拨打或接听任何真实号码。

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
| `services.py` | Pipecat 自定义服务 `ParaformerSTTService`、`CosyVoiceTTSService` |
| `processors.py` | `IntelProcessor`（情报/话术/策略/填充音）、`BotTextTap`、`GuardTextFilter` |
| `persona.py` | 由 `site/assets/core/personas.json` 生成系统提示词；填充音台词；输出守卫 |
| `app.py` | FastAPI + SmallWebRTC 信令（`/api/offer`）+ 管线组装；`python -m voice.app` |
| `static/` | 浏览器端（原生 WebRTC，无构建步骤） |
| `smoke.py` | `python -m voice.smoke --out x.wav`：真实调用 qwen-plus → CosyVoice → Paraformer 的冒烟测试 |

人设音色：王阿姨 `longlaoyi_v3`（龙老姨），李大爷 `longlaobo_v3`（龙老伯），小林 `longanyang`。

## 隐私与安全

- 交给大模型的只有**脱敏后**的转写文本；卡号等原值只在本进程内存里用于黑名单比对，不写盘、不上报。
- 浏览器看板只收到脱敏值。音频不落盘（填充音缓存在 `~/.cache/deepsuck/voice/`，只是机器人自己的台词）。
- 输出守卫会去掉括号动作 / Markdown，抹掉 5 位以上数字串，防止机器人编造"验证码""卡号"。
- 黑名单比对默认读 `https://deepsuck.si/data/blocklist/`（destroylist、Phishing.Database、OFAC 等，见 `docs/INTEL.md`）。

## 测试

```bash
pip install -r voice/requirements.txt
python -m pytest voice/tests -q    # 全部用假 WebSocket，不联网、不需要 key
```

## 已知限制

- Paraformer 的数字规整（ITN）有时会把"张三"转成"张3"，导致姓名抽取漏掉。
- 打断（barge-in）依赖 Silero VAD 与 Pipecat 默认轮次策略，没有针对老人人设专门调过。
- 只在 Linux + Chrome（伪造麦克风输入）下做过端到端测试；真实麦克风、回声消除、移动端浏览器未测。
- 使用 Pipecat 1.12 的 `PipelineTask` / 上下文内 system 消息（2.0 将移除），已在 requirements 中锁 `<2`。
