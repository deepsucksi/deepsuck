"""断续句情报回归（#8）：「…」「...」「，」停顿、逐位读出、跨回合拆开、「尾号XXXX」。
手写向量与 tests/halting_recall.test.js 共用（tests/fixtures/halting_vectors.json）；另跑一遍 eval/halting_eval.py 的生成评测集
与模拟器断续句模式（--reveal halting），作为召回 / 误报门槛。"""
import json
import re
import sys
from pathlib import Path

import pytest

from deepsuck import sim
from deepsuck.engine import Session

ROOT = Path(__file__).resolve().parents[2]
VEC = json.loads((ROOT / "tests" / "fixtures" / "halting_vectors.json").read_text(encoding="utf-8"))
INTEL = ("bank_card", "phone", "crypto_tron", "crypto_eth", "crypto_btc")


def session_intel(turns):
    s = Session("refund", "wang", rng=lambda: 0.5, now=lambda: 0)
    for t in turns:
        s.ingest(t)
    return sorted([i["type"], re.sub(r"[^0-9A-Za-z]", "", str(s._raw[k]))] for k, i in s.intel.items() if i["type"] in INTEL)


@pytest.mark.parametrize("case", VEC["positive"], ids=[c["name"] for c in VEC["positive"]])
def test_halting_positive(case):
    assert session_intel(case["turns"]) == sorted(case["want"])


@pytest.mark.parametrize("case", VEC["negative"], ids=[c["name"] for c in VEC["negative"]])
def test_halting_negative(case):
    assert session_intel(case["turns"]) == []


@pytest.fixture(scope="module")
def halting_eval():
    sys.path.insert(0, str(ROOT / "eval"))
    import halting_eval as H
    return H.run(Session, sim._canon, seeds=6)


def test_halting_eval_recall(halting_eval):
    sm = halting_eval["summary"]
    for g in ("account", "phone", "wallet"):
        assert sm[g + "Recall"] >= 0.99, (g, halting_eval["misses"][:5])


def test_halting_eval_no_false_items(halting_eval):
    assert halting_eval["summary"]["negCases"] >= 50
    assert halting_eval["summary"]["falseItems"] == 0, halting_eval["negative"]["hits"]


def test_sim_halting_mode():
    res = sim.run(seeds=3, policies=("rule",), reveal="halting")
    r = res["byPolicy"]["rule"]
    assert res["config"]["reveal"] == "halting"
    assert r["extractRate"] == 1.0 and r["falseIntelPerSession"] == 0 and r["leakRate"] == 0
    assert {"bank_card", "phone"} <= set(r["byType"])


def test_sim_halting_splits_numbers_across_turns():
    scripts = sim.load_scripts("legacy")
    sc = sim.Scammer(scripts["scenarios"]["refund"], scripts["common"], sim.Rand(7), "halting")
    msgs = []
    for _ in range(6):
        sc.todo.append("bank")
        msgs.append(sc.reveal("bank"))
    assert sc.pending, "断续句模式应把部分卡号拆到下一回合"
    assert all("…" in m or "..." in m or "，" in m for m in msgs)
