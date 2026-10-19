# 0002 语音栈：Pipecat + Paraformer + qwen-plus + CosyVoice + SmallWebRTC

状态：已采纳

## 背景

语音演示要在中文电话场景下做到低延迟、可打断，并且同一条管线能接浏览器和电话。团队小，不想自研流式编排。

## 决策

- 编排用 Pipecat（锁定 `>=1.12,<2`）；识别 Paraformer、对话 qwen-plus、合成 CosyVoice，均走阿里云百炼接口（`voice/dashscope_ws.py`、`voice/services.py`）。
- 浏览器用 SmallWebRTC 直连 VPS，不依赖第三方实时音视频服务；UDP 不通时由 coturn 中继（#3）。
- 电话通过 `voice/telephony/` 的适配器（asterisk-ws、ws-raw）接入同一个 `build_pipeline`，网页与电话只在延迟参数上分档（`voice/tuning.py`）。

## 后果

- 中文识别与合成质量好，单一供应商便于记账（`voice/guard.py` 预算护栏）。
- 依赖 Pipecat 的接口演进：当前用到的 `PipelineTask`/`PipelineRunner` 与上下文内 system 消息已弃用，升级 2.0 前必须迁移（#9）。
- SmallWebRTC 在受限网络下连通性差，必须有 TURN 回退与前端失败提示。

2026-10-19 起统一改用 qwen3.8-flash，见 #145。
