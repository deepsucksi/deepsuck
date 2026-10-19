"""#187：语音侧——硬性规则 4 收紧（固定部分、每轮不变，#169 前缀缓存），guard_output / speakable 第一步拦下已转 / 承诺转。

用例 tests/fixtures/transfer_claim.json（与 tests/transfer_claim.test.js、python/tests/test_transfer_claim.py 共用）。
"""
import json
from pathlib import Path

import pytest

from voice import persona as P
from deepsuck.personas import TRANSFER_CLAIM as TC

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/transfer_claim.json").read_text(encoding="utf-8"))
BAD = ("转完了", "转过去了", "我先转", "收到了没", "转给你", "马上转")


@pytest.mark.parametrize("case", F["claim"], ids=lambda c: c["text"][:12])
def test_guard_output_holds_claims(case):
    out = P.guard_output(case["text"])
    assert any(x in out for x in TC["stall"]), out
    assert not any(w in out for w in BAD), out
    if case.get("mustKeep"):  # #204：改写后仍保留问收款信息那一问
        assert case["mustKeep"] in out, out
    spoken = P.speakable(case["text"], calm_tts=False)
    assert not any(w in spoken for w in BAD), spoken


@pytest.mark.parametrize("text", F["keep"], ids=lambda t: t[:12])
def test_guard_output_keeps_negations_and_quotes(text):
    assert not any(x in P.guard_output(text) for x in TC["stall"] if x not in text)


def test_rule_4_in_fixed_prefix_and_stable():
    fixed_a, turn_a = P.prompt_parts("wang", "police", "fake_progress", ["收款账户"], topics={"bank"}, scenes=["police"], refs=set())
    fixed_b, _ = P.prompt_parts("wang", "police", "elicit_account", [], topics={"bank"}, scenes=["police"], refs={"number"},
                                have=["收款银行卡号"], facts=["工商银行"])
    assert "4. " + TC["rule"] in fixed_a and fixed_a == fixed_b  # 固定部分每轮不变
    assert TC["rule"] not in turn_a
    for w in BAD:
        assert w not in fixed_a, w  # 规则里不举那几句原话
