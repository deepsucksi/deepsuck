"""电话接入适配器基类与注册表。

一个 TelephonyAdapter 负责一类来电接入方式：
  1. accept()：读握手消息，得到 CallInfo（主被叫、通话 ID、编码、采样率）；
  2. create_serializer()：返回 Pipecat FrameSerializer，负责媒体流编解码
     （8 kHz μ-law / A-law / L16 ↔ 管线 16 kHz PCM 重采样）、DTMF → InputDTMFFrame、
     EndFrame → 挂断、InterruptionFrame → 清空对端播放缓冲；
  3. create_transport()：默认用 Pipecat 自带的 FastAPIWebsocketTransport 包起来；
  4. hangup()：可选，走服务商 REST/信令主动挂断（serializer 未能处理时兜底）。

适配器只管“电话 ↔ Pipecat 帧”，不碰 ASR/LLM/TTS 与 DeepSuck 情报逻辑。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Type

ENCODINGS = ("pcmu", "pcma", "l16")


@dataclass
class CallInfo:
    """一通来电的元数据（号码只在本进程内存里使用；对外展示前需脱敏）。"""
    provider: str
    call_id: str
    stream_id: str = ""
    from_number: str = ""
    to_number: str = ""
    encoding: str = "pcmu"         # pcmu(μ-law) / pcma(A-law) / l16(16-bit 线性 PCM)
    sample_rate: int = 8000        # 电话侧采样率，常见 8000；L16 也可能是 16000
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.encoding = (self.encoding or "pcmu").lower()
        if self.encoding in ("ulaw", "mulaw", "g711u", "audio/x-mulaw"):
            self.encoding = "pcmu"
        elif self.encoding in ("alaw", "g711a", "audio/x-alaw"):
            self.encoding = "pcma"
        elif self.encoding in ("linear16", "pcm", "slin", "slin16"):
            self.encoding = "l16"
        if self.encoding not in ENCODINGS:
            raise ValueError(f"unsupported encoding: {self.encoding}")
        self.sample_rate = int(self.sample_rate or 8000)


class TelephonyAdapter(ABC):
    """电话接入适配器。子类设置 name 并用 @register_adapter 注册。"""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    @abstractmethod
    async def accept(self, websocket) -> CallInfo:
        """读取握手消息（已 accept 的 FastAPI WebSocket），返回 CallInfo；格式不对抛 ValueError。"""

    @abstractmethod
    def create_serializer(self, call: CallInfo):
        """返回 pipecat FrameSerializer。"""

    def create_transport(self, websocket, call: CallInfo, *, session_timeout: Optional[float] = None):
        """默认：FastAPIWebsocketTransport + 本适配器的 serializer。采样率由 PipelineParams 决定。"""
        from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

        params = FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False,
                                        serializer=self.create_serializer(call), session_timeout=session_timeout)
        return FastAPIWebsocketTransport(websocket=websocket, params=params)

    async def hangup(self, call: CallInfo) -> None:  # pragma: no cover - 默认交给 serializer
        """主动挂断兜底；默认什么都不做（serializer 在 EndFrame 时处理）。"""
        return None


_REGISTRY: Dict[str, Type[TelephonyAdapter]] = {}


def register_adapter(cls: Type[TelephonyAdapter]) -> Type[TelephonyAdapter]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} 没有 name")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"adapter name already registered: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get_adapter(name: str, **kwargs) -> TelephonyAdapter:
    try:
        return _REGISTRY[name](**kwargs)
    except KeyError:
        raise KeyError(f"unknown telephony adapter: {name}（可用：{', '.join(list_adapters())}）") from None


def list_adapters() -> List[str]:
    return sorted(_REGISTRY)
