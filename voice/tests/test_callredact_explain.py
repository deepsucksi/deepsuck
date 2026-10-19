"""#165：按通话打码跟进逐字解释（#158 / #162，共享核心 nameRules.explain）。
用例与共享核心同一组：tests/fixtures/redact.json 的 charExplain（正例 + 反例）。"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck import extract_sensitive, redact_text
from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice.callredact import CHAIZI, CallRedactor, explain_segments
from voice.persona import unmask
from voice.processors import GuardTextFilter, IntelProcessor

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "tests/fixtures/redact.json").read_text(encoding="utf-8"))["charExplain"]
MASK = [c for c in CASES if c["expect"] == "mask"]
KEEP = [c for c in CASES if c["expect"] == "keep"]
_SPLIT_SUR = {cz + sur: sur for sur, czs in CHAIZI.items() for cz in czs}


def _session():
    return Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)


def core(t):
    return redact_text(t, extract_sensitive(t))


def _explained(case):
    """正例里被打码的逐字解释段原文（「伟大的伟」「伟字是伟大的伟」），以及被解释的字。"""
    out = []
    for sp in case["spans"]:
        seg = case["text"][sp["start"]:sp["end"]]
        if "的" in seg:
            out.append((seg, re.sub("字$", "", seg)[-1]))
    return out


def _call_name(case):
    """跨轮场景里本通已记住的姓名：拆字报的姓（没有就用“张”）+ 被解释的字。"""
    sur = next((s for k, s in _SPLIT_SUR.items() if k in case["text"]), "张")
    given = "".join(dict.fromkeys(x for _, x in _explained(case) if x != sur))
    return sur + given


def test_fixture_counts():
    assert len(CASES) == len(MASK) + len(KEEP) and not any("xfail" in c for c in CASES)  # #163：xfail 已全部修好


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_same_turn_via_session(case):
    """逐句：session.ingest（共享核心 redact_text，explain 已生效）→ 记下本段提取的姓名 → CallRedactor 再打一遍。"""
    s = _session()
    red = s.ingest(case["text"])["redacted"]
    assert red == case["redacted"]  # 进 CallRedactor 前就是共享核心的结果
    r = CallRedactor()
    r.learn(s)
    out = r.apply(red)
    if not len(r):
        assert out == red  # 没记住任何值时不改
    if case["expect"] == "keep":
        assert out == case["text"]
        return
    for seg, _ in _explained(case):
        assert seg not in out, (case["text"], out)
    spoken = unmask(out)
    assert "*" not in spoken and "＊" not in spoken
    for seg, _ in _explained(case):
        assert seg not in spoken


@pytest.mark.parametrize("case", MASK, ids=[c["text"] for c in MASK])
def test_cross_turn_full_sentence(case):
    """本通已记住姓名，后面一轮整句再说（骗子原话经共享核心、模型复述原文直接进 CallRedactor 两条路）都不露解释段。"""
    name = _call_name(case)
    r = CallRedactor()
    r.add("name", name)
    for text in (case["text"], core(case["text"])):
        out = r.apply(text)
        for seg, _ in _explained(case):
            assert seg not in out, (name, text, out)
        assert "*" not in unmask(out)


@pytest.mark.parametrize("case", MASK, ids=[c["text"] for c in MASK])
def test_cross_turn_single_explain(case):
    """单独一段解释（「伟大的伟」）达不到逐句门槛，共享核心不打；本通已记住的姓名里的字照样打成“那个名字”。"""
    name = _call_name(case)
    r = CallRedactor()
    r.add("name", name)
    for seg, x in _explained(case):
        if x == name[0]:
            continue  # 被解释的是姓：与 张** 只留姓一致，不打
        for t in (seg, "对，" + seg + "。", seg + "啊"):
            red = core(t)
            out = r.apply(red)
            assert seg not in out, (name, t, out)
            assert "*" not in unmask(out)
            if seg in red:  # 共享核心没打的（单段、无「就是 / X是」）由按通话打码补上，读成“那个名字”
                assert "那个名字" in unmask(out), (name, t, out)
            # 模型复述原文（送 TTS 前先过 CallRedactor）
            raw = r.apply(t)
            assert seg not in raw and "那个名字" in unmask(raw), (name, t, raw)


@pytest.mark.parametrize("case", KEEP, ids=[c["text"] for c in KEEP])
def test_keep_cases_not_masked_in_call(case):
    """反例：本通记住了 张伟晨、陈东屿、李明、王家 这些名字，反例照旧不动（「伟大的伟人」「东方的东西」「伟大的祖国」…）。
    只有「伟大的那个伟字」本身就是对已记住姓名里「伟」字的解释，按通话应打码。"""
    r = CallRedactor()
    for n in ("张伟晨", "陈东屿", "李明"):
        r.add("name", n)
    out = r.apply(core(case["text"]))
    if case["text"] == "伟大的那个伟字":
        assert out == "张**"
    else:
        # 拆字报的是已记住姓名的姓（「木子李」，李明）时按 #140 原有规则只换拆字说法，解释段本身不动
        assert out == case["text"].replace("木子李", "李*"), out
    # 没记住相关的字时，任何反例都不动
    r2 = CallRedactor()
    r2.add("name", "赵钱")
    assert r2.apply(case["text"]) == case["text"]


def test_surname_explain_kept():
    r = CallRedactor()
    r.add("name", "李春")
    assert r.apply("李子的李") == "李子的李"
    assert unmask(r.apply("木子李，就是李子的李，春天的春")) == "那个名字，就是李子的李，那个名字"
    assert "春" not in r.apply(core("木子李，就是李子的李，春天的春"))


def test_core_star_tail_merged_into_name():
    """共享核心已打成「弓长张，****」时，拆字说法连同后面的星号并成一个名字，不剩「，****」读成“那个号”。"""
    r = CallRedactor()
    r.add("name", "张伟晨")
    assert r.apply("收款户名张**，弓长张，****，****") == "收款户名张**，张**"
    assert unmask(r.apply("收款人叫张**，****")) == "收款人叫那个名字"
    assert r.apply("我的卡号138****5678") == "我的卡号138****5678"  # 号码打码不并


def test_explain_segments_rules_from_core():
    segs = explain_segments("伟大的伟，早晨的晨，东方的东西，这是大家的家")
    assert [[u["x"] for u in c] for c in segs] == [["伟", "晨"], ["家"]]
    assert explain_segments("伟大的祖国") == []


def _tf(text):
    return TranscriptionFrame(text=text, user_id="u", timestamp="t")


def test_pipeline_cross_turn_model_input_and_tts():
    """IntelProcessor：第一段报户名并逐字解释，第二段单独一段解释；进模型、会话记录、送 TTS 都不露名字。"""
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx, filler_prob=0.0)
    texts = ["收款户名张伟晨，弓长张，伟大的伟，早晨的晨", "对，早晨的晨。"]
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf(t) for t in texts],
                                   expected_down_frames=[TranscriptionFrame] * len(texts)))
    to_model = [f.text for f in down]
    assert to_model == ["收款户名那个名字，那个名字", "对，那个名字。"], to_model
    for m in s.messages:
        if m.get("role") == "scammer":
            assert "早晨的晨" not in m["text"] and "伟大的伟" not in m["text"], m
    f = GuardTextFilter(p.redactor)
    for t in ("伟大的伟，早晨的晨，对吧？", "早晨的晨吧", "弓长张，伟大的伟"):
        spoken = asyncio.run(f.filter(t))
        assert "伟" not in spoken and "晨" not in spoken and "*" not in spoken, spoken
        assert "那个名字" in spoken, spoken
    # 反例不误打
    assert asyncio.run(f.filter("东方的东西都是伟大的祖国的")) == "东方的东西都是伟大的祖国的"


@pytest.mark.parametrize("t", ["收款人是弓长张，伟大的伟对吧", "户名龚厂长伟大的伟对吧", "伟大的伟是吗", "伟大的伟，明天的明对不对"])
def test_cross_turn_tail_words(t):
    """#202：解释段后面紧跟确认说法（nameRules.explain.tailWords，#206）时，模型复述原话进 CallRedactor 也不露解释段。"""
    r = CallRedactor()
    r.add("name", "张伟明")
    out = r.apply(t)
    assert "伟大的伟" not in out and "明天的明" not in out, (t, out)
    assert "*" not in unmask(out)
