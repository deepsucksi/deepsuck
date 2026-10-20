"""#216 P0：对方从没报过户名时的三处露字 + 带空格的打码姓名，走整条链路锁住。

用例 tests/fixtures/unsaid_leaks.json（与网页、Python 共用）。链路：ClauseTextAggregator 流式分句 → GuardTextFilter
（CallRedactor → drop_unsaid → speakable：guard_output → unmask / _unmask_names），以及 BotTextTap（会话记录）。
refs 为空（开场前还没接上 heard_refs）、没报过户名、报过户名三种都跑；逐字 / 每 3 字送一块，还有中途打断。
判定：输出里不能有真名（李四、王志强、张三丰）、残字「明」、任何星号；不能把「那个名字」念成「那个号」。"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.callredact import CallRedactor
from voice.processors import BotTextTap, GuardTextFilter, IntelProcessor
from voice.textagg import ClauseTextAggregator

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/unsaid_leaks.json").read_text(encoding="utf-8"))
NAMES = re.compile(r"李四|王志强|张三丰|[*＊]")
P0 = [c for c in F["cases"] if c.get("p0")]
LEAK_TEXTS = [c["text"] for c in F["cases"] if c["refs"] == ["name"] and c["text"] != c["redacted"] or c.get("p0")]


def _proc(mode: str):
    s = Session(scenario="police", persona="wang", rng=mulberry32(5), now=lambda: 0)
    p = IntelProcessor(s, context=LLMContext([{"role": "system", "content": "x"}]))
    if mode == "reported":
        p.call_redact(s.ingest("卡号6222021234567890128，户名张三丰。"))
    else:
        s.ingest("您名下有一张银行卡涉嫌洗钱。")

    async def _n(_m):
        return None
    p.notify = _n
    return s, p


async def _guard(p, text, refs, step, interrupt_at=None):
    agg, g, out = ClauseTextAggregator(), GuardTextFilter(p.redactor, refs=refs), []
    for k, i in enumerate(range(0, len(text), step)):
        if interrupt_at is not None and k == interrupt_at:
            await g.handle_interruption()
        async for a in agg.aggregate(text[i:i + step]):
            out.append(await g.filter(a.text))
    last = await agg.flush()
    if last:
        out.append(await g.filter(last.text))
    return "".join(out)


async def _tap(s, p, text, monkeypatch):
    t = BotTextTap(p)

    async def push(_f, _d):
        return None

    async def nop(self, _f, _d):
        return None
    t.push_frame = push
    monkeypatch.setattr(FrameProcessor, "process_frame", nop)
    await t.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    for i in range(0, len(text), 3):
        await t.process_frame(LLMTextFrame(text[i:i + 3]), FrameDirection.DOWNSTREAM)
    await t.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)
    return [m["text"] for m in s.messages if m.get("role") != "scammer"][-1]


def _ok(text, out):
    assert not NAMES.search(out), (text, out)
    assert "那个号明" not in out and not re.search(r"名字明|明[吗？]?$", out), (text, out)
    if "户名" in text and "卡号" not in text and "尾号" not in text:
        assert "那个号" not in out, (text, out)


@pytest.mark.parametrize("mode", ["refs_none", "unreported", "reported"])
@pytest.mark.parametrize("step", [1, 3])
@pytest.mark.parametrize("text", LEAK_TEXTS)
def test_guard_chain_no_leak(mode, step, text):
    s, p = _proc("reported" if mode == "reported" else "unreported")
    refs = None if mode == "refs_none" else p.heard_refs
    assert ("name" in p.heard_refs()) is (mode == "reported")
    _ok(text, asyncio.run(_guard(p, text, refs, step)))


@pytest.mark.parametrize("text", LEAK_TEXTS)
def test_guard_chain_interrupted(text):
    _, p = _proc("unreported")
    _ok(text, asyncio.run(_guard(p, text, p.heard_refs, 2, interrupt_at=2)))


@pytest.mark.parametrize("mode", ["unreported", "reported"])
@pytest.mark.parametrize("text", LEAK_TEXTS)
def test_bot_text_tap_no_leak(mode, text, monkeypatch):
    s, p = _proc(mode)
    _ok(text, asyncio.run(_tap(s, p, text, monkeypatch)))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["text"])
def test_speakable_matches_fixture(case):
    assert P.speakable(case["text"], calm_tts=False) == case["voice"]


def test_real_name_not_restored_by_unmask_names():
    """「对方叫李四」打码成「对方叫李*」以后，_unmask_names 只会换成「那个名字」，不会把真名还原回来（它手里没有原值）。"""
    _, p = _proc("unreported")
    out = asyncio.run(_guard(p, "对方叫李四是吧", p.heard_refs, 1))
    assert out == "对方叫那个名字是吧"
    assert P._unmask_names("对方叫李*是吧") == "对方叫那个名字是吧"
    assert "四" not in P.speakable("对方叫李四是吧", calm_tts=False)


def test_spaced_name_with_call_redactor():
    """语音探针：对方报过张伟明以后，人设把名字逐字隔开说（「好，张 伟 明」「张·伟·明」）也要打码。"""
    r = CallRedactor()
    r.add("name", "张伟明")
    for t in ("好，张 伟 明", "张·伟·明，对吧", "伟　明是吧"):
        out = P.speakable(r.apply(t), calm_tts=False)
        assert not re.search("伟|明|[*＊]", out), (t, out)


@pytest.mark.parametrize("text", ["138 **** 1234", "6222 **** **** 1234"])
def test_number_separators_stay_number(text):
    out = P.speakable(text, calm_tts=False)
    assert "名字" not in out and not re.search(r"[*＊0-9]", out), out
