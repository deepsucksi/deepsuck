"""#163：偏旁说法、没有提示词的单段解释在语音出口（guard_output / speakable）和按通话打码（CallRedactor）里不露姓名。"""
import re

import pytest

from voice.callredact import CallRedactor
from voice.persona import guard_output, speakable

LEAKS = ["弓长张，单人旁一个韦", "弓长张，单人旁一个韦，日字旁一个月的明", "户名张伟，单人旁一个韦", "三点水的江",
         "三点水一个工的江", "弓长张，三点水的江", "木子李，草字头的花", "伟大的那个伟字", "李子的李",
         "张伟晨，伟大的伟", "张伟晨，伟大的伟，早晨的晨"]
BAD = re.compile("韦|江|工|花|伟|晨|旁一个|点水|字头|字旁|李子|弓长|那个号")
KEEP = ["伟大的祖国", "三点水很重要", "李子熟了", "单人旁的字很多", "草字头的植物", "明天的会别迟到"]


@pytest.mark.parametrize("t", LEAKS)
def test_voice_exit_no_leak(t):
    for out in (guard_output(t), speakable(t)):
        assert not BAD.search(out), (t, out)
        assert "那个名字" in out


@pytest.mark.parametrize("t", KEEP)
def test_voice_exit_keeps_plain(t):
    assert guard_output(t) == t


def test_callredact_radical_uses_known_name():
    r = CallRedactor()
    r.add("name", "张伟明")
    assert r.apply("单人旁一个韦，日字旁一个月的明") == "张**"
    assert r.apply("三点水很重要") == "三点水很重要"


def test_callredact_raw_bare_stars_read_as_name():
    """共享核心把单段解释打成纯星号（「对，****。」）时，按原文换成所属姓名的打码值，不读成“那个号”。"""
    r = CallRedactor()
    r.add("name", "张伟晨")
    assert r.apply("对，****。", raw="对，早晨的晨。") == "对，张**。"
    assert r.apply("卡号****", raw="卡号1234") == "卡号****"  # 原文没有解释串时不动


# #163 复审（负责人：任何露姓都在本 PR 修）：逐字解释 / 拆字前面的姓名、残姓并进「那个名字」，整句不念出姓
SURNAME_CASES = [
    ("我叫张伟，伟大的伟", "我叫那个名字"),
    ("我是张伟，伟大的伟", "我是那个名字"),
    ("我叫张伟晨，伟大的伟，早晨的晨", "我叫那个名字"),
    ("张伟晨，伟大的伟，早晨的晨", "那个名字"),
    ("我姓张，弓长张", "我姓那个名字"),
    ("我姓张，弓长张，伟大的伟", "我姓那个名字"),
    ("我姓李，木子李", "我姓那个名字"),
    ("收款人李四，木子李", "收款人那个名字"),
    ("收款人李四，木子李，四个的四", "收款人那个名字"),
    ("户名张伟，单人旁一个韦", "户名那个名字"),
    ("收款人是张伟，伟大的伟对吧", "收款人是那个名字对吧"),
]


@pytest.mark.parametrize("t,want", SURNAME_CASES)
def test_voice_exit_no_surname(t, want):
    for out in (guard_output(t), speakable(t)):
        assert out == want, (t, out)
        assert not re.search("[张李伟晨四]|[*＊]", out), (t, out)


@pytest.mark.parametrize("t,_want", SURNAME_CASES)
def test_voice_stream_no_surname(t, _want):
    """逐字、每 3 字流式送进 ClauseTextAggregator → GuardTextFilter，各分句拼起来也不露姓。"""
    import asyncio

    from voice.processors import GuardTextFilter
    from voice.textagg import ClauseTextAggregator

    async def chain(step):
        agg, f, segs = ClauseTextAggregator(), GuardTextFilter(CallRedactor()), []
        for i in range(0, len(t), step):
            async for a in agg.aggregate(t[i:i + step]):
                segs.append(a.text)
        last = await agg.flush()
        if last:
            segs.append(last.text)
        return "".join([await f.filter(x) for x in segs])
    for step in (1, 3, len(t)):
        out = asyncio.run(chain(step))
        assert not re.search("[张李伟晨四]|[*＊]", out), (t, step, out)


@pytest.mark.parametrize("t", ["告诉我那个名字", "高那个名字呢", "你说的那个名字我没记住"])
def test_absorb_keeps_existing_phrase(t):
    assert guard_output(t) == t
