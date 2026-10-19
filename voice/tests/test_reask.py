"""#209（b）：不重复追问——已拿到的字段、上一条刚问过的字段，第一句以后的短问句去掉；缺项里不再列上一条刚问过的。"""
import asyncio

import pytest
from pipecat.processors.aggregators.llm_context import LLMContext

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice.processors import GuardTextFilter, IntelProcessor
from voice.reask import ReaskGuard, asked, drop_reask
from voice.textagg import ClauseTextAggregator

CARD = "6222021234567890128"


def _session(scenario="police"):
    return Session(scenario=scenario, persona="wang", rng=mulberry32(5), now=lambda: 0)


@pytest.mark.parametrize("text,want", [
    ("卡号多少", {"bank"}), ("户名是谁？", {"name"}), ("你报一下卡号", {"bank"}), ("那钱退到哪个卡", set()),
    ("还没弄好，卡号多少", {"bank"}), ("电话多少", {"phone"}), ("链接发我一下", {"url"}),
    ("我在找手机银行，你等一下我这边信号不好，卡号你再说一遍", {"bank"}),  # 按小句看，最后一小句是问卡号
    ("我在找手机银行你等一下我这边信号不好卡号你再说一遍", set()),  # 不分句的长句不算
    ("等一下啊。", set()),
])
def test_asked(text, want):
    assert asked(text) == want


@pytest.mark.parametrize("text,have,last,want", [
    ("还没弄好。卡号多少", set(), {"bank"}, "还没弄好。"),             # 上一条刚问过卡号
    ("还没弄好。卡号多少", {"bank"}, set(), "还没弄好。"),             # 卡号已经拿到
    ("还没弄好。户名是谁", set(), {"bank"}, "还没弄好。户名是谁"),     # 问的是别的字段，照留
    ("卡号多少", set(), {"bank"}, "卡号多少"),                         # 只有一句不去，免得整条变空
    ("手机…在屋里呢。", set(), {"bank"}, "手机…在屋里呢。"),
    ("嗯，我找找。卡号多少？户名是谁？", {"bank"}, {"name"}, "嗯，我找找。"),
])
def test_drop_reask(text, have, last, want):
    assert drop_reask(text, have, last) == want


def _segments(text):
    async def run():
        agg, out = ClauseTextAggregator(min_clause_chars=6), []
        for ch in text:
            async for a in agg.aggregate(ch):
                out.append(a.text)
        last = await agg.flush()
        return out + ([last.text] if last else [])
    return asyncio.run(run())


@pytest.mark.parametrize("text", ["还没弄好。卡号多少", "等一下啊…… 卡号多少", "卡号多少", "转，还没弄好，卡号多少",
                                  "嗯，我找找。卡号多少？户名是谁？"])
def test_tts_segments_match_record(text):
    """送 TTS 分段过和会话记录整条过结果一致（去标点后比）。"""
    s = _session()
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    s.record_bot("你说吧，卡号多少", "x")  # 上一条问过卡号
    g = ReaskGuard(s)
    f = GuardTextFilter(None, reask=g)
    spoken = "".join(asyncio.run(f.filter(x)) for x in _segments(text))
    rec = g.text(text)
    norm = lambda t: "".join(c for c in t if c not in " ，,。…？?")
    assert norm(spoken) == norm(rec), (spoken, rec)
    asyncio.run(f.handle_interruption())


def test_have_from_session():
    s = _session()
    g = ReaskGuard(s)
    s.ingest(f"把钱转到安全账户，卡号{CARD}。")
    assert "bank" in g.have()
    assert g.text("好的我记一下。卡号多少") == "好的我记一下。"


def test_missing_skips_field_asked_last_turn():
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx)
    p.reask = ReaskGuard(s)
    s.ingest("您名下有一张银行卡涉嫌洗钱，要转到安全账户。")
    p.update_prompt()
    turn = ctx.get_messages()[-1]["content"]
    assert "收款银行卡号" in turn
    s.record_bot("转账户…卡号多少", "x")
    s.ingest("你快点。")
    p.update_prompt()
    turn = ctx.get_messages()[-1]["content"]
    assert "收款银行卡号" not in turn and "收款人姓名" in turn
