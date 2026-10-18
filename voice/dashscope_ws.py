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
import hashlib
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Optional

WS_URL = os.environ.get("DASHSCOPE_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")

# 人设 → CosyVoice 系统音色（cosyvoice-v3-flash；均为北京地域）。开箱即用，任何百炼账号都能合成。
# 小陈妈妈（chen）、郑老板（zheng）暂不配音色：负责人试听通过前退回默认音色（下面 persona_voice 的 longlaoyi_v3），
# 也可以先用 DEEPSUCK_VOICE_CHEN / DEEPSUCK_VOICE_ZHENG 在测试环境试听。建议见 personas.json 的 voiceHint。
PERSONA_VOICES = {
    "wang": "longlaoyi_v3",   # 龙老姨：烟火从容阿姨，60 岁以上
    "lin": "longanyang",       # 龙安洋：阳光大男孩
}
DEFAULT_VOICE = "longlaoyi_v3"

# 声音设计音色（voice-enrollment 生成，ID 形如 cosyvoice-v3.5-flash-vd-xxx）只属于创建它的百炼账号，
# 所以不写死在代码里：用 `python -m voice.design_voice wang` 在自己账号里创建，再把 ID 填进环境变量。
#   DEEPSUCK_VOICE_<人设>              音色 ID（不设则用上面的系统音色）
#   DEEPSUCK_VOICE_<人设>_MODEL        模型；不设时设计音色按 ID 前缀推断（设计音色绑定创建时的模型）
#   DEEPSUCK_VOICE_<人设>_INSTRUCTION  合成指令，例如「请用东北话表达。」；0/off/空 表示不加。
#                                      系统音色 longlaoyi 等不支持指令，只有设计音色才发送。
DEFAULT_INSTRUCTIONS: dict = {}  # 人设 → 默认指令（只对设计音色生效）。王阿姨对比过开/关东北话指令，盲评无差别，默认不加：少一个参数、首包快约 50 ms
_OFF = {"", "0", "off", "none", "false", "no"}


@dataclass(frozen=True)
class VoiceSpec:
    voice: str
    model: str
    instruction: Optional[str] = None

    @property
    def cache_tag(self) -> str:
        """填充音缓存键：同一音色开/关指令合成出来的声音不同，要分开缓存。"""
        if not self.instruction:
            return self.voice
        return f"{self.voice}-i{hashlib.sha1(self.instruction.encode()).hexdigest()[:8]}"


def designed_model(voice: str) -> Optional[str]:
    """cosyvoice-v3.5-flash-vd-xxx → cosyvoice-v3.5-flash；系统音色返回 None。"""
    for mark in ("-vd-", "-vc-"):
        if voice.startswith("cosyvoice-") and mark in voice:
            return voice.split(mark, 1)[0]
    return None


def persona_voice(pid: str, default_model: Optional[str] = None, env=None) -> VoiceSpec:
    env = os.environ if env is None else env
    up = pid.upper()
    default_model = default_model or env.get("DEEPSUCK_TTS_MODEL", "cosyvoice-v3-flash")
    voice = (env.get(f"DEEPSUCK_VOICE_{up}") or "").strip() or PERSONA_VOICES.get(pid, DEFAULT_VOICE)
    model = (env.get(f"DEEPSUCK_VOICE_{up}_MODEL") or "").strip() or designed_model(voice) or default_model
    instruction = None
    if designed_model(voice):
        raw = env.get(f"DEEPSUCK_VOICE_{up}_INSTRUCTION")
        raw = DEFAULT_INSTRUCTIONS.get(pid) if raw is None else raw
        instruction = None if raw is None or raw.strip().lower() in _OFF else raw.strip()
    return VoiceSpec(voice=voice, model=model, instruction=instruction)


class DashScopeError(RuntimeError):
    pass


def api_key() -> str:
    k = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not k:
        raise DashScopeError("缺少 DASHSCOPE_API_KEY（复制 voice/.env.example 为 .env 并填写）")
    return k


async def _connect(key: str, url: str = WS_URL):
    import websockets  # 延迟导入：单测可注入假连接

    headers = {"Authorization": f"Bearer {key}", "user-agent": "deepsuck-voice/0.4", "X-DashScope-DataInspection": "enable"}
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:  # websockets<13
        return await websockets.connect(url, extra_headers=headers, max_size=None)


Connector = Callable[[str], Awaitable]


def _header(action: str, task_id: str) -> dict:
    return {"action": action, "task_id": task_id, "streaming": "duplex"}


def run_task_tts(task_id: str, model: str, voice: str, sample_rate: int, rate: float = 1.0, fmt: str = "pcm",
                 instruction: Optional[str] = None) -> dict:
    params = {"text_type": "PlainText", "voice": voice, "format": fmt, "sample_rate": sample_rate,
              "volume": 50, "rate": rate, "pitch": 1.0}
    if instruction:
        params["instruction"] = instruction
    return {"header": _header("run-task", task_id), "payload": {
        "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer", "model": model,
        "parameters": params, "input": {}}}


ASR_SILENCE_MIN_MS, ASR_SILENCE_MAX_MS = 200, 6000  # Paraformer 实时识别允许的 max_sentence_silence 范围


def clamp_sentence_silence(ms: Optional[int]) -> Optional[int]:
    """把断句静音阈值夹到服务端允许范围；None 表示用服务端默认（约 800ms）。"""
    if ms is None:
        return None
    return max(ASR_SILENCE_MIN_MS, min(ASR_SILENCE_MAX_MS, int(ms)))


def run_task_asr(task_id: str, model: str, sample_rate: int,
                 max_sentence_silence: Optional[int] = None) -> dict:
    params = {"format": "pcm", "sample_rate": sample_rate, "language_hints": ["zh"],
              "punctuation_prediction_enabled": True, "inverse_text_normalization_enabled": True,
              "heartbeat": True}
    ms = clamp_sentence_silence(max_sentence_silence)
    if ms is not None:
        # 句末静音多久判为一句结束。默认约 800ms，调小能让句末结果更早出来
        params["max_sentence_silence"] = ms
    return {"header": _header("run-task", task_id), "payload": {
        "task_group": "audio", "task": "asr", "function": "recognition", "model": model,
        "parameters": params, "input": {}}}


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
                     connect: Optional[Connector] = None, instruction: Optional[str] = None) -> AsyncIterator[bytes]:
    """CosyVoice 流式合成：逐块产出 16-bit PCM。"""
    ws = await (connect or _connect)(key or api_key())
    task_id = uuid.uuid4().hex
    try:
        await ws.send(json.dumps(run_task_tts(task_id, model, voice, sample_rate, rate, instruction=instruction)))
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
                 key: Optional[str] = None, connect: Optional[Connector] = None,
                 max_sentence_silence: Optional[int] = None):
        self.model, self.sample_rate = model, sample_rate
        self.max_sentence_silence = max_sentence_silence
        self._key, self._connect = key, connect or _connect
        self.task_id = uuid.uuid4().hex
        self.ws = None
        self._q: asyncio.Queue = asyncio.Queue()
        self._reader: Optional[asyncio.Task] = None
        self.finished = asyncio.Event()

    async def start(self) -> None:
        self.ws = await self._connect(self._key or api_key())
        await self.ws.send(json.dumps(run_task_asr(self.task_id, self.model, self.sample_rate,
                                                    self.max_sentence_silence)))
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
