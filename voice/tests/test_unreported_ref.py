"""#181（#173 子 issue）：对方还没报过号码 / 户名时，语音侧拼的提示词要写明不说“那个号”“那个名字”、要直接问；
例句里带这两个说法的这一轮不选。只在相关话题对方提到后才写（#4），闲聊时不出现。回归来自生产探针 XSIBKTYQ。"""
import re

from pipecat.processors.aggregators.llm_context import LLMContext

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.processors import IntelProcessor
from voice.tests.test_no_leak import FORBIDDEN

CARD = "6222021234567890128"


def _proc(scenario="police", persona="wang"):
    s = Session(scenario=scenario, persona=persona, rng=mulberry32(5), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    return s, IntelProcessor(s, context=ctx), ctx


def _turn(ctx):
    msgs = ctx.get_messages()
    assert msgs[-1]["role"] == "system"
    return msgs[-1]["content"]


def test_small_talk_has_no_unreported_line():
    s, p, ctx = _proc("pig", "lin")
    s.ingest("你好，交个朋友")
    p.update_prompt()
    t = _turn(ctx)
    assert "还没报过" not in t and "那个号" not in t and "那个名字" not in t
    assert not FORBIDDEN.search(t)


def test_bank_mentioned_but_nothing_reported():
    s, p, ctx = _proc()
    s.ingest("你好，我是公安局的。")
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    assert p.unreported() == ["number", "name"]
    p.update_prompt()
    t = _turn(ctx)
    line = next(x for x in t.split("\n") if x.startswith("对方到现在还没报过"))
    assert "卡号" in line and "户名" in line and "“那个号”" in line and "“那个名字”" in line and "“户名是谁”" in line
    assert not re.search(r"[0-9]", line)
    # 例句里带“那个号”“那个名字”的这一轮不选（警察场景的例句“那个号你说，我先记着”）
    shots = [x for x in t.split("\n") if x.startswith("你：")]
    assert shots and not any("那个号" in x or "那个名字" in x for x in shots)
    # 末尾仍是后续规则；不出现别的话题（电话、钱包）
    assert t.rstrip().endswith(P.FOLLOW_UP_RULE) and "电话" not in line and "钱包" not in line


def test_reported_card_and_name_drop_out():
    s, p, ctx = _proc()
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    p.call_redact(s.ingest(f"把钱转到安全账户，卡号{CARD}。"))
    assert p.unreported() == ["name"]
    p.update_prompt()
    line = next(x for x in _turn(ctx).split("\n") if x.startswith("对方到现在还没报过"))
    assert "户名" in line and "卡号" not in line and "“那个号”" not in line
    p.call_redact(s.ingest("户名张三丰。"))
    assert p.unreported() == []
    p.update_prompt()
    assert "对方到现在还没报过" not in _turn(ctx)


def test_masked_number_in_scammer_text_counts_as_reported():
    s, p, ctx = _proc("refund")
    s.ingest("退款要先转到您的收款账户。")
    p.call_redact(s.ingest("验证码是384715，快告诉我。"))
    assert "number" not in p.unreported()


def test_unreported_line_offline_and_topics():
    assert P.unreported_line(["number", "name"], None) == ""
    assert P.unreported_line(["number", "name"], set()) == ""
    assert "电话" in P.unreported_line(["number"], {"phone"}) and "户名" not in P.unreported_line(["number", "name"], {"phone"})
    assert P.unreported_line([], {"bank"}) == ""
    # 离线 system_prompt（不传 unreported）不变
    assert "对方到现在还没报过" not in P.system_prompt("wang", "police", "generic", topics={"bank"})
