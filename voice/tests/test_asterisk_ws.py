"""asterisk-ws 适配器（Asterisk chan_websocket）测试：假 WebSocket / TestClient，本地回环，不连 Asterisk、不拨电话。"""
import asyncio
import json
import math
import struct
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)

from voice.telephony import get_adapter, list_adapters
from voice.telephony import server as S
from voice.telephony.asterisk_ws import AsteriskWebSocketSerializer, parse_media_start


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def sine_pcm(rate: int, ms: int, freq: float = 440.0) -> bytes:
    n = rate * ms // 1000
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


def media_start(fmt="slin16", frame=640, **kw):
    msg = {"event": "MEDIA_START", "connection_id": "e226e283", "channel": "WebSocket/deepsuck-0001",
           "channel_id": "1760000000.42", "format": fmt, "optimal_frame_size": frame, "ptime": 20,
           "channel_variables": {"__DS_FROM": "ds1234abcd", "__DS_EXTEN": "9000", "OTHER": "x"}}
    msg.update(kw)
    return json.dumps(msg)


def test_registered():
    assert "asterisk-ws" in list_adapters()
    assert get_adapter("asterisk-ws").name == "asterisk-ws"


@pytest.mark.parametrize("fmt,enc,rate", [("slin16", "l16", 16000), ("slin", "l16", 8000),
                                          ("ulaw", "pcmu", 8000), ("alaw", "pcma", 8000)])
def test_parse_media_start_json(fmt, enc, rate):
    c = parse_media_start(media_start(fmt))
    assert (c.provider, c.call_id, c.stream_id) == ("asterisk-ws", "1760000000.42", "e226e283")
    assert (c.encoding, c.sample_rate) == (enc, rate)
    assert (c.from_number, c.to_number) == ("ds1234abcd", "9000")
    assert c.extra["optimal_frame_size"] == 640 and c.extra["format"] == fmt


def test_parse_media_start_plain_text_and_defaults():
    c = parse_media_start("MEDIA_START connection_id:abc channel:WebSocket/x channel_id:pbx-1.2 format:ulaw "
                          "optimal_frame_size:160 ptime:20")
    assert (c.call_id, c.encoding, c.sample_rate, c.extra["optimal_frame_size"]) == ("pbx-1.2", "pcmu", 8000, 160)
    # 帧长缺失/离谱时按 20 ms 推算
    assert parse_media_start(media_start("slin16", frame=0)).extra["optimal_frame_size"] == 640
    assert parse_media_start(media_start("ulaw", frame=10 ** 6)).extra["optimal_frame_size"] == 160
    c = parse_media_start(media_start(channel_variables={"DS_FROM": "1001"}))
    assert (c.from_number, c.to_number) == ("1001", "")


@pytest.mark.parametrize("bad", [None, b"\x00", "", "x" * 9000, "not json {", "{bad json",
                                 json.dumps({"event": "DTMF_END"}), "MEDIA_XON", media_start("opus"),
                                 media_start("g722"), media_start(channel_id="", connection_id="")])
def test_parse_media_start_rejects(bad):
    with pytest.raises(ValueError):
        parse_media_start(bad)


@pytest.mark.parametrize("fmt", ["slin16", "ulaw"])
def test_serializer_audio_in_and_framed_out(fmt):
    async def go():
        call = parse_media_start(media_start(fmt, frame=640 if fmt == "slin16" else 160))
        s = AsteriskWebSocketSerializer(call)
        await s.setup(SimpleNamespace(audio_in_sample_rate=16000))
        frame = call.extra["optimal_frame_size"]
        payload = sine_pcm(16000, 20) if fmt == "slin16" else b"\xff" * 160
        frames = [await s.deserialize(payload) for _ in range(10)]  # 8k→16k 流式重采样首包可能先缓冲
        frames = [f for f in frames if f is not None]
        assert frames and all(isinstance(f, InputAudioRawFrame) and f.sample_rate == 16000 and f.num_channels == 1
                              for f in frames)
        total = 0
        for ms in (7, 13, 20, 33, 41, 9, 100):  # TTS 帧长不规则（24 kHz）
            out = await s.serialize(OutputAudioRawFrame(audio=sine_pcm(24000, ms), sample_rate=24000, num_channels=1))
            if out is not None:
                assert isinstance(out, bytes) and len(out) % frame == 0  # 只发整帧，零头留到下一包
                total += len(out)
        bytes_per_sec = 32000 if fmt == "slin16" else 8000
        assert total > 0.15 * bytes_per_sec * 0.7
        assert len(s._pending) < frame
    run(go())


def test_serializer_control_commands():
    async def go():
        s = AsteriskWebSocketSerializer(parse_media_start(media_start()))
        await s.setup(SimpleNamespace(audio_in_sample_rate=16000))
        await s.serialize(OutputAudioRawFrame(audio=sine_pcm(24000, 7), sample_rate=24000, num_channels=1))
        assert json.loads(await s.serialize(InterruptionFrame())) == {"command": "FLUSH_MEDIA"}
        assert len(s._pending) == 0  # 打断时零头也丢掉
        f = await s.deserialize(json.dumps({"event": "DTMF_END", "channel_id": "x", "digit": "5"}))
        assert isinstance(f, InputDTMFFrame) and f.button.value == "5"
        assert await s.deserialize(json.dumps({"event": "DTMF_END", "digit": "Z"})) is None
        for ev in ("MEDIA_XOFF", "MEDIA_XON", "STATUS", "QUEUE_DRAINED"):
            assert await s.deserialize(json.dumps({"event": ev})) is None
        assert await s.deserialize("garbage") is None and await s.deserialize(b"") is None
        assert json.loads(await s.serialize(EndFrame())) == {"command": "HANGUP"}
        assert await s.serialize(CancelFrame()) is None  # 只挂一次
    run(go())


def test_route_call_lifecycle_with_stub_pipeline(monkeypatch, tmp_path):
    """真实 FastAPIWebsocketTransport + asterisk-ws serializer，管线换成回声（不调 ASR/LLM/TTS）。"""
    from fastapi import FastAPI
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    from voice import guard as G

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
    monkeypatch.setenv("VOICE_TELEPHONY", "1")
    monkeypatch.setenv("VOICE_TELEPHONY_TOKEN", "t0ken-for-tests")
    monkeypatch.setenv("VOICE_TELEPHONY_ADAPTERS", "asterisk-ws")
    app = FastAPI()
    gate, budget = G.Gate(G.Limits(max_sessions=1)), G.VoiceBudget(cap_cny=5, data_dir=str(tmp_path))
    assert S.add_telephony_routes(app, engine="rule", limits=G.Limits(max_sessions=1, idle_seconds=0),
                                  budget=budget, gate=gate, build=build)
    c = TestClient(app)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:  # 没 token / ws-raw 没在白名单里
        with c.websocket_connect("/telephony/asterisk-ws") as ws:
            ws.receive_text()
    assert e.value.code == 1008
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/telephony/ws-raw?token=t0ken-for-tests") as ws:
            ws.receive_text()
    import base64
    for bad in ("Basic " + base64.b64encode(b"asterisk:wrong").decode(), "Basic !!notbase64", "Basic "):
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/telephony/asterisk-ws", headers={"Authorization": bad}) as ws:
                ws.receive_text()
        assert e.value.code == 1008
    frame = sine_pcm(16000, 20)  # slin16 20 ms = 640 字节
    basic = "Basic " + base64.b64encode(b"asterisk:t0ken-for-tests").decode()  # Asterisk websocket_client 的鉴权方式
    with c.websocket_connect("/telephony/asterisk-ws", headers={"Authorization": basic}) as ws:
        ws.send_text(media_start("slin16"))
        for _ in range(25):
            ws.send_bytes(frame)
        ws.send_text(json.dumps({"event": "DTMF_END", "digit": "1"}))
        echoed = 0
        for _ in range(80):
            m = ws.receive()
            if m.get("bytes"):
                assert len(m["bytes"]) % 640 == 0
                echoed += len(m["bytes"])
            if echoed >= 640 * 5:
                break
        assert echoed >= 640 * 5
        assert len(gate.active) == 1
    deadline = time.time() + 15  # Asterisk 侧挂机 = 关闭 WebSocket
    while gate.active and time.time() < deadline:
        time.sleep(0.05)
    assert seen["audio"] > 0 and seen["dtmf"] == ["1"]
    assert not gate.active and budget.status()["active"] == 0
