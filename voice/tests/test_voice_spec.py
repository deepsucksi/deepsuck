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


def test_calm_tts_text():
    from voice.persona import calm, speakable
    assert calm("哎呀！退款啊？那太好了！！") == "哎呀。退款啊？那太好了。"
    assert calm("我找找……你等会儿啊~~") == "我找找…你等会儿啊"
    assert calm("我找找……你等会儿啊~~", pauses=False) == "我找找，你等会儿啊"
    assert calm("啊啊啊，真的？") == "啊，真的？"
    assert calm("嗯……", pauses=False) == "嗯"
    assert calm("退…退款？哪…哪个啊。。。") == "退…退款？哪…哪个啊…"
    assert speakable("好的！", calm_tts=False) == "好的！"
    assert "……" in speakable("卡号是 6222 **** 3456！")


def test_voice_prompt_is_restrained():
    from voice.persona import system_prompt
    for pid in ("wang", "li", "lin"):
        sp = system_prompt(pid, "refund")
        assert "不用感叹号" in sp and "“…”" in sp and "老花镜" in sp and "看不清" not in sp
        assert "62 岁" not in sp and "62岁" not in sp


def test_split_pause_and_range():
    from voice.persona import pause_range, split_pause
    assert split_pause("退…") == ("退", True)
    assert split_pause("…款？") == ("款？", False)
    assert split_pause("我好像…没买吧。") == ("我好像，没买吧。", False)
    assert pause_range("300-900") == (300, 900) and pause_range("0") == (0, 0) and pause_range("x") == (300, 900)


def test_stream_tts_inserts_pause_between_tasks(monkeypatch):
    from voice.services import CosyVoiceStreamTTSService
    import json
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame, TTSStoppedFrame
    from pipecat.tests.utils import SleepFrame, run_test
    from voice.tests.test_latency import _stream_connect
    monkeypatch.setenv("DEEPSUCK_PAUSE_MS", "500")
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000, clause_min_chars=4)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("退…"), LLMTextFrame("退款？哪…哪个啊。"),
              LLMFullResponseEndFrame(), SleepFrame(0.5)]
    down, _ = asyncio.run(run_test(tts, frames_to_send=frames))
    ws = connect.made[0]
    texts = [json.loads(m)["payload"]["input"]["text"] for m in ws.sent if json.loads(m)["header"]["action"] == "continue-task"]
    assert texts == ["退", "退款？", "哪", "哪个啊。"]
    assert ws.actions().count("run-task") == 3 and tts.pauses == 2 and tts.connects == 1
    gaps = [f for f in down if isinstance(f, TTSAudioRawFrame) and len(f.audio) == 24000 and not any(f.audio)]
    assert len(gaps) == 2
    assert sum(isinstance(f, TTSStoppedFrame) for f in down) == 1


def test_stream_tts_turn_ending_on_pause_still_stops(monkeypatch):
    from voice.services import CosyVoiceStreamTTSService
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSStoppedFrame
    from pipecat.tests.utils import SleepFrame, run_test
    from voice.tests.test_latency import _stream_connect
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("我好像…"), SleepFrame(0.3), LLMFullResponseEndFrame(), SleepFrame(0.3)]
    down, _ = asyncio.run(run_test(tts, frames_to_send=frames))
    assert sum(isinstance(f, TTSStoppedFrame) for f in down) == 1


def test_ambience_choice_and_mixer(monkeypatch):
    import numpy as np
    from voice import ambience as A
    assert A.choose("wang", "1") == "kitchen" and A.choose("li", "1") == "tv" and A.choose("lin", "1") == "street"
    assert A.choose("wang", "0") is None and A.choose("wang", "street") == "street"
    for f in A.SOUNDS.values():
        assert f.exists() and f.stat().st_size < 600_000
    m = A.make_mixer("wang", "1")
    asyncio.run(m.start(8000))  # 电话 8k：加载时重采样
    out = np.frombuffer(asyncio.run(m.mix(b"\x00\x00" * 160)), dtype=np.int16)
    assert len(out) == 160 and np.abs(out).max() > 0
    rms = np.sqrt(np.mean(np.frombuffer(m._sounds["kitchen"], dtype=np.int16).astype(float) ** 2)) * A.volume() / 32768
    assert 20 * np.log10(rms) < -35  # 混进去后的底噪足够低
    assert A.make_mixer("wang", "off") is None
