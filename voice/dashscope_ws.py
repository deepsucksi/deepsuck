"""DashScope 实时语音 WebSocket 客户端（不依赖 Pipecat，便于单测与复用）。

协议（2026-10 官方文档）：wss://dashscope.aliyuncs.com/api-ws/v1/inference，Header `Authorization: Bearer <key>`；
  run-task → task-started → (continue-task 文本 | 二进制音频)… → finish-task → task-finished / task-failed。
  - Paraformer 实时 ASR：task=asr, function=recognition, model=paraformer-realtime-v2，客户端发 PCM 16k 单声道二进制帧，
    服务端发 result-generated（payload.output.sentence: text / sentence_end）。
  - CosyVoice 流式 TTS：task=tts, function=SpeechSynthesizer, model=cosyvoice-v3-flash，客户端发 continue-task 文本，
    服务端用二进制帧返回音频（format=pcm 时为 16-bit little-endian）。
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional

WS_URL = os.environ.get("DASHSCOPE_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")

# 人设 → CosyVoice 系统音色（cosyvoice-v3-flash；均为北京地域）
PERSONA_VOICES = {
    "wang": "longlaoyi_v3",   # 龙老姨：烟火从容阿姨，60 岁以上
    "li": "longlaobo_v3",     # 龙老伯：沧桑岁月爷，60 岁以上
    "lin": "longanyang",      # 龙安洋：阳光大男孩，20~30 岁
}


class DashScopeError(RuntimeError):
    pass


def api_key() -> str:
    k = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not k:
        raise DashScopeError("缺少 DASHSCOPE_API_KEY（复制 voice/.env.example 为 .env 并填写）")
    return k


async def _connect(key: str, url: str = WS_URL):
    import websockets  # 延迟导入：单测可注入假连接

    headers = {"Authorization": f"Bearer {key}", "user-agent": "deepsuck-voice/0.3", "X-DashScope-DataInspection": "enable"}
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:  # websockets<13
        return await websockets.connect(url, extra_headers=headers, max_size=None)


Connector = Callable[[str], Awaitable]


def _header(action: str, task_id: str) -> dict:
    return {"action": action, "task_id": task_id, "streaming": "duplex"}


def run_task_tts(task_id: str, model: str, voice: str, sample_rate: int, rate: float = 1.0, fmt: str = "pcm") -> dict:
    return {"header": _header("run-task", task_id), "payload": {
        "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer", "model": model,
        "parameters": {"text_type": "PlainText", "voice": voice, "format": fmt, "sample_rate": sample_rate,
                       "volume": 50, "rate": rate, "pitch": 1.0},
        "input": {}}}


def run_task_asr(task_id: str, model: str, sample_rate: int) -> dict:
    return {"header": _header("run-task", task_id), "payload": {
        "task_group": "audio", "task": "asr", "function": "recognition", "model": model,
        "parameters": {"format": "pcm", "sample_rate": sample_rate, "language_hints": ["zh"],
                       "punctuation_prediction_enabled": True, "inverse_text_normalization_enabled": True,
                       "heartbeat": True},
        "input": {}}}


def continue_task_text(task_id: str, text: str) -> dict:
    return {"header": _header("continue-task", task_id), "payload": {"input": {"text": text}}}


def finish_task(task_id: str) -> dict:
    return {"header": _header("finish-task", task_id), "payload": {"input": {}}}


async def _await_started(ws, timeout: float = 10) -> None:
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout)
        if isinstance(msg, (bytes, bytearray)):
            continue
        ev = json.loads(msg)["header"]
        if ev.get("event") == "task-started":
            return
        if ev.get("event") == "task-failed":
            raise DashScopeError(f"{ev.get('error_code')}: {ev.get('error_message')}")


async def synthesize(text: str, voice: str = "longlaoyi_v3", model: str = "cosyvoice-v3-flash",
                     sample_rate: int = 16000, rate: float = 1.0, key: Optional[str] = None,
                     connect: Optional[Connector] = None) -> AsyncIterator[bytes]:
    """CosyVoice 流式合成：逐块产出 16-bit PCM。"""
    ws = await (connect or _connect)(key or api_key())
    task_id = uuid.uuid4().hex
    try:
        await ws.send(json.dumps(run_task_tts(task_id, model, voice, sample_rate, rate)))
        await _await_started(ws)
        await ws.send(json.dumps(continue_task_text(task_id, text)))
        await ws.send(json.dumps(finish_task(task_id)))
        while True:
            msg = await asyncio.wait_for(ws.recv(), 30)
            if isinstance(msg, (bytes, bytearray)):
                yield bytes(msg)
                continue
            h = json.loads(msg)["header"]
            if h.get("event") == "task-finished":
                return
            if h.get("event") == "task-failed":
                raise DashScopeError(f"{h.get('error_code')}: {h.get('error_message')}")
    finally:
        await ws.close()


@dataclass
class Transcript:
    text: str
    final: bool


class ParaformerStream:
    """Paraformer 实时识别会话：start() → send_audio(pcm)… → finish()；results() 异步产出 Transcript。"""

    def __init__(self, model: str = "paraformer-realtime-v2", sample_rate: int = 16000,
                 key: Optional[str] = None, connect: Optional[Connector] = None):
        self.model, self.sample_rate = model, sample_rate
        self._key, self._connect = key, connect or _connect
        self.task_id = uuid.uuid4().hex
        self.ws = None
        self._q: asyncio.Queue = asyncio.Queue()
        self._reader: Optional[asyncio.Task] = None
        self.finished = asyncio.Event()

    async def start(self) -> None:
        self.ws = await self._connect(self._key or api_key())
        await self.ws.send(json.dumps(run_task_asr(self.task_id, self.model, self.sample_rate)))
        await _await_started(self.ws)
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for msg in self.ws:
                if isinstance(msg, (bytes, bytearray)):
                    continue
                d = json.loads(msg)
                ev = d["header"].get("event")
                if ev == "result-generated":
                    s = d["payload"]["output"].get("sentence") or {}
                    if s.get("heartbeat") or not s.get("text"):
                        continue
                    await self._q.put(Transcript(s["text"], bool(s.get("sentence_end"))))
                elif ev == "task-finished":
                    break
                elif ev == "task-failed":
                    await self._q.put(DashScopeError(f"{d['header'].get('error_code')}: {d['header'].get('error_message')}"))
                    break
        finally:
            self.finished.set()
            await self._q.put(None)

    async def send_audio(self, pcm: bytes) -> None:
        if self.ws is not None and not self.finished.is_set():
            await self.ws.send(pcm)

    async def finish(self, timeout: float = 10) -> None:
        if self.ws is None:
            return
        if not self.finished.is_set():
            await self.ws.send(json.dumps(finish_task(self.task_id)))
            try:
                await asyncio.wait_for(self.finished.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        await self.ws.close()

    async def results(self) -> AsyncIterator[Transcript]:
        while True:
            item = await self._q.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item


async def transcribe_pcm(pcm: bytes, sample_rate: int = 16000, chunk_ms: int = 100, realtime: bool = False,
                         **kw) -> str:
    """便捷函数：把整段 PCM 送去识别，返回拼接的最终文本（用于冒烟测试）。"""
    st = ParaformerStream(sample_rate=sample_rate, **kw)
    await st.start()
    step = sample_rate * 2 * chunk_ms // 1000
    for i in range(0, len(pcm), step):
        await st.send_audio(pcm[i:i + step])
        if realtime:
            await asyncio.sleep(chunk_ms / 1000)
    # 末尾补 0.6 秒静音，帮助断句
    await st.send_audio(b"\x00" * (sample_rate * 2 * 6 // 10))
    finals = []
    fin = asyncio.create_task(st.finish())
    async for t in st.results():
        if t.final:
            finals.append(t.text)
    await fin
    return "".join(finals)
