"""#194：人设回复压短（语音硬性规则 1、FOLLOW_UP_RULE、首轮规则）。用例 tests/fixtures/reply_length.json 与 tests/reply_length.test.js 共用。
硬性规则在固定前缀里（#169），每轮相同。"""
import json
from pathlib import Path

import pytest

from voice import persona as P

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/reply_length.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("pid", F["personas"])
@pytest.mark.parametrize("first", [True, False])
def test_voice_prompt_length_rules(pid, first):
    sp = P.system_prompt(pid, "refund", "opening", first_turn=first)
    for w in F["voice"]["required"] + (F["voice"]["firstTurn"] if first else F["voice"]["followUp"]):
        assert w in sp, (pid, first, w)
    for w in F["forbidden"]:
        assert w not in sp, (pid, first, w)
    assert f"{F['maxChars']} 字" in sp


def test_hard_rules_prefix_fixed():
    a = P.system_prompt("chen", "refund", "opening", first_turn=True)
    b = P.system_prompt("chen", "refund", "generic", first_turn=False)
    rules = "\n".join(P.HARD_RULES)
    assert rules in a and rules in b
    assert a.index(rules) == b.index(rules)
