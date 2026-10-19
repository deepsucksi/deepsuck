"""#173（含 #181）/ #172：共享核心 deepsuck.refs 与 llm.js 逐字一致。

用例 tests/fixtures/unsaid_refs.json（与 tests/unsaid_refs.test.js、voice/tests/test_unsaid_refs.py 共用）、
tests/fixtures/redact.json 的 charExplain。规则引擎（Session）对方没报号时回复里也没有“那个号”“那个名字”。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import Session  # noqa: E402
from deepsuck.refs import UR, drop_unheard, forbidden_in, heard_refs, speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/unsaid_refs.json").read_text(encoding="utf-8"))
RX = json.loads((ROOT / "tests/fixtures/redact.json").read_text(encoding="utf-8"))
PJ = json.loads((ROOT / "site/assets/core/personas.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_heard_refs_same_as_js(case):
    assert sorted(heard_refs(case["heard"])) == sorted(case["refs"])


def test_drop_unheard_same_as_js():
    assert drop_unheard(PJ["nameRule"], set()) == "不复述对方说的任何人名（只说了姓的、打了星号的也算）。"
    assert drop_unheard(PJ["nameRule"], {"name"}) == PJ["nameRule"]
    assert drop_unheard("都算；要提就说“你说的那个号”“那张卡”，最多含糊地说“好像是…开头的”", set()) == "都算；最多含糊地说“好像是…开头的”"
    ci = drop_unheard(PJ["intentHints"]["confirm_intel"], {"url"})
    assert "只说姓氏或“你发的那个网址”" in ci and "那个号" not in ci and "那个名字" not in ci
    for k, v in PJ["intentHints"].items():
        if k != "confirm_intel":
            assert drop_unheard(v, set()) == v, k


@pytest.mark.parametrize("text", [c["redacted"] for c in RX["charExplain"] if c["expect"] == "mask" and not c.get("xfail")] + ["伟是****", "伟字是****", "就是****", "伟，****"])
def test_char_explain_is_a_name(text):  # #172
    out = speak_masked(text)
    assert UR["phrase"]["name"] in out and "那个号" not in out and "*" not in out, out


@pytest.mark.parametrize("text", ["138****5678", "卡号 6222 **** **** 7890", "转到622202*********3445", "验证码是******", "尾号 ****"])
def test_masked_numbers_stay_numbers(text):
    out = speak_masked(text)
    assert "那个号" in out and "那个名字" not in out, out


@pytest.mark.parametrize("case", [c for c in F["cases"] if not c["refs"]], ids=lambda c: c["id"])
def test_rule_engine_never_refers_to_unsaid(case):
    for seed in range(8):
        s = Session("police", case["persona"], rng=__import__("random").Random(seed).random, now=lambda: 0)
        for t in case["heard"]:
            out = s.rule_reply(s.ingest(t))["text"]
            assert not forbidden_in(out, set()), (case["id"], out)
