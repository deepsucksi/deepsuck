"""#163 三审：拆字报姓（含 ASR 同音写法）紧接金额 / 数字 / 卡号 / 手机号，前面配「转给」「收款人」等，
refs、语音 speakable、按通话打码（CallRedactor → GuardTextFilter 流式）都不露姓。web 出口见 tests/split_digits_grid.test.js（同一网格）。
ASR 同音写法后面直接连名（「尔东陈伟明500」）与「尔东陈列馆」分不开，记 #216，不在网格里。"""
import asyncio
import itertools

import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.refs import mask_names, speak_masked
from voice.callredact import CallRedactor
from voice.persona import speakable
from voice.processors import GuardTextFilter
from voice.textagg import ClauseTextAggregator

SP = {"弓长张": "张", "木子李": "李", "耳东陈": "陈", "口天吴": "吴", "立早章": "章", "龚厂长": "张", "工长张": "张", "尔东陈": "陈"}
EXACT = ("弓长张", "木子李", "耳东陈", "口天吴", "立早章")
LEADS = ["", "转给", "收款人", "收款人是", "户名", "打给", "汇给"]
TAILS = ["五百块", "三五百块", "一千元", "两万", "500", "1000元", "6222021234567890123", "，卡号6222021234567890123",
         "13812345678", "，手机13812345678", "，500块"]
GRID = [(l + s + g + t, s) for l, s, t in itertools.product(LEADS, SP, TAILS) for g in (("", "三", "伟明") if s in EXACT else ("",))]


def refs_exit(t):
    s = mask_names(t)
    return speak_masked(redact_text(s, extract_sensitive(s)))


async def _chain(t, red):
    agg, f, segs = ClauseTextAggregator(), GuardTextFilter(red), []
    for i in range(0, len(t), 3):
        async for a in agg.aggregate(t[i:i + 3]):
            segs.append(a.text)
    last = await agg.flush()
    if last:
        segs.append(last.text)
    return "".join([await f.filter(x) for x in segs])


def _leak(out, sp):
    o = out.replace("那个名字", "")
    return SP[sp] in o or sp[:2] in o


def test_grid_size():
    assert len(GRID) >= 1000


@pytest.mark.parametrize("t,sp", GRID, ids=[g[0] for g in GRID])
def test_split_digits_no_surname(t, sp):
    red = CallRedactor()
    red.add("name", SP[sp] + "伟")
    for name, out in (("refs", refs_exit(t)), ("speakable", speakable(t)), ("callredact", asyncio.run(_chain(t, red)))):
        assert not _leak(out, sp), (name, t, out)
