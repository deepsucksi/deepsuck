"""DashScope 的 Pipecat 自定义服务：Paraformer 实时识别（STT）与 CosyVoice 合成（TTS）。

两者都走 DashScope 的 WebSocket 协议（见 dashscope_ws.py），不依赖 dashscope SDK。
需要环境变量 DASHSCOPE_API_KEY。
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService, WebsocketTTSService
from pipecat.utils.time import time_now_iso8601

from . import dashscope_ws as ds
from .persona import pause_range, split_pause
from .textagg import ClauseTextAggregator


def pause_silence(sample_rate: int, rng=random) -> bytes:
    """一段随机时长的静音 PCM（断续停顿用）；范围见 persona.pause_range。"""
    lo, hi = pause_range()
    ms = rng.randint(lo, hi) if hi > 0 else 0
    return b"\x00\x00" * int(sample_rate * ms / 1000)


@dataclass
class ParaformerSTTSettings(STTSettings):
    """Paraformer 设置（model 例：paraformer-realtime-v2）。"""


class ParaformerSTTService(STTService):
    """把麦克风 PCM 持续推给 Paraformer 实时识别，句末推 TranscriptionFrame，中间结果推 InterimTranscriptionFrame。"""

    Settings = ParaformerSTTSettings
    _settings: Settings

    def __init__(self, *, model: str = "paraformer-realtime-v2", key: Optional[str] = None,
                 connect=None, sample_rate: int = 16000, meter=None,
                 max_sentence_silence: Optional[int] = None, **kwargs):
        super().__init__(sample_rate=sample_rate,
                         settings=self.Settings(model=model, language="zh"), **kwargs)
        self._key, self._connect = key, connect
        self._max_silence = max_sentence_silence
        self._meter = meter  # voice.guard.Ticket：按发送的音频秒数记账（Paraformer 按音频时长计费）
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
                                         key=self._key, connect=self._connect,
                                         max_sentence_silence=self._max_silence)
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
                if self._meter is not None:
                    self._meter.asr(len(audio) / (2.0 * (self.sample_rate or 16000)))
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
                 rate: float = 1.0, key: Optional[str] = None, connect=None, meter=None,
                 instruction: Optional[str] = None, **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True,
                         settings=self.Settings(model=model, voice=voice, language="zh"), **kwargs)
        self._rate, self._key, self._connect = rate, key, connect
        self._instruction = instruction  # 设计音色的合成指令（例如方言），系统音色传 None
        self._meter = meter  # 按字符记账（CosyVoice 按字符计费）

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        sr = self.sample_rate
        text, pause = split_pause(text)
        try:
            if not text:
                return
            await self.start_tts_usage_metrics(text)
            if self._meter is not None:
                self._meter.tts(len(text))
            pcm = ds.synthesize(text, voice=self._settings.voice, model=self._settings.model,
                                sample_rate=sr, rate=self._rate, key=self._key, connect=self._connect,
                                instruction=self._instruction)
            async for frame in self._stream_audio_frames_from_iterator(pcm, in_sample_rate=sr,
                                                                       context_id=context_id):
                await self.stop_ttfb_metrics()
                yield frame
            gap = pause_silence(sr) if pause else b""
            if gap:
                yield TTSAudioRawFrame(audio=gap, sample_rate=sr, num_channels=1, context_id=context_id)
        except Exception as e:
            logger.error(f"{self}: CosyVoice 合成失败: {e}")
            yield ErrorFrame(error=f"CosyVoice 合成失败: {e}")
            yield TTSStoppedFrame(context_id=context_id)
        finally:
            await self.stop_ttfb_metrics()


class CosyVoiceStreamTTSService(WebsocketTTSService):
    """CosyVoice 双向流式合成：每通会话一条长连接，每个 LLM 回合一个 DashScope 任务。

    - start() 时就建连，省掉每句话的 TLS 握手；
    - 回合开始（LLMFullResponseStartFrame / TTSSpeakFrame）时预先发 run-task，
      LLM 首个分句到达后直接 continue-task，边吐字边合成；
    - 回合结束 flush_audio() 发 finish-task，task-finished 时补 TTSStoppedFrame；
    - 打断时若任务还在合成就断开重连（DashScope 没有取消指令，断连即中止计费的合成），
      已合成完、只剩本地播放的回合则只清本地队列，不重连。
    同一连接同一时刻只能跑一个任务：新回合会等上一个任务结束（最多 task_wait_secs）。
    """

    Settings = CosyVoiceTTSSettings
    _settings: Settings

    def __init__(self, *, voice: str = "longlaoyi_v3", model: str = "cosyvoice-v3-flash",
                 rate: float = 1.0, key: Optional[str] = None, connect=None, meter=None,
                 clause_min_chars: int = 6, task_wait_secs: float = 10.0, instruction: Optional[str] = None,
                 **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True,
                         settings=self.Settings(model=model, voice=voice, language="zh"), **kwargs)
        self._rate, self._key, self._connect_fn = rate, key, connect
        self._instruction = instruction  # 设计音色的合成指令（例如方言），系统音色传 None
        self._meter = meter
        self._text_aggregator = ClauseTextAggregator(min_clause_chars=clause_min_chars)
        self._task_wait = task_wait_secs
        self._receive_task: Optional[asyncio.Task] = None
        self._task_id: Optional[str] = None     # 当前 DashScope 任务
        self._task_ctx: Optional[str] = None    # 该任务对应的 Pipecat 回合 context_id
        self._task_started = asyncio.Event()
        self._task_done = asyncio.Event()
        self._task_done.set()
        self._finish_sent = False
        self._conn_lock = asyncio.Lock()
        # 断续停顿：分句以「…」结尾时，该句单独成一个任务，合成完插一段静音，回合不结束，下一句再开新任务
        self._pause_task = False                # 当前任务结束后要插静音（不是回合结束）
        self._flush_pending = False             # 停顿任务进行中收到了回合结束
        self._open_ctx: Optional[str] = None    # 停顿后仍未结束的回合
        self.pauses = 0                         # 插入的停顿次数（测试/观测用）
        self.connects = 0                      # 建连次数（测试/观测用）
        self.tasks = 0                         # 发起的合成任务数

    def can_generate_metrics(self) -> bool:
        return True

    # ---- 连接 ----
    async def start(self, frame: StartFrame):
        await super().start(frame)
        try:
            await self._connect()
        except Exception as e:  # 首连失败不致命，首次合成时再连
            logger.warning(f"{self}: CosyVoice 预连接失败: {e}")

    async def _connect(self):
        await super()._connect()
        await self._connect_websocket()
        if self._websocket is not None and self._receive_task is None:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        await super()._disconnect()
        if self._receive_task is not None:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self):
        async with self._conn_lock:
            if self._websocket is not None:
                return
            fn = self._connect_fn or ds._connect
            self._websocket = await fn(self._key or ds.api_key())
            self.connects += 1

    async def _disconnect_websocket(self):
        ws, self._websocket = self._websocket, None
        self._reset_task()
        self._pause_task = self._flush_pending = False
        self._open_ctx = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    def _reset_task(self):
        self._task_id = self._task_ctx = None
        self._finish_sent = False
        self._task_started.clear()
        self._task_done.set()

    async def _ensure_connected(self):
        if self._websocket is None:
            await self._connect()

    # ---- 任务 ----
    async def _close_open_ctx(self, keep: Optional[str] = None):
        ctx = self._open_ctx
        if ctx is None or ctx == keep:
            return
        self._open_ctx = None
        if self.audio_context_available(ctx):
            await self.append_to_audio_context(ctx, TTSStoppedFrame(context_id=ctx))
            await self.remove_audio_context(ctx)

    async def _open_task(self, context_id: str):
        if self._task_id is not None and self._task_ctx == context_id and not self._finish_sent:
            return
        await self._close_open_ctx(keep=context_id)  # 上一回合以停顿句收尾但没等到 flush：先把它结束掉
        if self._task_id is not None and not self._task_done.is_set():
            try:
                await asyncio.wait_for(self._task_done.wait(), self._task_wait)
            except asyncio.TimeoutError:
                logger.warning(f"{self}: 上一个合成任务未结束，重连")
                await self._disconnect()
        await self._ensure_connected()
        tid = uuid.uuid4().hex
        self._task_id, self._task_ctx, self._finish_sent = tid, context_id, False
        self._task_started.clear()
        self._task_done.clear()
        self.tasks += 1
        await self._websocket.send(json.dumps(ds.run_task_tts(tid, self._settings.model, self._settings.voice,
                                                              self.sample_rate, self._rate,
                                                              instruction=self._instruction)))

    async def on_turn_context_created(self, context_id: str):
        # 回合一开始就发 run-task，与 LLM 首 token 的等待重叠
        try:
            await self._open_task(context_id)
        except Exception as e:
            logger.warning(f"{self}: 预开合成任务失败: {e}")
            await self._disconnect_websocket()

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        text, pause = split_pause(text)
        if not text:
            yield None
            return
        try:
            await self._open_task(context_id)
            await asyncio.wait_for(self._task_started.wait(), 10)
            if self._task_id is None:
                raise RuntimeError("合成任务已失败")
            await self.start_tts_usage_metrics(text)
            if self._meter is not None:
                self._meter.tts(len(text))
            await self._websocket.send(json.dumps(ds.continue_task_text(self._task_id, text)))
            if pause:
                # 这一句合成完就结束任务，task-finished 时插静音；回合继续
                self._pause_task, self._flush_pending, self._finish_sent = True, False, True
                await self._websocket.send(json.dumps(ds.finish_task(self._task_id)))
            yield None
        except Exception as e:
            logger.error(f"{self}: CosyVoice 合成失败: {e}")
            await self._disconnect_websocket()
            yield ErrorFrame(error=f"CosyVoice 合成失败: {e}")
            yield TTSStoppedFrame(context_id=context_id)

    async def flush_audio(self, context_id: Optional[str] = None):
        ctx = context_id or self._task_ctx or self._open_ctx
        if self._pause_task and self._task_id is not None and ctx == self._task_ctx:
            self._flush_pending = True  # 停顿任务还没结束：结束时直接收尾，不再插静音
            return
        if self._task_id is None and ctx is not None and ctx == self._open_ctx:
            self._open_ctx = None  # 回合最后一句是停顿句，任务已结束：在这里补 TTSStoppedFrame
            if self.audio_context_available(ctx):
                await self.append_to_audio_context(ctx, TTSStoppedFrame(context_id=ctx))
                await self.remove_audio_context(ctx)
            return
        if self._task_id is None or ctx != self._task_ctx or self._finish_sent or self._websocket is None:
            return
        self._finish_sent = True
        try:
            await self._websocket.send(json.dumps(ds.finish_task(self._task_id)))
        except Exception as e:
            logger.warning(f"{self}: finish-task 发送失败: {e}")
            await self._disconnect_websocket()

    async def _receive_messages(self):
        async for msg in self._websocket:
            ctx = self._task_ctx
            if isinstance(msg, (bytes, bytearray)):
                if ctx:
                    await self.stop_ttfb_metrics()
                    await self.append_to_audio_context(
                        ctx, TTSAudioRawFrame(audio=bytes(msg), sample_rate=self.sample_rate,
                                              num_channels=1, context_id=ctx))
                continue
            try:
                ev = json.loads(msg)["header"]
            except Exception:
                continue
            if ev.get("task_id") and ev.get("task_id") != self._task_id:
                continue  # 旧任务的残留事件
            name = ev.get("event")
            if name == "task-started":
                self._task_started.set()
            elif name in ("task-finished", "task-failed"):
                if name == "task-failed":
                    logger.error(f"{self}: CosyVoice 任务失败: {ev.get('error_message')}")
                    await self.push_error(error_msg=f"CosyVoice 任务失败: {ev.get('error_message')}")
                pause, self._pause_task = self._pause_task and name == "task-finished", False
                if pause and not self._flush_pending and ctx and self.audio_context_available(ctx):
                    gap = pause_silence(self.sample_rate)
                    if gap:
                        self.pauses += 1
                        await self.append_to_audio_context(
                            ctx, TTSAudioRawFrame(audio=gap, sample_rate=self.sample_rate, num_channels=1,
                                                  context_id=ctx))
                    self._open_ctx = ctx
                elif ctx and self.audio_context_available(ctx):
                    await self.append_to_audio_context(ctx, TTSStoppedFrame(context_id=ctx))
                    await self.remove_audio_context(ctx)
                self._flush_pending = False
                self._reset_task()

    # ---- 打断 ----
    async def _handle_interruption(self, frame: InterruptionFrame, direction: FrameDirection):
        busy = self._task_id is not None and not self._task_done.is_set()
        self._pause_task = self._flush_pending = False
        self._open_ctx = None
        await super()._handle_interruption(frame, direction)
        await self.stop_all_metrics()
        if busy:
            # 服务端还在合成：断开即取消；立刻重连，让下一回合不必再握手
            await self._disconnect()
            try:
                await self._connect()
            except Exception as e:
                logger.warning(f"{self}: 打断后重连失败（下次合成时再连）: {e}")
