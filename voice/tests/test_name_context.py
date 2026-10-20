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
from voice import persona as P
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


def test_transfer_name_amount_unreported_gap():
    """#216 已知缺口（已接受）：对方没报过名字时「转给李四五百块」不在共享规则内，原样输出。"""
    assert not find_name_context("转给李四五百块")
    assert run("转给李四五百块") == "转给李四五百块"


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("echo,want", [
    ("转给李四五百块", "转给那个名字五百块"),
    ("给李四三千", "给那个名字三千"),
    ("李四两万块", "那个名字两万块"),
    ("转给李四五百", "转给那个名字五百"),
    ("李四，五百块", "那个名字，五百块"),
])
def test_reported_name_then_amount_keeps_digit(echo, want, step):
    """#222：报过名字后，名字后面紧跟的中文金额不被吞字（原来念「转给那个名字百块」）。"""
    p, _ = _reported("收款人叫李四")
    assert run(echo, red=p.redactor, refs=["收款人叫李四"], step=step) == want


@pytest.mark.parametrize("text,want", [
    ("王*五", "那个名字"),            # 中间打码的三字名，「五」是名字里的字，照旧吃掉
    ("王*五是吧", "那个名字是吧"),
    ("户名王*五", "户名那个名字"),
    ("转给王*五", "转给那个名字"),
    ("王*二", "那个名字"),
    ("李*五百块", "那个名字五百块"),   # 数字后面还跟着数字 / 单位：金额，不吃
    ("李*三千元", "那个名字三千元"),
    ("打给张*两千", "打给那个名字两千"),
    ("打给张经理两千", "打给张经理两千"),  # 称呼不是名字，不动
])
def test_single_star_amount_vs_middle_mask(text, want):
    assert P.speakable(text, calm_tts=False) == want
    assert run(text) == want


# ---- #222 追加（情报复查）：报过 / 已打码的名字后面紧跟金额 ----------------------------------------------------
@pytest.mark.parametrize("step", [1, 3])
@pytest.mark.parametrize("echo,want", [
    ("转给李四五百块", "转给那个名字五百块"),
    ("汇给张三三万块", "汇给那个名字三万块"),
])
def test_reported_two_names_amount(echo, want, step):
    p, _ = _reported("收款人叫李四")
    p.redactor.add("name", "张三")
    out = run(echo, red=p.redactor, refs=["收款人叫李四"], step=step)
    assert out == want
    assert "那么些钱" not in out


@pytest.mark.parametrize("step", [1, 3])
def test_reported_name_arabic_amount_no_surname_leak(step):
    """「转给李四500」：不露「李」、不念「你发的那个号」、不留星号。500 本身按 #121 / #167 数字过滤念含糊说法（不在本 PR 改）。"""
    p, _ = _reported("收款人叫李四")
    out = run("转给李四500", red=p.redactor, refs=["收款人叫李四"], step=step)
    assert out.startswith("转给那个名字")
    assert "李" not in out and "你发的那个号" not in out and "*" not in out


@pytest.mark.parametrize("text,want_prefix", [
    ("转给李*五百块", "转给那个名字五百块"),
    ("张**三万块", "那个名字三万块"),
    ("汇给张**三万块", "汇给那个名字三万块"),
    ("李**500", "那个名字"),
    ("转给李**500", "转给那个名字"),
    ("是**明吗", "是那个名字吗"),
    ("张**三", "那个名字"),          # 残名单字照旧吃掉
])
def test_raw_masked_name_amount_chain(text, want_prefix):
    for refs in (None, ()):
        for step in (1, 3):
            out = run(text, refs=refs, step=step)
            assert out.startswith(want_prefix), out
            assert not any(c in out for c in "*＊李张明") and "你发的那个号" not in out


@pytest.mark.parametrize("text", ["卡号是6222**500", "尾号*500"])
def test_number_context_stars_digits_unchanged_semantics(text):
    """号码语境里的星号 + 数字仍按号码念，不当名字。"""
    assert "那个名字" not in P.speakable(text, calm_tts=False)
