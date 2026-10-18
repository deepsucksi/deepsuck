"""Asterisk chan_websocket 适配器（name = "asterisk-ws"）。

用于 deploy/ 的自建 SIP 软电话 profile（docs/PHONE.md「自建 SIP 软电话接入」）：手机 SIP 软电话
→ Asterisk 22（PJSIP）→ 拨号计划 Dial(WebSocket/deepsuck/c(slin16)f(json)) → Asterisk 作为 WebSocket
客户端连到 voice 服务的 WS /telephony/asterisk-ws（HTTP Basic，密码 = VOICE_TELEPHONY_TOKEN）。Asterisk 负责 SIP、RTP、抖动缓冲、编解码
（G.722/PCMU/PCMA ↔ slin16）与 20 ms 重新定时，本适配器不需要懂 SIP。

协议（Asterisk 22.8+ 的 JSON 控制格式；官方文档 Configuration/Channel-Drivers/WebSocket）：

  Asterisk → DeepSuck
    文本  {"event":"MEDIA_START","connection_id":"...","channel":"WebSocket/...","channel_id":"...",
           "format":"slin16|slin|ulaw|alaw","optimal_frame_size":640,"ptime":20,"channel_variables":{...}}
          第一条消息；拨号计划用 Set(__DS_FROM=...) 设的变量在 channel_variables 里是 "__DS_FROM"
    二进制 原始音频（无 RTP 头），格式同 MEDIA_START.format
    文本  {"event":"DTMF_END","digit":"5"} / MEDIA_XOFF / MEDIA_XON / STATUS / ...
    关闭  主叫挂机时 Asterisk 关闭 WebSocket

  DeepSuck → Asterisk
    二进制 机器人音频；按 optimal_frame_size 的整数倍发送（零头留到下一包），Asterisk 负责 20 ms 定时
    文本  {"command":"FLUSH_MEDIA"}   打断：丢弃 Asterisk 里尚未播放的音频
    文本  {"command":"HANGUP"}        挂断（通话结束 / 护栏触发）

编解码与重采样复用 ws-raw 的 RawStreamSerializer（G.711 8 kHz / L16 8k、16k）。
"""
from __future__ import annotations

import json
from typing import Optional

from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.frames.frames import CancelFrame, EndFrame, Frame, InputDTMFFrame, InterruptionFrame, OutputAudioRawFrame

from .base import CallInfo, TelephonyAdapter, register_adapter
from .ws_raw import MAX_HANDSHAKE_BYTES, RawStreamSerializer

# Asterisk format 名 → (CallInfo.encoding, 采样率)
FORMATS = {"ulaw": ("pcmu", 8000), "alaw": ("pcma", 8000), "slin": ("l16", 8000), "slin16": ("l16", 16000)}
# 主叫信息由拨号计划用 __DS_* 可继承变量带到 WebSocket 通道上（channel_variables 只在 JSON 格式里有）
VAR_FROM, VAR_TO = "DS_FROM", "DS_EXTEN"
MAX_FRAME_BYTES = 65500  # chan_websocket 单条消息上限，超过会被挂断


def parse_media_start(raw) -> CallInfo:
    """解析 chan_websocket 的 MEDIA_START（JSON；兼容旧的 plain-text 单行格式）。不合法抛 ValueError。"""
    if not isinstance(raw, str) or len(raw) > MAX_HANDSHAKE_BYTES:
        raise ValueError("first message must be a MEDIA_START text event")
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            msg = json.loads(raw)
        except ValueError:
            raise ValueError("MEDIA_START is not valid JSON") from None
        if not isinstance(msg, dict) or msg.get("event") != "MEDIA_START":
            raise ValueError("first message must be MEDIA_START")
    else:  # MEDIA_START connection_id:... channel:... format:ulaw optimal_frame_size:160 ptime:20
        head, *parts = raw.split()
        if head != "MEDIA_START":
            raise ValueError("first message must be MEDIA_START")
        msg = dict(p.split(":", 1) for p in parts if ":" in p)
    fmt = str(msg.get("format") or "").lower()
    if fmt not in FORMATS:
        raise ValueError(f"unsupported chan_websocket format: {fmt or '?'}（拨号计划用 c(slin16)/c(ulaw)/c(alaw)）")
    encoding, rate = FORMATS[fmt]
    call_id = str(msg.get("channel_id") or msg.get("connection_id") or "").strip()
    if not call_id:
        raise ValueError("MEDIA_START missing channel_id/connection_id")
    try:
        frame = int(msg.get("optimal_frame_size") or 0)
    except (TypeError, ValueError):
        frame = 0
    if not 0 < frame <= MAX_FRAME_BYTES:
        frame = rate // 50 * (1 if encoding != "l16" else 2)  # 20 ms
    variables = msg.get("channel_variables") if isinstance(msg.get("channel_variables"), dict) else {}

    def var(name: str) -> str:  # 可继承变量在 channel_variables 里带着 _ / __ 前缀
        for k in (name, "_" + name, "__" + name):
            if variables.get(k):
                return str(variables[k])[:64]
        return ""

    return CallInfo(provider="asterisk-ws", call_id=call_id, stream_id=str(msg.get("connection_id") or call_id),
                    from_number=var(VAR_FROM), to_number=var(VAR_TO),
                    encoding=encoding, sample_rate=rate,
                    extra={"format": fmt, "optimal_frame_size": frame, "channel": str(msg.get("channel") or "")})


class AsteriskWebSocketSerializer(RawStreamSerializer):
    """chan_websocket ↔ Pipecat 帧。音频编解码沿用 ws-raw；控制消息换成 chan_websocket 的 JSON 命令。"""

    def __init__(self, call: CallInfo, params: Optional[RawStreamSerializer.InputParams] = None):
        super().__init__(call, params)
        self._frame = int(call.extra.get("optimal_frame_size") or 0) or 160
        self._pending = bytearray()

    async def serialize(self, frame: Frame):
        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._hangup_sent:
                return None
            self._hangup_sent = True
            self._pending.clear()
            return json.dumps({"command": "HANGUP"})
        if isinstance(frame, InterruptionFrame):
            self._pending.clear()
            return json.dumps({"command": "FLUSH_MEDIA"})
        if isinstance(frame, OutputAudioRawFrame):
            out = await super().serialize(frame)
            if not out:
                return None
            # 只发 optimal_frame_size 的整数倍：零头会被 Asterisk 丢掉，留到下一包拼整
            self._pending.extend(out)
            n = min(len(self._pending) // self._frame * self._frame, MAX_FRAME_BYTES // self._frame * self._frame)
            if n <= 0:
                return None
            chunk = bytes(self._pending[:n])
            del self._pending[:n]
            return chunk
        return None

    async def deserialize(self, data):
        if isinstance(data, (bytes, bytearray)):
            return await super().deserialize(data)
        try:
            msg = json.loads(data)
        except (TypeError, ValueError):
            return None
        if isinstance(msg, dict) and msg.get("event") == "DTMF_END":
            try:
                return InputDTMFFrame(KeypadEntry(str(msg.get("digit", ""))))
            except ValueError:
                return None
        return None  # MEDIA_XOFF/XON/STATUS 等：Pipecat 按实时节奏发送，队列不会接近上限


@register_adapter
class AsteriskWebSocketAdapter(TelephonyAdapter):
    name = "asterisk-ws"
    description = "自建 Asterisk 22（chan_websocket，JSON 控制格式）：手机 SIP 软电话 → 分机 → AI"

    async def accept(self, websocket) -> CallInfo:
        msg = await websocket.receive()
        if msg.get("type") == "websocket.disconnect":
            raise ValueError("websocket closed before MEDIA_START")
        return parse_media_start(msg.get("text"))

    def create_serializer(self, call: CallInfo) -> AsteriskWebSocketSerializer:
        return AsteriskWebSocketSerializer(call)
