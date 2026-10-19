"""#184（#181，#173 子 issue）：对方还没报过号码 / 户名、但已经提到相关话题时，可变部分末尾写一行要直接问；
这一行本身不出现代称说法（共用用例 tests/fixtures/unsaid_refs.json 的 forbidden_in）。回归来自生产探针 XSIBKTYQ。"""
import json
from pathlib import Path

import pytest
from pipecat.processors.aggregators.llm_context import LLMContext

from deepsuck.engine import Session
from deepsuck.refs import forbidden_in
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.processors import IntelProcessor

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/unsaid_refs.json").read_text(encoding="utf-8"))
CARD = "6222021234567890128"
HEAD = "对方到现在还没报过"


def _proc(scenario="police", persona="wang"):
    s = Session(scenario=scenario, persona=persona, rng=mulberry32(5), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    return s, IntelProcessor(s, context=ctx), ctx


def _line(ctx):
    msgs = ctx.get_messages()
    assert msgs[-1]["role"] == "system"
    return next((x for x in msgs[-1]["content"].split("\n") if x.startswith(HEAD)), "")


def test_small_talk_no_line():
    s, p, ctx = _proc("pig", "lin")
    s.ingest("你好，交个朋友")
    p.update_prompt()
    assert _line(ctx) == ""


def test_bank_mentioned_nothing_reported():
    s, p, ctx = _proc()
    s.ingest("你好，我是公安局的。")
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    p.update_prompt()
    line = _line(ctx)
    assert "卡号" in line and "户名" in line and "“户名是谁”" in line and "“卡号多少”" in line
    assert "电话" not in line and "钱包" not in line  # 没提到的话题不写（#4）
    assert not forbidden_in(line, set())
    assert ctx.get_messages()[-1]["content"].rstrip().endswith(P.FOLLOW_UP_RULE)


def test_reported_items_drop_out():
    s, p, ctx = _proc()
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    p.call_redact(s.ingest(f"把钱转到安全账户，卡号{CARD}。"))
    p.update_prompt()
    line = _line(ctx)
    assert "户名" in line and "卡号" not in line
    p.call_redact(s.ingest("户名张三丰。"))
    p.update_prompt()
    assert _line(ctx) == ""


def test_offline_and_first_turn():
    assert P.unsaid_line(set(), None) == "" and P.unsaid_line(None, {"bank"}) == ""
    assert "电话" in P.unsaid_line(set(), {"phone"}) and "户名" not in P.unsaid_line(set(), {"phone"})
    on = P.system_prompt("wang", "police", "generic", topics={"bank"}, first_turn=True, refs=set())
    off = P.system_prompt("wang", "police", "generic", topics={"bank"}, refs=set())
    assert HEAD not in on and HEAD in off
    assert HEAD not in P.system_prompt("wang", "police", "generic", topics={"bank"})  # 离线不传 refs 不变


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_shared_fixture_still_clean_with_line(case):
    """共用用例：加上这一行以后，提示词里仍不出现对方没报过的代称说法。"""
    refs = P.heard_refs(case["heard"])
    topics = set().union(*(P.topics_in(t) for t in case["heard"])) | {"bank", "phone", "wallet"}
    for hint in F["hints"]:
        sp = P.system_prompt(case["persona"], "police", hint, topics=topics, opener_key=case["id"], refs=refs)
        assert not forbidden_in(sp, case["refs"]), (case["id"], hint)


DROP = [
    ("嗯，转我这儿。你报一下那个号", "嗯，转我这儿。你报一下号码"),
    ("你说的那个号…我手头没记着。", "号码…我手头没记着。"),
    ("户名是那个名字，我记下了", "户名叫什么，我记下了"),
    ("那张卡是哪个行的", "卡是哪个行的"),
    ("户名没记全，你再说一遍", "户名还没说，你再说一遍"),
]


@pytest.mark.parametrize("raw,want", DROP)
def test_drop_unsaid_when_not_reported(raw, want):
    out = P.drop_unsaid(raw, set())
    assert out == want
    assert not forbidden_in(out, set())


def test_drop_unsaid_keeps_reported_and_offline():
    t = "你说的那个号…户名是那个名字"
    assert P.drop_unsaid(t, {"number", "name"}) == t
    assert P.drop_unsaid(t, None) == t
    assert P.drop_unsaid(t, {"number"}) == "你说的那个号…户名叫什么"


def test_tts_filter_and_record_use_refs():
    import asyncio
    from voice.processors import GuardTextFilter
    s, p, ctx = _proc()
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    f = GuardTextFilter(p.redactor, refs=p.heard_refs)
    spoken = asyncio.run(f.filter("你报一下那个号，户名是那个名字"))
    assert "那个号" not in spoken and "那个名字" not in spoken, spoken
    p.call_redact(s.ingest(f"卡号{CARD}，户名张三丰。"))
    spoken = asyncio.run(f.filter("你说的那个号我记下了"))
    assert "那个号" in spoken  # 报过以后原样


def test_after_hold_transfer():
    """#187 的 hold_transfer 仍在守卫链最前面；代称兜底在它之后，两样都生效。"""
    import asyncio
    from voice.processors import GuardTextFilter
    s, p, ctx = _proc()
    s.ingest("您名下有一张银行卡涉嫌洗钱。")
    out = asyncio.run(GuardTextFilter(p.redactor, refs=p.heard_refs).filter("我已经转了。你报一下那个号"))
    assert "转了" not in out and "那个号" not in out, out
    assert P.speakable("我已经转了。") in out


def test_fragment_star_segments_count_as_number_not_name():
    """#186 打码后的号码片段单独成纯星号段：算号码，不算名字（本地号码探针 UYJ5OQDF：说出“户名是那个名字”）。"""
    s, p, ctx = _proc()
    s.ingest("你记一下。")
    for t in ("卡号是62220212。", "345678。", "90123。"):
        p.frag_redact(p.call_redact(s.ingest(t)))
    assert any(m["text"] == "******。" for m in s.messages if m.get("role") == "scammer")
    refs = p.heard_refs()
    assert "number" in refs and "name" not in refs, refs
    # 名字后面的纯星号逐字解释仍算名字（#172）
    s2, p2, _ = _proc()
    s2.messages += [{"role": "scammer", "text": "收款人叫张**。"}, {"role": "scammer", "text": "****，****。"}]
    assert "name" in p2.heard_refs()
