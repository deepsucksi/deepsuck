"""演示页回复回归（与 tests/demo_replies.test.js 对应）：规则引擎回复对骗子不念打码星号、引号配对；
复现场景为冒充客服·退款理赔、王阿姨、样例 1–3，另外全场景 × 全人设扫一遍。
遗留修复：小林删去“反诈课 PPT”句；李大爷 confirm_intel 后不紧接着要电话（personas.json 的 confirmAskSkip）。"""
import json
import re
from pathlib import Path

from deepsuck.engine import Session
from deepsuck.personas import PERSONAS, SCENARIOS
from deepsuck.rng import mulberry32

BY_ID = {s["id"]: s for s in SCENARIOS}

CORE = Path(__file__).resolve().parents[2] / "site" / "assets" / "core"
OPEN = {"“": "”", "「": "」", "『": "』", "‘": "’"}
CLOSE = {v: k for k, v in OPEN.items()}


def quotes_paired(t: str) -> bool:
    st = []
    for c in t:
        if c in OPEN:
            st.append(c)
        elif c in CLOSE and (not st or st.pop() != CLOSE[c]):
            return False
    return not st and t.count('"') % 2 == 0


def check(t: str, where: str) -> None:
    assert not re.search(r"[*＊]", t), f"{where} 回复带打码星号: {t}"
    assert quotes_paired(t), f"{where} 引号不配对: {t}"


def test_demo_refund_wang_samples_1_to_3():
    samples = BY_ID["refund"]["samples"]
    for seed in range(1, 201):
        s = Session("refund", "wang", rng=mulberry32(seed), now=lambda: 0)
        check(s.opening()["text"], "opening")
        for i in range(3):
            check(s.rule_reply(s.ingest(samples[i]))["text"], f"seed {seed} 样例 {i + 1}")


def test_all_scenarios_all_personas_no_stars_no_lone_quotes():
    corpus = [e["text"] for e in json.loads((CORE / "scam_scripts.json").read_text(encoding="utf-8"))["entries"]]
    n = 0
    for sc in SCENARIOS:
        for p in PERSONAS:
            for seed in range(1, 9):
                s = Session(sc["id"], p["id"], rng=mulberry32(seed), now=lambda: 0)
                check(s.opening()["text"], f"{sc['id']}/{p['id']} opening")
                lines = list(sc["samples"]) + [t for i, t in enumerate(corpus) if i % 8 == seed - 1][:20]
                for line in lines:
                    check(s.rule_reply(s.ingest(line))["text"], f"{sc['id']}/{p['id']}/{seed}")
                    n += 1
    assert n > 1000


def test_lin_no_antifraud_class_line_and_li_no_phone_after_confirm():
    lin = next(p for p in PERSONAS if p["id"] == "lin")
    for v in lin["templates"].values():
        for t in v:
            txt = t if isinstance(t, str) else t["t"]
            assert "反诈课" not in txt and "PPT" not in txt
    li = next(p for p in PERSONAS if p["id"] == "li")
    assert li.get("confirmAskSkip") == ["phone"]
    phone_ask = li["asks"]["phone"]
    confirms = 0
    for sc in SCENARIOS:
        for seed in range(1, 31):
            s = Session(sc["id"], "li", rng=mulberry32(seed), now=lambda: 0)
            s.opening()
            for line in sc["samples"]:
                r = s.rule_reply(s.ingest(line))
                if r["intent"] == "confirm_intel":
                    confirms += 1
                    assert phone_ask not in r["text"], r["text"]
    assert confirms > 20


def test_lin_no_cut_away_right_after_re_ask():
    lin = next(p for p in PERSONAS if p["id"] == "lin")
    for v in lin["templates"].values():
        for t in v:
            assert "反诈" not in (t if isinstance(t, str) else t["t"])
    assert [p["id"] for p in PERSONAS if p.get("afterReAskAvoid")] == ["lin"]
    cut = re.compile(lin["afterReAskAvoid"])
    after = 0
    for sc in SCENARIOS:
        for seed in range(1, 41):
            s = Session(sc["id"], "lin", rng=mulberry32(seed), now=lambda: 0)
            s.opening()
            prev = None
            lines = list(sc["samples"]) + ["验证码发我", "快点操作", "你切回来看一下页面", "验证码收到没有", "额度多少你说"]
            for line in lines + lines:
                r = s.rule_reply(s.ingest(line))
                if prev == "re_ask":
                    after += 1
                    assert not cut.search(r["text"]), r["text"]
                prev = r["intent"]
    assert after > 20
