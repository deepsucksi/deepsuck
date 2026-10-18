"""短口头语（backchannel）：选择规则、轮换、预合成缓存、回合结束即播、LLM 上下文、打断、first_audible 指标、接线。全部离线。"""
import asyncio
import random

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterruptionFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test

from voice import backchannel as BC
from voice.backchannel import Backchannel, skip_reason, trim_silence
from voice.latency import LatencyObserver, summarize
from voice.persona import FILLERS, system_prompt
from voice.processors import FillerProcessor, IntelProcessor, synth_fillers

LOUD = b"\x00\x10" * 2400  # 0.1s @24k，幅度 4096
FILL = {"嗯……": LOUD, "啊？": LOUD, "你说啥？": LOUD}


# ---------------- 清单与规则 ----------------

def test_each_persona_has_6_to_10_short_lines():
    for pid in ("wang", "li", "lin"):
        lines = FILLERS[pid]
        assert 6 <= len(lines) <= 10 and len(set(lines)) == len(lines)
        assert all(len(x) <= 8 for x in lines)


@pytest.mark.parametrize("text,why", [
    ("喂", "short"), ("对。", "short"), ("好的好的", None),
    ("你快点操作，别磨蹭了", "urge"), ("喂喂，听到没有", "urge"), ("阿姨你在吗？我这边等着呢", "urge"),
    ("是不是这样？", "followup"), ("您明白了吗", "followup"),
    ("您用的是哪个银行的卡？我这边帮您登记一下", None),
    ("我是淘宝客服，您上周买的衣服有质量问题。", None),
])
def test_skip_reason(text, why):
    assert skip_reason(text) == why


def test_enabled_env():
    assert BC.enabled({}) is True
    assert BC.enabled({"DEEPSUCK_BACKCHANNEL": "1"}) is True
    for v in ("0", "false", "off", "no", "OFF"):
        assert BC.enabled({"DEEPSUCK_BACKCHANNEL": v}) is False


def test_rotation_never_repeats_consecutively_and_uses_only_available():
    have = ["嗯……", "啊？", "你说啥？"]
    bc = Backchannel(lambda: have, rng=random.Random(3).random)
    seq = []
    for _ in range(60):
        bc.note("您好，我是淘宝客服这边的")
        seq.append(bc.take())
    assert all(a != b for a, b in zip(seq, seq[1:]))
    assert set(seq) == set(have)  # 随机，三条都会轮到
    assert bc.played == 60


def test_note_is_sticky_within_turn_and_take_once():
    bc = Backchannel(lambda: ["嗯……", "啊？"], rng=lambda: 0.0)
    a = bc.note("您好，我是客服")
    assert a == bc.note("这边给您办理退款") and a is not None
    assert bc.take() == a and bc.take() is None  # 每回合一次
    # 回合结束后再来的转写算新回合（开始帧可能晚于转写），且不和上一条重复
    b = bc.note("我是派出所的，找你核实一下情况")
    assert b is not None and b != a and bc.take() == b


def test_skip_then_take_returns_none_and_counts():
    bc = Backchannel(lambda: ["嗯……"], rng=lambda: 0.0)
    assert bc.note("快点") is None and bc.take() is None and bc.skipped == 1 and bc.last is None
    # 前一段很短、合起来够长：按整回合文本判断
    bc.note("喂")
    assert bc.note("我是派出所的民警，找你核实情况") == "嗯……"


def test_take_without_transcript_still_picks_and_none_when_nothing_cached():
    bc = Backchannel(lambda: ["嗯……"], rng=lambda: 0.0)
    assert bc.take() == "嗯……"
    empty = Backchannel(lambda: [])
    empty.note("我是派出所的民警，找你核实情况")
    assert empty.take() is None  # 合成失败/还没合成好：优雅降级，不播


# ---------------- 音频缓存 ----------------

def test_trim_silence_removes_leading_and_trailing_quiet():
    import numpy as np
    sr = 24000
    a = np.concatenate([np.zeros(sr // 2), np.full(sr // 10, 3000), np.zeros(sr // 4)]).astype(np.int16)
    out = trim_silence(a.tobytes(), sr, keep_ms=20)
    assert len(out) // 2 == sr // 10 + 2 * int(sr * 0.02)
    assert trim_silence(b"\x00\x00" * 100, sr) == b""


def test_cache_dir_prefers_explicit_then_data_dir(tmp_path):
    assert BC.cache_dir({"DEEPSUCK_FILLER_CACHE_DIR": "/x"}).as_posix() == "/x"
    assert BC.cache_dir({"DATA_DIR": "/data"}).as_posix() == "/data/voice/fillers"
    assert BC.cache_dir({"XDG_CACHE_HOME": "/c"}).as_posix() == "/c/deepsuck/voice"


def test_synth_fillers_trims_caches_in_memory_and_uses_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSUCK_FILLER_CACHE_DIR", raising=False)
    calls = []

    async def synth(text, voice, sample_rate):
        calls.append(text)
        yield b"\x00\x00" * 7200 + LOUD  # 0.3s 静音开头，像 CosyVoice 的真实输出

    got = asyncio.run(synth_fillers("li", "longlaobo_v3", 24000, synth=synth))
    assert set(got) == set(FILLERS["li"]) and len(calls) == len(FILLERS["li"])
    assert all(len(v) < len(LOUD) + 4800 for v in got.values())  # 开头静音被裁掉
    d = tmp_path / "voice" / "fillers"
    assert len(list(d.glob("longlaobo_v3-24000-*.pcm"))) == len(FILLERS["li"])
    for f in d.iterdir():
        f.unlink()
    again = asyncio.run(synth_fillers("li", "longlaobo_v3", 24000, synth=synth, cached_only=True))
    assert again == got and len(calls) == len(FILLERS["li"])  # 内存缓存，不再调用 TTS
    other_rate = asyncio.run(synth_fillers("li", "longlaobo_v3", 16000, synth=synth, cached_only=True))
    assert other_rate == {}  # 按采样率区分


def test_synth_fillers_partial_failure_keeps_what_worked(tmp_path):
    n = {"i": 0}

    async def synth(text, voice, sample_rate):
        n["i"] += 1
        if n["i"] > 2:
            raise RuntimeError("quota")
        yield LOUD

    got = asyncio.run(synth_fillers("wang", "v-partial", 24000, synth=synth, cache_dir=tmp_path))
    assert len(got) == 2


# ---------------- FillerProcessor：回合结束即播 ----------------

def _bc(lines=None, rng=lambda: 0.0):
    have = dict(FILL if lines is None else lines)
    return have, Backchannel(lambda: [k for k, v in have.items() if v], rng=rng)


def _run(frames, *, delay_ms=0, note=None, fillers=None):
    have, bc = _bc(fillers)
    fp = FillerProcessor(have, sample_rate=24000, delay_ms=650, backchannel=bc, backchannel_delay_ms=delay_ms)

    class Noter(FrameProcessor):  # 代替 IntelProcessor：转写到了就 note()
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                bc.note(frame.text)
            await self.push_frame(frame, direction)

    from pipecat.pipeline.pipeline import Pipeline
    down, _ = asyncio.run(run_test(Pipeline([Noter(), fp]), frames_to_send=frames))
    return fp, bc, [f for f in down if type(f) is OutputAudioRawFrame], down


def _tf(t):
    return TranscriptionFrame(t, "u", "t")


LONG = "我是淘宝客服，您上周买的衣服有质量问题"


def test_backchannel_plays_right_at_turn_end_without_waiting_for_llm():
    fp, bc, out, down = _run([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0), _tf(LONG),
                              SleepFrame(0.01), UserStoppedSpeakingFrame(), LLMTextFrame("哎"), SleepFrame(0.05)])
    assert len(out) == 1 and fp.played == 1 and out[0].audio == LOUD
    i_stop = next(i for i, f in enumerate(down) if isinstance(f, UserStoppedSpeakingFrame))
    i_aud = next(i for i, f in enumerate(down) if type(f) is OutputAudioRawFrame)
    i_llm = next(i for i, f in enumerate(down) if isinstance(f, LLMTextFrame))
    assert i_aud <= i_stop + 1 and i_aud < i_llm  # 回合结束同步推出，排在正式回复前面


def test_backchannel_skipped_for_urging_and_short():
    for t in ("快点啊你", "喂"):
        fp, bc, out, _ = _run([UserStartedSpeakingFrame(), _tf(t), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.05)])
        assert out == [] and bc.skipped == 1


def test_backchannel_not_while_bot_speaking_and_once_per_turn():
    _, bc, out, _ = _run([BotStartedSpeakingFrame(), UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(),
                          SleepFrame(0.05)])
    assert out == [] and bc.last is None and bc.played == 0
    _, _, out, _ = _run([UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), UserStoppedSpeakingFrame(),
                         SleepFrame(0.05)])
    assert len(out) == 1


def test_backchannel_two_turns_differ():
    fr = []
    for _ in range(2):
        fr += [UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.02)]
    _, bc, out, _ = _run(fr)
    assert len(out) == 2 and out[0].audio == out[1].audio  # 同样的假音频
    assert bc.played == 2


def test_backchannel_delay_and_interruption_cancels():
    fp, _, out, _ = _run([UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.15)],
                         delay_ms=80)
    assert len(out) == 1
    fp, _, out, _ = _run([UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.01),
                          InterruptionFrame(), SleepFrame(0.15)], delay_ms=80)
    assert out == [] and fp.cancelled == 1
    # 用户又开口（新回合）也作废未播的
    fp, _, out, _ = _run([UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.01),
                          UserStartedSpeakingFrame(), SleepFrame(0.15)], delay_ms=80)
    assert out == []


def test_backchannel_ignores_vad_pauses_and_degrades_without_audio():
    # 句中停顿再久也不插嘴（只看回合结束）
    _, _, out, _ = _run([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0), SleepFrame(0.8)])
    assert out == []
    _, _, out, _ = _run([UserStartedSpeakingFrame(), _tf(LONG), SleepFrame(0.01), UserStoppedSpeakingFrame(), SleepFrame(0.05)],
                        fillers={})
    assert out == []


def _played_backchannel_bytes(interrupt: bool) -> int:
    from pipecat.transports.base_output import BaseOutputTransport
    from pipecat.transports.base_transport import TransportParams
    from pipecat.pipeline.pipeline import Pipeline

    written = []

    class Out(BaseOutputTransport):
        async def start(self, frame):
            await super().start(frame)
            await self.set_transport_ready(frame)

        async def write_audio_frame(self, frame):
            written.append(frame.audio)
            await asyncio.sleep(len(frame.audio) / 48000)  # 按实时速度播放
            return True

    async def go():
        out = Out(TransportParams(audio_out_enabled=True, audio_out_sample_rate=24000))
        long_audio = {"嗯……": b"\x00\x10" * 24000}  # 1s
        bc = Backchannel(lambda: list(long_audio), rng=lambda: 0.0)
        fp = FillerProcessor(long_audio, sample_rate=24000, backchannel=bc)
        frames = [UserStartedSpeakingFrame(), UserStoppedSpeakingFrame(), SleepFrame(0.15)]
        frames += [InterruptionFrame(), SleepFrame(1.3)] if interrupt else [SleepFrame(1.45)]
        await run_test(Pipeline([fp, out]), frames_to_send=frames, expected_down_frames=None)
    asyncio.run(go())
    return sum(len(a) for a in written if any(a))


def test_interruption_stops_backchannel_in_output_transport():
    """打断：口头语是普通输出音频，InterruptionFrame 到输出 transport 时会和 TTS 音频一起被清掉。
    用 Pipecat 自带的 BaseOutputTransport 验证：不打断能播完 1s，打断后只播出一小段。"""
    full = _played_backchannel_bytes(False)
    cut = _played_backchannel_bytes(True)
    assert full >= 48000 * 0.95
    assert 0 < cut < full * 0.6


# ---------------- LLM 上下文 ----------------

def test_system_prompt_mentions_backchannel_only_when_said():
    assert "已经先随口应了一声" not in system_prompt("wang", "refund")
    sp = system_prompt("wang", "refund", said_first="啊？")
    assert "“啊？”" in sp and "开头不要再用嗯" in sp


def _session():
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32
    return Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)


def test_intel_processor_writes_backchannel_into_llm_prompt():
    ctx = LLMContext([{"role": "system", "content": "x"}])
    bc = Backchannel(lambda: ["嗯……"], rng=lambda: 0.0)
    intel = IntelProcessor(_session(), context=ctx, mode="llm", backchannel=bc)
    asyncio.run(run_test(intel, frames_to_send=[_tf("我是淘宝客服，您的订单有问题需要退款")]))
    assert intel.said_first == "嗯……"
    assert "“嗯……”" in ctx.get_messages()[0]["content"]
    # 下一回合对方催促：不说口头语，提示词也不再提
    bc.take()
    intel = IntelProcessor(_session(), context=ctx, mode="llm", backchannel=bc)  # 处理器实例不能跑两次 run_test
    asyncio.run(run_test(intel, frames_to_send=[_tf("你快点")]))
    assert intel.said_first == "" and "随口应了一声" not in ctx.get_messages()[0]["content"]


# ---------------- 指标 ----------------

def test_latency_first_audible_counts_backchannel_and_keeps_reply_first_packet():
    t = {"now": 100.0}
    obs = LatencyObserver(vad_stop_secs=0.2, clock=lambda: t["now"])
    fp = FillerProcessor({})

    def push(at, frame, src=None):
        t["now"] = 100 + at
        asyncio.run(obs.on_push_frame(FramePushed(source=src, destination=None, frame=frame,
                                                  direction=FrameDirection.DOWNSTREAM, timestamp=0)))
    push(1.0, UserStartedSpeakingFrame())
    push(2.0, VADUserStoppedSpeakingFrame(stop_secs=0.2))
    push(2.6, UserStoppedSpeakingFrame())
    push(2.61, OutputAudioRawFrame(LOUD, 24000, 1), src=FillerProcessor({}))   # 口头语
    push(2.7, OutputAudioRawFrame(LOUD, 24000, 1), src=FrameProcessor())      # 别处的输出帧不算
    push(2.65, BotStartedSpeakingFrame())
    push(4.0, TTSAudioRawFrame(LOUD, 24000, 1))
    row = obs.turns[0]
    assert row["first_audible"] == 810 and row["e2e_reply"] == 2200 and row["filler"] == 1
    assert row["e2e_any"] == 850
    s = summarize(obs.turns)
    assert s["first_audible"]["p50"] == 810 and s["e2e_reply"]["p50"] == 2200
    del fp


def test_probe_headline():
    from voice.probe import headline
    server = summarize([{"first_audible": 800, "e2e_reply": 2000, "filler": 1},
                        {"first_audible": 1000, "e2e_reply": 1800, "filler": 0}])
    h = headline(server, {"n": 2, "p50": 950.0}, [{"filler": 1}, {"filler": 0}])
    assert h == {"first_audible_p50": 900.0, "client_first_audible_p50": 950.0, "reply_first_packet_p50": 1900.0,
                 "filler_turns": 1, "turns": 2}


# ---------------- 接线 ----------------

def _build(monkeypatch, env, profile="web", engine="llm"):
    from voice.app import build_pipeline
    from voice.tests.test_latency import _FakeLLM, _session as s2, _Transport
    if env is None:
        monkeypatch.delenv("DEEPSUCK_BACKCHANNEL", raising=False)
    else:
        monkeypatch.setenv("DEEPSUCK_BACKCHANNEL", env)
    have = dict(FILL)

    async def go():
        return build_pipeline(_Transport(), s2(), None, engine=engine, fillers=have, llm=_FakeLLM(), profile=profile)
    pl, intel, _ = asyncio.run(go())
    fp = next(p for p in pl.processors if isinstance(p, FillerProcessor))
    return fp, intel, have


@pytest.mark.parametrize("profile", ["web", "phone"])
def test_build_pipeline_backchannel_default_on_both_profiles(monkeypatch, profile):
    fp, intel, have = _build(monkeypatch, None, profile)
    assert fp.backchannel is not None and intel.backchannel is fp.backchannel
    assert fp.fillers is have  # 后台补齐的同一个字典
    have["新合成的"] = LOUD
    assert "新合成的" in fp.backchannel.available()


def test_build_pipeline_backchannel_off_falls_back_to_latency_filler(monkeypatch):
    fp, intel, _ = _build(monkeypatch, "0")
    assert fp.backchannel is None and intel.backchannel is None and fp.delay_ms == 650


def test_build_pipeline_rule_mode_has_backchannel(monkeypatch):
    fp, intel, _ = _build(monkeypatch, None, engine="rule")
    assert intel.backchannel is fp.backchannel is not None


def test_profile_backchannel_delay_env():
    from voice.tuning import get_profile
    assert get_profile("web").backchannel_delay_ms == 0 and get_profile("phone").backchannel_delay_ms == 0
    assert get_profile("phone", {"DEEPSUCK_PHONE_LAT_BACKCHANNEL_DELAY_MS": "120"}).backchannel_delay_ms == 120


# ---------------- 数据源：personas/voice_traits.yaml ----------------

ONLINE_FIRST8 = {  # ccca71b 线上的口头语；音频缓存按文本区分，留下的这几条不能改字（王阿姨删去“哎哟……”，李大爷删去“大点声……”）
    "wang": ["嗯……", "啊？", "哎……", "你说啥？", "等一下啊……", "我听听啊……", "哦……"],
    "li": ["啊？", "嗯？", "啥？", "你说啥？", "哦……", "等会儿……", "嗯……"],
    "lin": ["呃……", "嗯嗯", "啊？", "等下哈", "哦哦", "啊这……", "嗯……我想想", "诶？"],
}


def test_fillers_come_from_voice_traits_yaml_and_keep_online_lines():
    from personas.voice_traits import fillers
    assert FILLERS == fillers()
    for pid, lines in ONLINE_FIRST8.items():
        assert FILLERS[pid][:len(lines)] == lines


def test_load_fillers_direct_yaml_and_missing_file(tmp_path):
    from voice.persona import load_fillers
    f = tmp_path / "t.yaml"
    f.write_text("personas:\n  wang:\n    backchannel: ['嗯……', '啊？']\n", encoding="utf-8")
    assert load_fillers(f) == {"wang": ["嗯……", "啊？"]}
    assert load_fillers(tmp_path / "nope.yaml") == {}


def test_new_yaml_lines_synthesized_on_first_use_old_cache_kept(tmp_path):
    """前 8 条已在缓存里：只补合成新增的条目。"""
    import hashlib
    for line in ONLINE_FIRST8["wang"]:
        (tmp_path / f"v-24000-{hashlib.sha1(line.encode()).hexdigest()[:12]}.pcm").write_bytes(LOUD)
    calls = []

    async def synth(text, voice, sample_rate):
        calls.append(text)
        yield LOUD
    got = asyncio.run(synth_fillers("wang", "v", 24000, synth=synth, cache_dir=tmp_path))
    assert calls == FILLERS["wang"][len(ONLINE_FIRST8["wang"]):] and set(got) == set(FILLERS["wang"])
