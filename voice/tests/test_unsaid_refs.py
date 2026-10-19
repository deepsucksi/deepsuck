"""#173（含 #181）：语音人设提示词——对方没报过号码 / 户名时不出现“那个号”“那个名字”。

用例 tests/fixtures/unsaid_refs.json（与 tests/unsaid_refs.test.js、python/tests/test_unsaid_refs.py 共用）。
通话里 IntelProcessor.update_prompt 传 refs=heard_refs()（对方的话里出现过的打码值 + 已提取的情报）。
"""
import json
from pathlib import Path

import pytest

from voice import persona as P
from deepsuck.engine import Session
from deepsuck.refs import UR, forbidden_in

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/unsaid_refs.json").read_text(encoding="utf-8"))
LABEL = {"bank": "收款银行卡号", "wallet": "加密钱包地址", "phone": "联系电话", "url": "网址/下载链接", "name": "收款人姓名"}


def _prompts(case):
    refs = P.heard_refs(case["heard"])
    topics = set().union(*(P.topics_in(t) for t in case["heard"]))
    scenes = []
    for t in case["heard"]:
        scenes += [x for x in P.scenes_in(t) if x not in scenes]
    for hint in F["hints"]:
        for first in (True, False):
            yield hint, P.system_prompt(case["persona"], "police", hint, [LABEL[g] for g in case["goals"]], topics=topics,
                                        first_turn=first, scenes=scenes, opener_key=case["id"], refs=refs)


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_refs_same_as_web(case):
    assert sorted(P.heard_refs(case["heard"])) == sorted(case["refs"])


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_prompt_never_names_unsaid_refs(case):
    for hint, sp in _prompts(case):
        assert not forbidden_in(sp, case["refs"]), (case["id"], hint, sp)
        assert P.UNSAID_RULE in sp
        if not case["refs"]:
            assert "户名没记全" not in sp and "那张卡" not in sp, (case["id"], hint)


def test_shot_with_ref_word_skipped_until_reported():
    shot = "那个号你说"
    off = P.system_prompt("wang", "police", "generic", [], topics={"bank"}, scenes=["police"], refs=set())
    on = P.system_prompt("wang", "police", "generic", [], topics={"bank"}, scenes=["police"], refs={"number"})
    assert shot not in off and "那个号" not in off
    assert "“你说的那个号”" in on and P.ref_line({"number"}) in on  # 报过号码以后在可变部分说
    fixed_off, _ = P.prompt_parts("wang", "police", "generic", [], topics={"bank"}, scenes=["police"], refs=set())
    fixed_on, _ = P.prompt_parts("wang", "police", "generic", [], topics={"bank"}, scenes=["police"], refs={"number", "name"})
    assert fixed_off == fixed_on  # #169：固定部分不随报没报过变


def test_offline_prompt_unchanged_without_refs():
    sp = P.system_prompt("wang", "refund", "generic", [], topics={"bank"}, scenes=["refund"])
    assert P.RULE_DIGITS in sp and P.load("personas")["nameRule"] in sp


def test_processor_refs_from_session():
    from voice.processors import IntelProcessor
    s = Session("police", "wang", rng=lambda: 0.3, now=lambda: 0)
    ip = IntelProcessor.__new__(IntelProcessor)
    ip.session = s
    s.ingest("你把钱转到国家安全账户，查清楚了马上退给你。")
    assert ip.heard_refs() == set()
    s.ingest("账户是6222020200112233445，户名王小明")
    assert ip.heard_refs() >= {"number", "name"}
    assert UR["phrase"]["name"] == "那个名字"
