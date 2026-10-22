"""#249：语音各出口（redact_line、speakable、guard_output、CallRedactor → GuardTextFilter 流式）对同音拆字 + 名 + 数字不露名，
白名单普通词不误伤。夹具见 tests/fixtures/homophone_split_249.json。"""
import asyncio
import json
from pathlib import Path

import pytest

from voice.callredact import CallRedactor, redact_line
from voice.persona import guard_output, speakable
from voice.processors import GuardTextFilter
from voice.textagg import ClauseTextAggregator

CASES = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/homophone_split_249.json").read_text("utf-8"))["cases"]
# 夹具名：每句里要遮住的名（姓之后的字）
GIVEN = {"工厂张三五百块转给我": "张三", "收款人尔东陈伟明500": "陈伟明", "尔东陈伟明500": "陈伟明", "工长张三五百块": "张三",
         "转给工厂张伟明1000元": "张伟明", "尔东陈伟明五百块": "陈伟明", "木子里小红300": "里小红", "龚厂长伟明两万": "长伟明",
         "木子李子轩500": "李子轩", "弓长张三五百块": "张三"}
KEEP_WORDS = {"工厂张贴通知三份": "张贴", "工厂张家港二厂明天停工": "张家港", "我在尔东陈列馆2楼等你": "陈列馆",
              "按立早章程第3条办理": "章程", "木子李子5斤一共30元": "李子", "口天吴江路88号取件": "吴江路", "弓长张贴500份传单": "张贴",
              "尔东陈列室3号": "陈列室", "工厂张江路100号": "张江路"}


async def _chain(t, red):
    agg, f, segs = ClauseTextAggregator(), GuardTextFilter(red), []
    for i in range(0, len(t), 3):
        async for a in agg.aggregate(t[i:i + 3]):
            segs.append(a.text)
    last = await agg.flush()
    if last:
        segs.append(last.text)
    return "".join([await f.filter(x) for x in segs])


def _exits(t, name=None):
    red = CallRedactor()
    if name:
        red.add("name", name)
    return {"redact_line": redact_line(t), "speakable": speakable(t), "guard_output": guard_output(t),
            "callredact": asyncio.run(_chain(t, red))}


@pytest.mark.parametrize("t", sorted(GIVEN))
def test_mask_all_exits(t):
    full = GIVEN[t]
    for k, out in _exits(t).items():
        assert full[1:] not in out.replace("那个名字", ""), (k, t, out)


@pytest.mark.parametrize("t", sorted(KEEP_WORDS))
def test_whitelist_not_masked(t):
    for k, out in _exits(t).items():
        if k == "callredact":
            continue  # 流式过滤按通话打码，没学到姓名时只换数字
        assert KEEP_WORDS[t] in out, (k, t, out)
        assert "那个名字" not in out, (k, t, out)
