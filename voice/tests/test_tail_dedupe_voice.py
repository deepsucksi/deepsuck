"""#175：语音链路接入 dedupe_tail（#153）——按通话记最近 3 轮尾句，送 TTS 前去重；删空且无兜底时整轮不出声。"""
import asyncio

import pytest
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from deepsuck.personas import PERSONA_BY_ID, TAIL_DEDUPE
from voice.callredact import CallRedactor
from voice.processors import BotTextTap, IntelProcessor, TailDedupeProcessor, TailHistory

ASK = "ask_repeat"


def _plain(pid):
    return [x for x in PERSONA_BY_ID[pid]["templates"][ASK] if "{" not in x]


def _picked(pid):
    """#188：兜底只从 tailDedupe.fallbackPick 标了的 ask_repeat 里挑（不带具体场景、不带变量、最多一位数字）。"""
    lst = PERSONA_BY_ID[pid]["templates"][ASK]
    return [lst[i] for i in TAIL_DEDUPE["fallbackPick"][pid]]


def _turn(*chunks):
    return [LLMFullResponseStartFrame(), *[LLMTextFrame(c) for c in chunks], LLMFullResponseEndFrame()]


def _replies(frames):
    """下游（TTS 方向）按轮收到的文字；只有 Start…End 包着的才算一轮。"""
    out, cur = [], None
    for f in frames:
        if isinstance(f, LLMFullResponseStartFrame):
            cur = []
        elif isinstance(f, LLMTextFrame):
            assert cur is not None, "文字必须在 Start/End 之间"
            cur.append(f.text)
        elif isinstance(f, LLMFullResponseEndFrame):
            out.append("".join(cur))
            cur = None
    assert cur is None
    return out


def _run(proc, *turns):
    frames = [f for t in turns for f in t]
    down, _ = asyncio.run(run_test(proc, frames_to_send=frames))
    return down


def test_same_call_cross_turn_dedupe():
    p = TailDedupeProcessor("wang")
    down = _run(p, _turn("好的。", "你再说一遍。"), _turn("我在听呢。", "你再", "说一遍！"), _turn("那你等一下。"))
    assert _replies(down) == ["好的。你再说一遍。", "我在听呢。", "那你等一下。"]
    assert p.history.recent() == ["你再说一遍。", "我在听呢。", "那你等一下。"]  # 记的是实际说出口的尾句
    assert p.rewritten == 1 and p.dropped == 0


def test_cascade_and_window_of_three():
    p = TailDedupeProcessor("wang")
    down = _run(p, _turn("一。"), _turn("二。"), _turn("三。"), _turn("四。"),
                _turn("一。"),            # 已经超出最近三轮（二三四），照说
                _turn("五。三。四。"))    # 尾句四、新尾句三都重复，连删两句
    assert _replies(down) == ["一。", "二。", "三。", "四。", "一。", "五。"]


def test_streams_safe_sentences_before_end():
    """不是最近尾句前缀的句子不压着：第一句在 End 之前就放行（不拖首包延迟）。"""
    p = TailDedupeProcessor("wang")
    down = _run(p, _turn("你再说一遍。"), _turn("哎", "呀，", "我找找。", "你再说一遍。"))
    texts = [f.text for f in down if isinstance(f, LLMTextFrame)]
    assert texts[:4] == ["你再说一遍。", "哎", "呀，", "我找找。"]  # 逐块透传
    assert _replies(down)[1] == "哎呀，我找找。"


def test_different_calls_independent():
    a, b = TailDedupeProcessor("wang"), TailDedupeProcessor("wang")
    _run(a, _turn("你再说一遍。"))
    assert _replies(_run(b, _turn("你再说一遍。"))) == ["你再说一遍。"]  # b 是另一通电话，不受 a 影响
    assert len(a.history) == 1 and len(b.history) == 1 and a.history is not b.history


@pytest.mark.parametrize("pid", ["chen", "wang", "mom"])  # mom 是 chen 的别名
def test_emptied_reply_falls_back_to_ask_repeat(pid):
    p = TailDedupeProcessor(pid)
    pool = _picked("chen" if pid == "mom" else pid)
    down = _run(p, _turn("行。"), _turn("行！"))
    r = _replies(down)
    assert r[0] == "行。" and r[1] in pool  # 删空后从该人设 fallbackPick 标了的 ask_repeat 里挑（#188）
    assert p.history.recent()[-1] == r[1].strip() or p.history.recent()[-1] in r[1]
    # 确定性：同样的输入同样的结果
    q = TailDedupeProcessor(pid)
    assert _replies(_run(q, _turn("行。"), _turn("行！"))) == r


def test_persona_id_passed_to_dedupe_tail(monkeypatch):
    import voice.processors as vp
    calls = []
    real = vp.dedupe_tail

    def spy(text, recent, persona_id=None):
        calls.append(persona_id)
        return real(text, recent, persona_id)

    monkeypatch.setattr(vp, "dedupe_tail", spy)
    p = TailDedupeProcessor("zheng")
    r = _replies(_run(p, _turn("要得。"), _turn("要得。")))
    assert "zheng" in calls and r[1] in _plain("zheng")


def test_build_pipeline_wires_dedupe_with_persona_and_call_redactor():
    from voice.app import build_pipeline
    from voice.tests.test_latency import _FakeLLM, _session, _Transport
    from voice.processors import FillerProcessor

    s = _session()

    async def go():
        return build_pipeline(_Transport(), s, None, engine="llm", fillers={}, llm=_FakeLLM())
    pl, intel, _ = asyncio.run(go())
    procs = list(pl.processors)
    d = next(x for x in procs if isinstance(x, TailDedupeProcessor))
    assert d.persona_id == s.persona["id"]
    assert d.redactor is intel.redactor  # 同一通电话的打码名单
    idx = {type(x): i for i, x in enumerate(procs)}
    # LLM 之后、填充音 / 会话记录 / TTS 之前
    assert idx[TailDedupeProcessor] < idx[FillerProcessor] < idx[BotTextTap] < idx[type(procs[idx[BotTextTap] + 1])]
    # 每通电话各自一份历史
    pl2, _, _ = asyncio.run(go())
    d2 = next(x for x in pl2.processors if isinstance(x, TailDedupeProcessor))
    assert d2.history is not d.history


def _call(pid):
    s = Session(scenario="refund", persona="wang", now=lambda: 0)
    intel = IntelProcessor(s)
    intel.intent = "slow_walk"
    p = TailDedupeProcessor(pid, redactor=intel.redactor)
    return s, p, Pipeline([p, BotTextTap(intel)])


def _assert_dropped_turn_then_recovers(pid):
    s, p, pl = _call(pid)
    down = _run(pl, _turn("你说啥？"), _turn("你", "说啥？"), _turn("那我去问问我儿子。"))
    # 第二轮删空且无兜底：不发 Start/文字/End，TTS 什么都收不到；会话里也不记这一轮
    assert _replies(down) == ["你说啥？", "那我去问问我儿子。"]
    assert sum(isinstance(f, LLMFullResponseStartFrame) for f in down) == 2
    assert sum(isinstance(f, LLMTextFrame) and not f.text for f in down) == 0  # 不发空串
    assert [m["text"] for m in s.messages if m["role"] == "bot"] == ["你说啥？", "那我去问问我儿子。"]
    assert p.dropped == 1
    assert p.history.recent() == ["你说啥？", "那我去问问我儿子。"]  # 没说出口的一轮不进历史
    assert not p._active and p._sent == 0 and p._full == ""  # 状态已复位


def test_empty_without_persona_id_sends_no_tts_and_next_turn_ok():
    _assert_dropped_turn_then_recovers(None)


def test_empty_when_persona_has_no_plain_ask_repeat(monkeypatch):
    # 兜底只用不带 {变量} 的 ask_repeat：只剩带变量的台词时等于没有兜底
    t = dict(PERSONA_BY_ID["wang"]["templates"])
    t[ASK] = [x for x in t[ASK] if "{" in x]
    assert t[ASK]
    monkeypatch.setitem(PERSONA_BY_ID["wang"], "templates", t)
    _assert_dropped_turn_then_recovers("wang")


def test_redact_before_dedupe():
    r = CallRedactor()
    r.add("name", "张伟")
    p = TailDedupeProcessor("wang", redactor=r)
    out = _replies(_run(p, _turn("是张伟吧？"), _turn("好。", "是张伟吧？")))
    assert out == ["是张伟吧？", "好。"]  # 打码后与上一轮尾句相同，删掉（放出去的原文仍由 TTS 的 GuardTextFilter 打码）
    assert "张伟" not in "".join(p.history.recent())  # 历史只存打码后的


def test_interruption_resets_and_history_window():
    from pipecat.frames.frames import InterruptionFrame
    p = TailDedupeProcessor("wang")
    down = _run(p, _turn("你再说一遍。"),
                [LLMFullResponseStartFrame(), LLMTextFrame("你再"), InterruptionFrame()],
                _turn("我听着呢。"))
    assert _replies(down) == ["你再说一遍。", "我听着呢。"]
    h = TailHistory(window=3)
    for x in ["a。", "b。", "", "c。", "d。"]:
        h.push(x)
    assert h.recent() == ["b。", "c。", "d。"]


@pytest.mark.parametrize("pid", ["wang", "chen", "lin", "zheng"])
def test_fallback_never_scene_specific(pid):
    # #188：语音链路删空兜底不会拿到「哪个按钮？红的绿的？」这类带具体场景的句子
    ok = _picked(pid)
    for t in ("行。", "好的吧。", "嗯，我听着呢。"):
        r = _replies(_run(TailDedupeProcessor(pid), _turn(t), _turn(t)))
        assert r[0] == t and (len(r) == 1 or r[1] in ok), r
    assert "哪个按钮？红的绿的？你说清楚点阿姨照着按。" not in _picked("wang")
