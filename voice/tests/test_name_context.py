"""#222：姓名语境里的真名（转给 / 打给 / 汇给 X、是 X 吗、我叫 / 我是 X）在语音链路上的表现。

规则只有一份：core/extractors.json nameRules.nameContext（deepsuck.extractors.find_name_context）。语音不另写正则：
- 骗子说的话：Session.ingest → extract_sensitive 抽出 name → raw_intel → IntelProcessor.call_redact 让 CallRedactor 学到这个名字，
  送进模型的是「我叫张*」；之后机器人复述（「张三是吧」）由 CallRedactor 打码。
- 机器人自己说的：GuardTextFilter → speakable → guard_output 里的 redact_text 走同一条规则，念「那个名字」。
「张三是吧」在对方没报过这个名字时不在共享规则内（见 #223 语音审查），这里只锁住报过之后的行为。"""
import asyncio

import pytest

from deepsuck.engine import Session
from deepsuck.extractors import find_name_context
from deepsuck.refs import heard_refs
from deepsuck.rng import mulberry32
from voice.callredact import CallRedactor
from voice.processors import GuardTextFilter, IntelProcessor
from voice.textagg import ClauseTextAggregator


async def _chain(text, red, refs, step):
    agg = ClauseTextAggregator()
    f = GuardTextFilter(red, refs=(lambda: refs) if refs is not None else None)
    segs = []
    for i in range(0, len(text), step):
        async for a in agg.aggregate(text[i:i + step]):
            segs.append(a.text)
    last = await agg.flush()
    if last:
        segs.append(last.text)
    return "".join([await f.filter(s) for s in segs])


def run(text, red=None, refs=(), step=1):
    return asyncio.run(_chain(text, red if red is not None else CallRedactor(),
                              heard_refs(list(refs)) if refs is not None else None, step))


BOT_MASKED = {
    "转给李四": "转给那个名字",
    "是李四吗": "是那个名字吗",
    "是李明吗": "是那个名字吗",
    "我叫张三": "我叫那个名字",
}
UNCHANGED = ["我是退休的", "我是他妈", "我是王阿姨", "是马上吗", "是真的吗", "转给银行", "打给客服"]


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("refs", [None, ()])
@pytest.mark.parametrize("text,want", list(BOT_MASKED.items()))
def test_bot_output_name_context_masked(text, want, refs, step):
    assert find_name_context(text), "共享规则应认出这个名字"
    assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("text", UNCHANGED)
def test_not_names_unchanged(text, step):
    assert not find_name_context(text)
    assert run(text, step=step) == text


def _reported(said):
    s = Session(scenario="police", persona="wang", rng=mulberry32(5), now=lambda: 0)
    p = IntelProcessor(s)
    a = p.call_redact(s.ingest(said))
    return p, a


@pytest.mark.parametrize("said,name,echo,want", [
    ("我叫张三", "张三", "张三是吧", "那个名字是吧"),
    ("转给李四", "李四", "李四是吧", "那个名字是吧"),
    ("是李四吗", "李四", "是李四吗", "是那个名字吗"),
])
def test_scammer_said_name_learned_and_echo_masked(said, name, echo, want):
    p, a = _reported(said)
    assert name not in a["redacted"]  # 送进模型的已打码
    assert name not in "".join(m["text"] for m in p.session.messages if m.get("role") == "scammer")
    for step in (1, 3):
        assert run(echo, red=p.redactor, refs=[said], step=step) == want


def test_zhangsan_shiba_not_in_shared_rule():
    """对方没报过时「张三是吧」不在共享规则内，原样输出（模型自己编的名字）；记录在案，见 #223 语音审查。"""
    assert not find_name_context("张三是吧")
    assert run("张三是吧") == "张三是吧"


@pytest.mark.xfail(strict=False, reason="#216 已知缺口：「转给李四五百块」名字后紧跟金额不在共享规则内；"
                                       "报过名字后 _unmask_names 单星号分支吞掉「五」，念「转给那个名字百块」（main 上就有）")
def test_transfer_name_amount():
    assert run("转给李四五百块") != "转给李四五百块"
    p, _ = _reported("收款人叫李四")
    assert run("转给李四五百块", red=p.redactor, refs=["收款人叫李四"]) == "转给那个名字五百块"
