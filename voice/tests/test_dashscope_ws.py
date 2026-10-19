import asyncio

import pytest

from voice import dashscope_ws as ds


def test_message_builders():
    m = ds.run_task_tts("t1", "cosyvoice-v3-flash", "longlaoyi_v3", 24000)
    assert m["header"] == {"action": "run-task", "task_id": "t1", "streaming": "duplex"}
    p = m["payload"]
    assert (p["task_group"], p["task"], p["function"]) == ("audio", "tts", "SpeechSynthesizer")
    assert p["parameters"]["voice"] == "longlaoyi_v3" and p["parameters"]["sample_rate"] == 24000
    a = ds.run_task_asr("t2", "paraformer-realtime-v2", 16000)
    assert a["payload"]["task"] == "asr" and a["payload"]["function"] == "recognition"
    assert a["payload"]["parameters"]["sample_rate"] == 16000
    assert ds.continue_task_text("t1", "你好")["payload"]["input"]["text"] == "你好"
    assert ds.finish_task("t1")["header"]["action"] == "finish-task"


def test_persona_voices_are_elderly_for_elders():
    assert ds.PERSONA_VOICES["wang"] == "longlaoyi_v3"
    assert ds.PERSONA_VOICES["lin"] == "longanyang"
    # #95：郑老板系统音色 longsanshu_v3；小陈妈妈是设计音色，只认 DEEPSUCK_VOICE_CHEN，代码里不写死（没配走默认音色）
    assert ds.PERSONA_VOICES["zheng"] == "longsanshu_v3"
    assert "chen" not in ds.PERSONA_VOICES
    assert ds.DEFAULT_VOICE == "longlaoyi_v3"


def test_synthesize_streams_pcm(fake_ws):
    connect = fake_ws(mode="tts")

    async def go():
        return b"".join([c async for c in ds.synthesize("你好", connect=connect)])

    pcm = asyncio.run(go())
    assert len(pcm) == 640
    ws = connect.made[0]
    actions = [m["header"]["action"] for m in ws.sent_json()]
    assert actions == ["run-task", "continue-task", "finish-task"]
    assert ws.closed


def test_synthesize_task_failed(fake_ws):
    connect = fake_ws(mode="tts", fail="InvalidApiKey")

    async def go():
        return [c async for c in ds.synthesize("你好", connect=connect)]

    with pytest.raises(ds.DashScopeError):
        asyncio.run(go())


def test_transcribe_pcm(fake_ws):
    connect = fake_ws(mode="asr", asr_text="哎呦小伙子")
    text = asyncio.run(ds.transcribe_pcm(b"\x00\x00" * 16000, connect=connect))
    assert text == "哎呦小伙子"
    ws = connect.made[0]
    assert any(isinstance(m, bytes) for m in ws.sent)
    assert ws.sent_json()[0]["payload"]["model"] == "paraformer-realtime-v2"


def test_api_key_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ds.DashScopeError):
        ds.api_key()
