"""#186：ASR 把卡号 / 手机号切成几段时，送给大模型的文字里片段本身也要打码；情报提取仍用拼好的完整号码。
回归来自本地号码探针（「卡号是62220212。」「345678。」「*0123。」前两段原样进了模型）。号码均为假号。"""
import asyncio
import re

import pytest
from pipecat.frames.frames import LLMContextFrame, TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from voice.callredact import redact_digit_fragments
from voice.persona import unmask
from voice.processors import ContextGuard, IntelProcessor

DIG = re.compile(r"[0-9０-９]{3,}|[零〇一二三四五六七八九幺]{3,}")

SPLITS = {
    "two": ["卡号是6222021234", "5678901"],
    "three": ["卡号是62220212。", "345678。", "9010123。"],
    "space": ["我卡号 6222 0212", "3456 7890 123"],
    "dunhao": ["账号是6222、0212、3456", "7890、123"],
    "chinese": ["卡号是六二二二零二一二", "三四五六七八九零一二三"],
    "phone": ["我手机号138。", "0013。", "8000"],
    "nokw": ["你记一下", "62220212", "3456789012"],
}

NEGATIVE = [
    ["退款金额是380元。"],
    ["先转5000块过来"],
    ["卡号你记好了吗", "金额先填200。"],
    ["明天10:30给你回电话"],
    ["卡号报一下", "下午3点前到账"],
    ["打到TRC20的地址"],
    ["两三天就到账"],
    ["我只有300块钱"],
    ["给你退三百八十元"],
    ["2026年10月19日之前办"],
]


def _tf(text):
    return TranscriptionFrame(text=text, user_id="u", timestamp="t")


def _session():
    from deepsuck.rng import mulberry32
    return Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)


def _run(p, texts):
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf(t) for t in texts],
                                   expected_down_frames=[TranscriptionFrame] * len(texts)))
    return [f.text for f in down]


@pytest.mark.parametrize("key", list(SPLITS))
def test_fragments_masked(key):
    out = [unmask(x) for x in redact_digit_fragments(SPLITS[key])]
    for raw, t in zip(SPLITS[key], out):
        assert not DIG.search(t), (key, out)
        assert ("那个号" in t) == bool(DIG.search(raw)), (key, out)


@pytest.mark.parametrize("segs", NEGATIVE)
def test_not_numbers_untouched(segs):
    assert redact_digit_fragments(segs) == segs


def test_core_masked_value_kept():
    """共享核心完整的打码值不动（unmask 读成“尾号0128”）；打了一半的（622202**）补打。"""
    segs = ["卡号是622202*********0128。", "安全账户的卡号是621700********8901。"]
    assert redact_digit_fragments(segs) == segs
    assert unmask(segs[0]) == unmask(redact_digit_fragments(segs)[0])
    assert redact_digit_fragments(["你记一下", "622202**"])[1] == "********"


def test_idempotent_and_unmasked_input():
    once = redact_digit_fragments(SPLITS["three"])
    assert redact_digit_fragments(once) == once
    # 上下文里已经 unmask 过的（「那个号」）也算号码语境，下一段纯数字照打
    assert redact_digit_fragments(["卡号是那个号", "345678"])[1] == "******"


@pytest.mark.parametrize("key", ["two", "three", "space", "phone", "nokw"])
def test_model_input_and_session_have_no_fragments(key):
    s = _session()
    p = IntelProcessor(s, context=LLMContext([{"role": "system", "content": "x"}]), filler_prob=0.0)
    for t in _run(p, SPLITS[key]):
        assert not DIG.search(t), (key, t)
    for m in s.messages:
        if m.get("role") == "scammer":
            assert not DIG.search(m["text"]), (key, m)


def test_cross_turn_split():
    """片段分在两轮（中间人设回了一句）也打。"""
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx, filler_prob=0.0)
    first = _run(p, ["卡号是62220212"])[0]
    ctx.add_message({"role": "user", "content": first})
    ctx.add_message({"role": "assistant", "content": "后面呢…"})
    s.record_bot("后面呢…", "x")
    p2 = IntelProcessor(s, context=ctx, redactor=p.redactor, filler_prob=0.0)  # run_test 每次收尾都发 EndFrame，换一个实例接着跑同一通
    second = _run(p2, ["3456789010123"])[0]
    assert not DIG.search(first) and not DIG.search(second), (first, second)


def test_extraction_rate_unchanged():
    """情报提取不经过片段打码：走 IntelProcessor 与直接 Session.ingest 拿到的情报一样，卡号 / 手机号都拿到。"""
    got = 0
    for key, segs in SPLITS.items():
        plain = _session()
        for t in segs:
            plain.ingest(t)
        s = _session()
        _run(IntelProcessor(s, context=LLMContext([{"role": "system", "content": "x"}]), filler_prob=0.0), segs)
        assert s.raw_intel() == plain.raw_intel(), key
        got += bool(s.raw_intel())
    assert got >= 5


def test_context_guard_fixes_already_pushed_segments():
    """已经进了用户聚合器 / 上下文的原样片段，在调大模型前改掉；系统和助手消息不动。"""
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "卡号规则 123456"},
                      {"role": "user", "content": "卡号是62220212。 345678。 那个号。"},
                      {"role": "assistant", "content": "你再说一遍"},
                      {"role": "user", "content": "金额先填200。"}])
    p = IntelProcessor(s, context=ctx, filler_prob=0.0)
    asyncio.run(run_test(ContextGuard(p), frames_to_send=[LLMContextFrame(context=ctx)],
                         expected_down_frames=[LLMContextFrame]))
    msgs = ctx.get_messages()
    assert msgs[0]["content"] == "卡号规则 123456"
    assert not DIG.search(msgs[1]["content"]), msgs[1]
    assert msgs[2]["content"] == "你再说一遍"
    assert msgs[3]["content"] == "金额先填200。"
