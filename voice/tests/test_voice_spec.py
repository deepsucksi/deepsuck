import asyncio
import json

from voice import dashscope_ws as ds
from voice.processors import fillers_missing, synth_fillers

VD = "cosyvoice-v3.5-flash-vd-wangdb-0123456789abcdef"


def test_default_is_system_voice():
    vs = ds.persona_voice("wang", env={})
    assert vs == ds.VoiceSpec("longlaoyi_v3", "cosyvoice-v3-flash", None)


def test_designed_voice_infers_model_and_ignores_instruction_for_system_voice():
    vs = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD})
    assert vs.model == "cosyvoice-v3.5-flash" and vs.voice == VD
    # 系统音色不支持指令：设了也不发
    vs2 = ds.persona_voice("li", env={"DEEPSUCK_VOICE_LI_INSTRUCTION": "请用东北话表达。"})
    assert vs2.instruction is None


def test_instruction_toggle(monkeypatch):
    on = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD, "DEEPSUCK_VOICE_WANG_INSTRUCTION": "请用东北话表达。"})
    assert on.instruction == "请用东北话表达。"
    for off in ("0", "off", "", " none "):
        assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD,
                                             "DEEPSUCK_VOICE_WANG_INSTRUCTION": off}).instruction is None
    monkeypatch.setitem(ds.DEFAULT_INSTRUCTIONS, "wang", "请用东北话表达。")
    assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD}).instruction == "请用东北话表达。"
    assert ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD,
                                         "DEEPSUCK_VOICE_WANG_INSTRUCTION": "0"}).instruction is None


def test_explicit_model_wins_and_global_default():
    vs = ds.persona_voice("lin", env={"DEEPSUCK_TTS_MODEL": "cosyvoice-v3-plus"})
    assert vs.model == "cosyvoice-v3-plus"
    vs = ds.persona_voice("wang", env={"DEEPSUCK_VOICE_WANG": VD, "DEEPSUCK_VOICE_WANG_MODEL": "x"})
    assert vs.model == "x"


def test_run_task_tts_instruction():
    p = ds.run_task_tts("t", "m", "v", 24000)["payload"]["parameters"]
    assert "instruction" not in p
    p = ds.run_task_tts("t", "m", "v", 24000, instruction="请用东北话表达。")["payload"]["parameters"]
    assert p["instruction"] == "请用东北话表达。"


def test_cache_tag_separates_instruction():
    a = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None)
    b = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", "请用东北话表达。")
    assert a.cache_tag == VD and b.cache_tag != a.cache_tag


def test_synth_fillers_passes_model_and_instruction(tmp_path):
    calls = []

    async def synth(line, voice, sample_rate, **kw):
        calls.append((voice, kw))
        yield b"\x10\x27" * 4000

    vs = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", "请用东北话表达。")
    got = asyncio.run(synth_fillers("wang", vs, 24000, synth=synth, cache_dir=tmp_path))
    assert got and not fillers_missing("wang", vs, 24000, got)
    assert all(v == VD and kw == {"model": "cosyvoice-v3.5-flash", "instruction": "请用东北话表达。"} for v, kw in calls)
    assert all(vs.cache_tag in f.name for f in tmp_path.iterdir())
    # 关掉指令是另一套缓存
    off = ds.VoiceSpec(VD, "cosyvoice-v3.5-flash", None)
    assert asyncio.run(synth_fillers("wang", off, 24000, synth=synth, cache_dir=tmp_path, cached_only=True)) == {}


def test_stream_service_sends_instruction():
    from voice.services import CosyVoiceStreamTTSService

    sent = []

    class WS:
        async def send(self, m):
            sent.append(json.loads(m))

    s = CosyVoiceStreamTTSService(voice=VD, model="cosyvoice-v3.5-flash", instruction="请用东北话表达。", key="k")
    s._websocket = WS()
    asyncio.run(s._open_task("ctx"))
    p = sent[0]["payload"]
    assert p["model"] == "cosyvoice-v3.5-flash" and p["parameters"]["instruction"] == "请用东北话表达。"
