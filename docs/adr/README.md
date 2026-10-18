# 架构决策记录（ADR）

每条记录一个已做出的关键决策：背景、决策、后果。决策变化时新增一条并把旧条标为“已被 000X 取代”，不改写历史。

| 编号 | 标题 | 状态 |
|---|---|---|
| [0001](0001-shared-core-json.md) | 共享 core JSON 作为 JS 与 Python 的单一事实来源 | 已采纳 |
| [0002](0002-pipecat-voice-stack.md) | 语音栈：Pipecat + Paraformer + qwen-plus + CosyVoice + SmallWebRTC | 已采纳 |
| [0003](0003-redact-before-storage.md) | 先脱敏再存储与展示 | 已采纳 |
| [0004](0004-pages-plus-single-vps.md) | 静态站点放 GitHub Pages，实时服务放单台 VPS | 已采纳 |

新增模板：`000N-简短英文名.md`，包含“状态 / 背景 / 决策 / 后果”四节，控制在一屏内。
