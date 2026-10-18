"""语音测试：不联网，用假 WebSocket 模拟 DashScope 协议。"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "python"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pytest  # noqa: E402


class FakeWS:
    """按 DashScope 协议回包：run-task → task-started；TTS 在 finish-task 后给 PCM + task-finished；
    ASR 每收到一块音频给一条中间结果，finish-task 后给一句最终结果 + task-finished。"""

    def __init__(self, mode="tts", pcm_chunks=(b"\x01\x00" * 160, b"\x02\x00" * 160), fail=None,
                 asr_text="我是客服，卡号6222000012345678901"):
        self.mode, self.pcm_chunks, self.fail, self.asr_text = mode, list(pcm_chunks), fail, asr_text
        self.sent, self.closed = [], False
        self.q: asyncio.Queue = asyncio.Queue()
        self.task_id = None

    def _ev(self, event, **payload):
        return json.dumps({"header": {"event": event, "task_id": self.task_id, **({"error_code": "X", "error_message": self.fail} if event == "task-failed" else {})},
                           "payload": payload})

    async def send(self, msg):
        self.sent.append(msg)
        if isinstance(msg, (bytes, bytearray)):
            if self.mode == "asr":
                await self.q.put(self._ev("result-generated", output={"sentence": {"text": "我是", "sentence_end": False}}))
            return
        d = json.loads(msg)
        action = d["header"]["action"]
        self.task_id = d["header"]["task_id"]
        if action == "run-task":
            if self.fail:
                await self.q.put(self._ev("task-failed"))
            else:
                await self.q.put(self._ev("task-started"))
        elif action == "finish-task":
            if self.mode == "tts":
                for c in self.pcm_chunks:
                    await self.q.put(c)
            else:
                await self.q.put(self._ev("result-generated", output={"sentence": {"heartbeat": True}}))
                await self.q.put(self._ev("result-generated", output={"sentence": {"text": self.asr_text, "sentence_end": True}}))
            await self.q.put(self._ev("task-finished"))

    async def recv(self):
        return await self.q.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed and self.q.empty():
            raise StopAsyncIteration
        return await self.q.get()

    async def close(self):
        self.closed = True

    def sent_json(self):
        return [json.loads(m) for m in self.sent if isinstance(m, str)]


@pytest.fixture
def fake_ws():
    made = []

    def factory(**kw):
        async def connect(key, url=None):
            ws = FakeWS(**kw)
            made.append(ws)
            return ws
        connect.made = made
        return connect

    return factory


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    # 单元测试绝不使用真实 key
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-not-real")


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    # 文字记录 / 录音 / 预算账本都写到临时目录，绝不碰真实数据目录
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for k in ("KEEP_AUDIO", "KEEP_AUDIO_DAYS", "VOICE_TRANSCRIPTS", "VOICE_TRANSCRIPT_DAYS",
              "VOICE_AI_DISCLOSURE", "VOICE_AI_DISCLOSURE_TEXT", "VOICE_TELEPHONY_DISCLOSURE",
              "TRACE_DIR", "TRACE_DAYS", "TRACE_MAX_MB", "TRACE_MIN_FREE_MB", "TRACE_AUDIO", "VOICE_TRACE",
              "TRACE_ADMIN_TOKEN", "TURN_SECRET", "TURN_URLS", "TURN_TTL", "VOICE_BROWSER_STUN"):
        monkeypatch.delenv(k, raising=False)
