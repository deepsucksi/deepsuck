import asyncio

from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from voice.processors import BotTextTap, GuardTextFilter, IntelProcessor, synth_fillers

CARD = "6222000012345678901"


def _tf(text):
    return TranscriptionFrame(text=text, user_id="u", timestamp="t")


def _session():
    from deepsuck.rng import mulberry32
    return Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)


def test_intel_llm_mode_redacts_and_updates_prompt():
    msgs = []

    async def notify(m):
        msgs.append(m)

    ctx = LLMContext([{"role": "system", "content": "old"}])
    p = IntelProcessor(_session(), context=ctx, notify=notify, fillers={"哎": b"\x00\x00" * 240}, filler_prob=1.0,
                       rng=lambda: 0.0)
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf(f"您好我是淘宝客服，请转到安全账户，卡号{CARD}")],
                                   expected_down_frames=[OutputAudioRawFrame, TranscriptionFrame]))
    assert CARD not in down[1].text and "*" not in down[1].text and "8901" not in down[1].text and "那个号" in down[1].text  # #121：大模型只看到“那个号”，不见星号也不见尾号
    sysmsg = ctx.get_messages()[0]
    assert sysmsg["role"] == "system" and "王阿姨" in sysmsg["content"]
    kinds = [m["type"] for m in msgs]
    assert "scammer" in kinds and "state" in kinds
    sc = next(m for m in msgs if m["type"] == "scammer")
    assert sc["intent"] == "confirm_intel" and sc["newIntel"][0]["type"] == "bank_card"
    assert all(CARD not in str(m) for m in msgs)  # 推给浏览器的也都是脱敏值


def test_intel_rule_mode_speaks_without_llm():
    msgs = []

    async def notify(m):
        msgs.append(m)

    s = _session()
    p = IntelProcessor(s, notify=notify, mode="rule")
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf("你的快递丢了，我们给你理赔")],
                                   expected_down_frames=[TTSSpeakFrame]))
    assert down[0].text
    assert [m["role"] for m in s.messages] == ["scammer", "bot"]
    assert any(m["type"] == "bot" for m in msgs)


def test_empty_transcript_dropped():
    p = IntelProcessor(_session(), mode="rule")
    asyncio.run(run_test(p, frames_to_send=[_tf("  ")], expected_down_frames=[]))


def test_bot_text_tap_records_guarded_reply():
    msgs = []

    async def notify(m):
        msgs.append(m)

    s = _session()
    intel = IntelProcessor(s, notify=notify)
    intel.intent = "slow_walk"
    tap = BotTextTap(intel)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("哎，验证码是"), LLMTextFrame("654321吧（笑）"), LLMFullResponseEndFrame()]
    asyncio.run(run_test(tap, frames_to_send=frames,
                         expected_down_frames=[LLMFullResponseStartFrame, LLMTextFrame, LLMTextFrame, LLMFullResponseEndFrame]))
    bot = s.messages[-1]
    assert bot["role"] == "bot" and bot["intent"] == "slow_walk"
    assert "654321" not in bot["text"] and "笑" not in bot["text"]
    assert any(m["type"] == "bot" for m in msgs)


def test_guard_text_filter():
    assert asyncio.run(GuardTextFilter().filter("**好的** 尾号 ****7890")) == "好的 后面几位没听清"


def test_synth_fillers_cached(tmp_path):
    calls = []

    async def synth(text, voice, sample_rate):
        calls.append(text)
        yield b"\x00\x10" * 10

    a = asyncio.run(synth_fillers("wang", "longlaoyi_v3", 24000, synth=synth, cache_dir=tmp_path))
    n = len(calls)
    b = asyncio.run(synth_fillers("wang", "longlaoyi_v3", 24000, synth=synth, cache_dir=tmp_path))
    assert a == b and len(a) == n > 0 and len(calls) == n  # 第二次全走缓存


def test_synth_fillers_failure_is_soft(tmp_path):
    async def synth(text, voice, sample_rate):
        raise RuntimeError("no network")
        yield b""

    assert asyncio.run(synth_fillers("wang", "v", 24000, synth=synth, cache_dir=tmp_path)) == {}


def test_synth_fillers_cached_only_and_inplace(tmp_path):
    from voice.guard import VoiceBudget
    from voice.processors import fillers_missing

    calls = []

    async def synth(text, voice, sample_rate):
        calls.append(text)
        yield b"\x00\x10" * 10

    assert asyncio.run(synth_fillers("wang", "v", 24000, synth=synth, cache_dir=tmp_path, cached_only=True)) == {}
    assert calls == []
    have = {}
    tk = VoiceBudget(cap_cny=1).reserve(0.5)
    asyncio.run(synth_fillers("wang", "v", 24000, synth=synth, cache_dir=tmp_path, out=have, meter=tk))
    assert have and not fillers_missing("wang", "v", 24000, have)
    assert tk.usage["tts_chars"] == sum(len(t) for t in calls)  # 填充音合成也计入预算


def test_intel_processor_closing_drops_transcripts():
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from deepsuck.engine import Session

    p = IntelProcessor(Session(scenario="refund", persona="wang"), mode="rule")
    p.closing = True
    pushed = []

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)
    p.push_frame = push

    async def go():
        import pipecat.processors.frame_processor as fp
        orig = fp.FrameProcessor.process_frame

        async def noop(self, frame, direction):
            return None
        fp.FrameProcessor.process_frame = noop
        try:
            await p.process_frame(TranscriptionFrame(text="卡号6222020200112233445", user_id="u", timestamp="t"),
                                  FrameDirection.DOWNSTREAM)
        finally:
            fp.FrameProcessor.process_frame = orig
    asyncio.run(go())
    assert pushed == [] and p.session.stats()["scammerMessages"] == 0
