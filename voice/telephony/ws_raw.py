"""通用 SIP/WebSocket 媒体流适配器（name = "ws-raw"）。

面向自建 SIP 侧桥接：FreeSWITCH（mod_audio_fork/mod_audio_stream 一类模块或 ESL 小程序）、
Asterisk（AudioSocket / chan_websocket 前置的小网关）、或基于 sipgo/pjsua 的自写 UAS。
桥接程序只需按下面这份极简协议说话，DeepSuck 侧不需要知道 SIP。

协议（一条 WebSocket = 一通电话）：

  桥接 → DeepSuck
    文本  {"event":"start","call_id":"...","from":"138...","to":"...","encoding":"pcmu|pcma|l16","sample_rate":8000}
          必须是第一条消息；encoding 缺省 pcmu，sample_rate 缺省 8000
    二进制 音频负载（与 start 声明的编码/采样率一致，单声道；建议 20 ms 一包：PCMU/PCMA 160 字节，L16@8k 320 字节）
    文本  {"event":"dtmf","digit":"5"}
    文本  {"event":"stop"}   对方挂机；发完后关闭 WebSocket

  DeepSuck → 桥接
    二进制 机器人音频（同一编码/采样率）
    文本  {"event":"clear"}   打断：请丢弃尚未播放的音频
    文本  {"event":"hangup","reason":"..."}   请挂断这通电话（通话结束 / 护栏触发）
"""
from __future__ import annotations

import json
from typing import Optional

from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import alaw_to_pcm, create_stream_resampler, pcm_to_alaw, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

from .base import CallInfo, TelephonyAdapter, register_adapter

MAX_HANDSHAKE_BYTES = 8192


class RawStreamSerializer(FrameSerializer):
    """ws-raw 协议 ↔ Pipecat 帧。编解码与重采样用 Pipecat 自带的 G.711 工具与流式重采样器。"""

    def __init__(self, call: CallInfo, params: Optional[FrameSerializer.InputParams] = None):
        super().__init__(params or FrameSerializer.InputParams(resampler_clear_after_secs=None))
        self.call = call
        self._sample_rate = 0  # 管线输入采样率，setup() 时确定
        self._in_resampler = create_stream_resampler(clear_after_secs=self._params.resampler_clear_after_secs)
        self._out_resampler = create_stream_resampler(clear_after_secs=self._params.resampler_clear_after_secs)
        self._hangup_sent = False

    async def setup(self, setup):
        self._sample_rate = setup.audio_in_sample_rate

    # ---- DeepSuck → 桥接 ----
    async def serialize(self, frame: Frame):
        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._hangup_sent:
                return None
            self._hangup_sent = True
            return json.dumps({"event": "hangup", "reason": "end" if isinstance(frame, EndFrame) else "cancel"})
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"event": "clear"})
        if isinstance(frame, OutputAudioRawFrame):
            rate, enc = self.call.sample_rate, self.call.encoding
            if enc == "pcmu":
                out = await pcm_to_ulaw(frame.audio, frame.sample_rate, rate, self._out_resampler)
            elif enc == "pcma":
                out = await pcm_to_alaw(frame.audio, frame.sample_rate, rate, self._out_resampler)
            else:
                out = await self._out_resampler.resample(frame.audio, frame.sample_rate, rate)
            return bytes(out) if out else None
        return None

    # ---- 桥接 → DeepSuck ----
    async def deserialize(self, data):
        if isinstance(data, (bytes, bytearray)):
            if not data:
                return None
            target = self._sample_rate or 16000
            rate, enc = self.call.sample_rate, self.call.encoding
            if enc == "pcmu":
                pcm = await ulaw_to_pcm(bytes(data), rate, target, self._in_resampler)
            elif enc == "pcma":
                pcm = await alaw_to_pcm(bytes(data), rate, target, self._in_resampler)
            else:
                pcm = await self._in_resampler.resample(bytes(data), rate, target)
            if not pcm:
                return None
            return InputAudioRawFrame(audio=pcm, num_channels=1, sample_rate=target)
        try:
            msg = json.loads(data)
        except (TypeError, ValueError):
            return None
        if isinstance(msg, dict) and msg.get("event") == "dtmf":
            try:
                return InputDTMFFrame(KeypadEntry(str(msg.get("digit", ""))))
            except ValueError:
                return None
        return None  # start/stop/未知事件：stop 之后桥接会关闭连接，由 on_client_disconnected 收尾


def parse_start(raw) -> CallInfo:
    """解析 ws-raw 的 start 消息；不合法抛 ValueError。"""
    if not isinstance(raw, str) or len(raw) > MAX_HANDSHAKE_BYTES:
        raise ValueError("first message must be a JSON text start event")
    try:
        msg = json.loads(raw)
    except ValueError:
        raise ValueError("start event is not valid JSON") from None
    if not isinstance(msg, dict) or msg.get("event") != "start":
        raise ValueError("first message must be {\"event\":\"start\",...}")
    call_id = str(msg.get("call_id") or "").strip()
    if not call_id:
        raise ValueError("start event missing call_id")
    rate = msg.get("sample_rate", 8000)
    if not isinstance(rate, int) or rate not in (8000, 16000):
        raise ValueError("sample_rate must be 8000 or 16000")
    known = {"event", "call_id", "from", "to", "encoding", "sample_rate", "stream_id"}
    return CallInfo(provider="ws-raw", call_id=call_id, stream_id=str(msg.get("stream_id") or call_id),
                    from_number=str(msg.get("from") or ""), to_number=str(msg.get("to") or ""),
                    encoding=str(msg.get("encoding") or "pcmu"), sample_rate=rate,
                    extra={k: v for k, v in msg.items() if k not in known})


@register_adapter
class RawWebSocketAdapter(TelephonyAdapter):
    name = "ws-raw"
    description = "通用 SIP 网关 / FreeSWITCH / Asterisk 桥接（极简 JSON + 二进制 G.711/L16 协议）"

    async def accept(self, websocket) -> CallInfo:
        msg = await websocket.receive()
        if msg.get("type") == "websocket.disconnect":
            raise ValueError("websocket closed before start event")
        return parse_start(msg.get("text"))

    def create_serializer(self, call: CallInfo) -> RawStreamSerializer:
        return RawStreamSerializer(call)
