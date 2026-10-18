"""电话接入适配器测试：全部用假 WebSocket / TestClient，本地回环，不连任何服务商、不拨打电话。"""
import asyncio
import json
import math
import struct
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    EndFrame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)

from voice.telephony import CallInfo, TelephonyAdapter, get_adapter, list_adapters, register_adapter
from voice.telephony import pipecat_ws, server as S
from voice.telephony.ws_raw import RawStreamSerializer, parse_start


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def sine_pcm(rate: int, ms: int, freq: float = 440.0) -> bytes:
    n = rate * ms // 1000
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


# ---- 注册表 / CallInfo ----

def test_registry_lists_builtin_adapters():
    assert {"ws-raw", "pipecat-ws"} <= set(list_adapters())
    assert get_adapter("ws-raw").name == "ws-raw"
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_register_rejects_duplicate_and_nameless():
    class Dup(TelephonyAdapter):
        name = "ws-raw"

        async def accept(self, websocket):
            raise NotImplementedError

        def create_serializer(self, call):
            raise NotImplementedError

    with pytest.raises(ValueError):
        register_adapter(Dup)

    class NoName(Dup):
        name = ""

    with pytest.raises(ValueError):
        register_adapter(NoName)


def test_callinfo_normalizes_encoding():
    assert CallInfo("x", "1", encoding="ulaw").encoding == "pcmu"
    assert CallInfo("x", "1", encoding="ALAW").encoding == "pcma"
    assert CallInfo("x", "1", encoding="slin16", sample_rate=16000).encoding == "l16"
    with pytest.raises(ValueError):
        CallInfo("x", "1", encoding="opus")


# ---- ws-raw 协议 ----

def test_parse_start_ok_and_errors():
    c = parse_start(json.dumps({"event": "start", "call_id": "c1", "from": "13800001234", "to": "02100000000",
                                "encoding": "pcma", "sample_rate": 8000, "trunk": "t1"}))
    assert (c.provider, c.call_id, c.encoding, c.sample_rate, c.from_number) == ("ws-raw", "c1", "pcma", 8000, "13800001234")
    assert c.extra == {"trunk": "t1"} and c.stream_id == "c1"
    for bad in (None, b"\x00", "not json", json.dumps({"event": "media"}), json.dumps({"event": "start"}),
                json.dumps({"event": "start", "call_id": "x", "sample_rate": 44100}), "x" * 9000):
        with pytest.raises(ValueError):
            parse_start(bad)


@pytest.mark.parametrize("enc", ["pcmu", "pcma", "l16"])
def test_raw_serializer_audio_roundtrip(enc):
    from pipecat.audio.utils import pcm_to_alaw, pcm_to_ulaw, create_stream_resampler

    async def go():
        s = RawStreamSerializer(CallInfo("ws-raw", "c1", encoding=enc, sample_rate=8000))
        await s.setup(SimpleNamespace(audio_in_sample_rate=16000))
        pcm8 = sine_pcm(8000, 1000)
        if enc == "pcmu":
            payload = await pcm_to_ulaw(pcm8, 8000, 8000, create_stream_resampler())
        elif enc == "pcma":
            payload = await pcm_to_alaw(pcm8, 8000, 8000, create_stream_resampler())
        else:
            payload = pcm8
        got = 0
        step = len(payload) // 50  # 20 ms 一包
        for i in range(0, len(payload), step):
            f = await s.deserialize(payload[i:i + step])
            if f is not None:
                assert isinstance(f, InputAudioRawFrame) and f.sample_rate == 16000 and f.num_channels == 1
                got += len(f.audio)
        samples = len(payload) // (2 if enc == "l16" else 1)
        assert got > 0.8 * samples * 2 * 2  # 8k → 16k：样本数翻倍、16 bit（流式重采样有少量缓冲）
        out = 0
        for _ in range(50):  # 24 kHz 20 ms 帧 → 电话侧 8 kHz（1 秒）
            b = await s.serialize(OutputAudioRawFrame(audio=sine_pcm(24000, 20), sample_rate=24000, num_channels=1))
            if b:
                assert isinstance(b, bytes)
                out += len(b)
        bytes_per_sample = 2 if enc == "l16" else 1
        assert 0.7 * 8000 * bytes_per_sample < out <= 8000 * bytes_per_sample + 64
    run(go())


def test_raw_serializer_control_events():
    async def go():
        s = RawStreamSerializer(CallInfo("ws-raw", "c1"))
        await s.setup(SimpleNamespace(audio_in_sample_rate=16000))
        f = await s.deserialize(json.dumps({"event": "dtmf", "digit": "5"}))
        assert isinstance(f, InputDTMFFrame) and f.button.value == "5"
        assert await s.deserialize(json.dumps({"event": "dtmf", "digit": "X"})) is None
        assert await s.deserialize(json.dumps({"event": "stop"})) is None
        assert await s.deserialize("garbage") is None
        assert await s.deserialize(b"") is None
        assert json.loads(await s.serialize(InterruptionFrame())) == {"event": "clear"}
        assert json.loads(await s.serialize(EndFrame()))["event"] == "hangup"
        assert await s.serialize(EndFrame()) is None  # 只发一次
    run(go())


# ---- pipecat-ws（Twilio / Telnyx / Plivo / Exotel） ----

class FakeTwilioWS:
    def __init__(self, msgs):
        self._msgs = msgs

    def iter_text(self):
        async def gen():
            for m in self._msgs:
                yield m
        return gen()


def test_pipecat_adapter_accepts_twilio_handshake(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    ws = FakeTwilioWS([json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}),
                       json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1",
                                                               "accountSid": "AC1", "customParameters": {}}})])
    a = get_adapter("pipecat-ws")
    call = run(a.accept(ws))
    assert (call.provider, call.stream_id, call.call_id, call.encoding) == ("twilio", "MZ1", "CA1", "pcmu")
    ser = a.create_serializer(call)
    assert type(ser).__name__ == "TwilioFrameSerializer" and ser._params.auto_hang_up is False


def test_pipecat_adapter_rejects_unknown_handshake():
    ws = FakeTwilioWS([json.dumps({"hello": 1}), json.dumps({"x": 2})])
    with pytest.raises(ValueError):
        run(get_adapter("pipecat-ws").accept(ws))


def test_pipecat_serializers_built_without_credentials(monkeypatch):
    for k in ("TELNYX_API_KEY", "PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    names = {p: type(pipecat_ws.build_serializer(CallInfo(p, "c1", stream_id="s1"))).__name__
             for p in ("telnyx", "plivo", "exotel")}
    assert names == {"telnyx": "TelnyxFrameSerializer", "plivo": "PlivoFrameSerializer", "exotel": "ExotelFrameSerializer"}
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_fake")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake")
    assert pipecat_ws.build_serializer(CallInfo("twilio", "CA1", stream_id="MZ1"))._params.auto_hang_up is True
    with pytest.raises(ValueError):
        pipecat_ws.build_serializer(CallInfo("vonage", "c1"))


# ---- 路由 / 鉴权 / 护栏 ----

def test_mask_number():
    assert S.mask_number("+86 138-0000-1234") == "***1234"
    assert S.mask_number("12") == "***" and S.mask_number("") == ""


def _app(monkeypatch, tmp_path, *, max_sessions=2, build=None, enable=True, token="t0ken"):
    from voice import app as A, guard as G
    for k in ("VOICE_TELEPHONY", "VOICE_TELEPHONY_TOKEN", "VOICE_TELEPHONY_ADAPTERS"):
        monkeypatch.delenv(k, raising=False)
    if enable:
        monkeypatch.setenv("VOICE_TELEPHONY", "1")
    if token:
        monkeypatch.setenv("VOICE_TELEPHONY_TOKEN", token)
    app = A.create_app("rule", limits=G.Limits(max_sessions=max_sessions, idle_seconds=0),
                       budget=G.VoiceBudget(cap_cny=5, data_dir=str(tmp_path)))
    return app


def test_telephony_disabled_by_default(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, enable=False)
    assert app.state.telephony is False
    assert not any(getattr(r, "path", "") == "/telephony/{adapter_name}" for r in app.routes)


def test_telephony_requires_token(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path, token="")
    assert app.state.telephony is False


def test_telephony_rejects_bad_token_and_adapter(monkeypatch, tmp_path):
    from starlette.websockets import WebSocketDisconnect
    app = _app(monkeypatch, tmp_path)
    assert app.state.telephony is True
    c = TestClient(app)
    for url in ("/telephony/ws-raw", "/telephony/ws-raw?token=wrong", "/telephony/pipecat-ws?token=t0ken"):
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(url) as ws:
                ws.receive_text()
        assert e.value.code == 1008


def test_telephony_bad_handshake_closes(monkeypatch, tmp_path):
    from starlette.websockets import WebSocketDisconnect
    c = TestClient(_app(monkeypatch, tmp_path))
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/telephony/ws-raw", headers={"Authorization": "Bearer t0ken"}) as ws:
            ws.send_text(json.dumps({"event": "media"}))
            ws.receive_text()
    assert e.value.code == 1003


def test_telephony_call_lifecycle_with_stub_pipeline(monkeypatch, tmp_path):
    """真实的 FastAPIWebsocketTransport + RawStreamSerializer，管线换成直通（不调用 ASR/LLM/TTS）。"""
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    seen = {"audio": 0, "dtmf": []}

    class Echo(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, InputAudioRawFrame):
                seen["audio"] += len(frame.audio)
                await self.push_frame(OutputAudioRawFrame(audio=frame.audio, sample_rate=frame.sample_rate,
                                                          num_channels=1), FrameDirection.DOWNSTREAM)
                return
            if isinstance(frame, InputDTMFFrame):
                seen["dtmf"].append(frame.button.value)
            await self.push_frame(frame, direction)

    def build(transport, session, notify):
        return Pipeline([transport.input(), Echo(), transport.output()]), None, None

    monkeypatch.setattr(S, "disclosure_text", lambda: "")
    from voice import app as A, guard as G
    for k in ("VOICE_TELEPHONY_ADAPTERS",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VOICE_TELEPHONY", "1")
    monkeypatch.setenv("VOICE_TELEPHONY_TOKEN", "t0ken")
    from fastapi import FastAPI
    app = FastAPI()
    gate, budget = G.Gate(G.Limits(max_sessions=1)), G.VoiceBudget(cap_cny=5, data_dir=str(tmp_path))
    assert S.add_telephony_routes(app, engine="rule", limits=G.Limits(max_sessions=1, idle_seconds=0),
                                  budget=budget, gate=gate, build=build)
    c = TestClient(app)
    ulaw_silence = b"\xff" * 160
    with c.websocket_connect("/telephony/ws-raw?token=t0ken") as ws:
        ws.send_text(json.dumps({"event": "start", "call_id": "c1", "from": "13800001234", "encoding": "pcmu"}))
        for _ in range(25):
            ws.send_bytes(ulaw_silence)
        ws.send_text(json.dumps({"event": "dtmf", "digit": "1"}))
        echoed = 0
        for _ in range(50):
            m = ws.receive()
            if m.get("bytes"):
                echoed += len(m["bytes"])
            if echoed >= 160 * 5:
                break
        assert echoed >= 160 * 5  # 机器人方向回来的是 8 kHz μ-law
        assert len(gate.active) == 1 and budget.status()["active"] == 1
        ws.send_text(json.dumps({"event": "stop"}))
    import time
    deadline = time.time() + 15  # 等服务端收尾（CI 机器慢时留足余量）
    while gate.active and time.time() < deadline:
        time.sleep(0.05)
    assert seen["audio"] > 0 and seen["dtmf"] == ["1"]
    assert not gate.active and budget.status()["active"] == 0


def test_telephony_rejects_when_full(monkeypatch, tmp_path):
    from starlette.websockets import WebSocketDisconnect
    app = _app(monkeypatch, tmp_path, max_sessions=1)
    app.state.gate.active["busy"] = "tel:x"
    c = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/telephony/ws-raw?token=t0ken") as ws:
            ws.send_text(json.dumps({"event": "start", "call_id": "c2"}))
            ws.receive_text()
    assert e.value.code == 1013
