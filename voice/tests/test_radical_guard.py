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
