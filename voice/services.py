"""DashScope 的 Pipecat 自定义服务：Paraformer 实时识别（STT）与 CosyVoice 合成（TTS）。

两者都走 DashScope 的 WebSocket 协议（见 dashscope_ws.py），不依赖 dashscope SDK。
需要环境变量 DASHSCOPE_API_KEY。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    TTSStoppedFrame,
)
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from . import dashscope_ws as ds


@dataclass
class ParaformerSTTSettings(STTSettings):
    """Paraformer 设置（model 例：paraformer-realtime-v2）。"""


class ParaformerSTTService(STTService):
    """把麦克风 PCM 持续推给 Paraformer 实时识别，句末推 TranscriptionFrame，中间结果推 InterimTranscriptionFrame。"""

    Settings = ParaformerSTTSettings
    _settings: Settings

    def __init__(self, *, model: str = "paraformer-realtime-v2", key: Optional[str] = None,
                 connect=None, sample_rate: int = 16000, **kwargs):
        super().__init__(sample_rate=sample_rate,
                         settings=self.Settings(model=model, language="zh"), **kwargs)
        self._key, self._connect = key, connect
        self._stream: Optional[ds.ParaformerStream] = None
        self._reader: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._ensure_stream()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._close()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._close()

    async def _ensure_stream(self) -> bool:
        async with self._lock:
            if self._stream is not None and not self._stream.finished.is_set():
                return True
            try:
                st = ds.ParaformerStream(model=self._settings.model, sample_rate=self.sample_rate,
                                         key=self._key, connect=self._connect)
                await st.start()
            except Exception as e:  # 缺 key、网络错误等
                logger.error(f"{self}: Paraformer 连接失败: {e}")
                await self.push_error(error_msg=f"Paraformer 连接失败: {e}")
                self._stream = None
                return False
            self._stream = st
            self._reader = self.create_task(self._read(st))
            return True

    async def _read(self, st: ds.ParaformerStream):
        try:
            async for t in st.results():
                if t.final:
                    await self.push_frame(TranscriptionFrame(text=t.text, user_id=self._user_id,
                                                             timestamp=time_now_iso8601(), finalized=True))
                else:
                    await self.push_frame(InterimTranscriptionFrame(text=t.text, user_id=self._user_id,
                                                                    timestamp=time_now_iso8601()))
        except Exception as e:
            logger.warning(f"{self}: Paraformer 会话结束: {e}")

    async def _close(self):
        st, self._stream = self._stream, None
        if st is not None:
            try:
                await st.finish(timeout=3)
            except Exception:
                pass
        if self._reader is not None:
            await self.cancel_task(self._reader)
            self._reader = None

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        # 会话超时/断开后在下一块音频时自动重连
        if self._stream is None or self._stream.finished.is_set():
            await self._ensure_stream()
        if self._stream is not None:
            try:
                await self._stream.send_audio(audio)
            except Exception as e:
                logger.warning(f"{self}: 发送音频失败: {e}")
                self._stream = None
        yield None


@dataclass
class CosyVoiceTTSSettings(TTSSettings):
    """CosyVoice 设置（model 例：cosyvoice-v3-flash；voice 例：longlaoyi_v3）。"""


class CosyVoiceTTSService(TTSService):
    """每句话一次 CosyVoice WebSocket 任务，流式返回 PCM。"""

    Settings = CosyVoiceTTSSettings
    _settings: Settings

    def __init__(self, *, voice: str = "longlaoyi_v3", model: str = "cosyvoice-v3-flash",
                 rate: float = 1.0, key: Optional[str] = None, connect=None, **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True,
                         settings=self.Settings(model=model, voice=voice, language="zh"), **kwargs)
        self._rate, self._key, self._connect = rate, key, connect

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        sr = self.sample_rate
        try:
            await self.start_tts_usage_metrics(text)
            pcm = ds.synthesize(text, voice=self._settings.voice, model=self._settings.model,
                                sample_rate=sr, rate=self._rate, key=self._key, connect=self._connect)
            async for frame in self._stream_audio_frames_from_iterator(pcm, in_sample_rate=sr,
                                                                       context_id=context_id):
                await self.stop_ttfb_metrics()
                yield frame
        except Exception as e:
            logger.error(f"{self}: CosyVoice 合成失败: {e}")
            yield ErrorFrame(error=f"CosyVoice 合成失败: {e}")
            yield TTSStoppedFrame(context_id=context_id)
        finally:
            await self.stop_ttfb_metrics()
