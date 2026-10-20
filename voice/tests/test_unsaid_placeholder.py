"""#219（负责人裁定保留「那个名字」）：#195 的 drop_unsaid 只改模型自己写的代称，不改 unmask / _unmask_names /
drop_name_explain 换出来的「那个名字」「那个号」占位，也不剩光秃秃的「名字」。
整条链路：GuardTextFilter（redactor → drop_unsaid → speakable：guard_output → unmask / _unmask_names）。"""
import asyncio
import re

import pytest
from pipecat.processors.aggregators.llm_context import LLMContext

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.processors import GuardTextFilter, IntelProcessor

BARE = re.compile(r"(?<!那个)名字")
CASES = [
    ("户名***", "户名那个名字"),
    ("收款人姓**明", "收款人那个名字"),
    ("他姓**明对吧", "他是那个名字对吧"),
    ("收款人**的卡", "收款人那个名字的卡"),
    ("户名 —— **明", "户名 —— 那个名字"),
    ("收款人是弓长张，伟大的伟对吧", "收款人是那个名字对吧"),
]


def _proc(reported: bool):
    s = Session(scenario="police", persona="wang", rng=mulberry32(5), now=lambda: 0)
    p = IntelProcessor(s, context=LLMContext([{"role": "system", "content": "x"}]))
    if reported:
        p.call_redact(s.ingest("卡号6222021234567890128，户名张三丰。"))
    else:
        s.ingest("您名下有一张银行卡涉嫌洗钱。")
    return s, p


@pytest.mark.parametrize("reported", [False, True], ids=["没报过户名", "报过户名"])
@pytest.mark.parametrize("text,want", CASES)
def test_placeholder_survives_drop_unsaid(reported, text, want):
    s, p = _proc(reported)
    assert ("name" in p.heard_refs()) is reported
    assert P.speakable(text, calm_tts=False) == want
    out = asyncio.run(GuardTextFilter(p.redactor, refs=p.heard_refs).filter(text))
    assert P.NAME_PHRASE in out and not BARE.search(out), out
    assert "*" not in out and "＊" not in out and "明" not in out and "伟" not in out


def test_model_written_proxy_still_dropped_when_unsaid():
    """模型自己写的「户名是那个名字」对方没报过时仍换成直说（#184 行为不变），同一句里的打码占位保留。"""
    s, p = _proc(False)
    out = asyncio.run(GuardTextFilter(p.redactor, refs=p.heard_refs).filter("户名是那个名字？收款人姓**明"))
    assert out.startswith("户名叫什么"), out
    assert out.endswith("收款人那个名字"), out
    assert not BARE.search(out.replace("户名叫什么", "")), out
