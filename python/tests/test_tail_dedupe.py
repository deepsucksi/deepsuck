"""#153：跨轮去重 deepsuck.engine.dedupe_tail 与 JS engine.dedupeTail 逐项一致（tests/fixtures/tail_dedupe.json 由 JS 生成）。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python")]

from deepsuck.engine import _td_norm, dedupe_tail, tail_sentence  # noqa: E402
from deepsuck.personas import PERSONAS, TAIL_DEDUPE, resolve_persona_id  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/tail_dedupe.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["text"][:12] or "empty")
def test_matches_js(case):
    assert dedupe_tail(case["text"], case["recent"], case["persona"]) == case["expected"]
    assert tail_sentence(case["text"]) == case["tail"]


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["text"][:12] or "empty")
def test_never_repeats_recent_tail(case):
    out = dedupe_tail(case["text"], case["recent"], case["persona"])
    recent = {_td_norm(x) for x in case["recent"][-FIX["window"]:]} - {""}
    if _td_norm(out):
        assert _td_norm(tail_sentence(out)) not in recent, out
    assert dedupe_tail(out, case["recent"], case["persona"]) == out  # 改写后再过一遍不变


def test_pure_and_window():
    recent = ["你再说一遍。", "a", "b", "c"]
    assert dedupe_tail("你再说一遍。", recent) == "你再说一遍。"  # 超出最近三轮的不算
    before = list(recent)
    dedupe_tail("c", recent)
    assert recent == before  # 不改入参、不存状态
    assert dedupe_tail("c", recent) == dedupe_tail("c", recent)


def _approved(pid):
    p = next(x for x in PERSONAS if x["id"] == resolve_persona_id(pid))
    return [x for x in p["templates"][TAIL_DEDUPE["fallback"]] if isinstance(x, str) and "{" not in x]


def test_no_new_line_text():
    # 负责人决定：兜底不加任何新口头语
    assert "lead" not in TAIL_DEDUPE and "particles" not in TAIL_DEDUPE
    for case in FIX["cases"]:
        out = case["expected"]
        if case["persona"] and out and out != case["text"]:
            # 输出要么是原文删掉尾部若干句，要么整句是该人设已批台词
            assert case["text"].startswith(out.rstrip()) or out in _approved(case["persona"]), out


def test_fallback_skips_recent_and_is_deterministic():
    pool = _approved("chen")
    recent = pool[:3]
    out = dedupe_tail(pool[0], recent, "chen")
    assert out in pool[3:]
    assert out == dedupe_tail(pool[0], recent, "chen")
    assert dedupe_tail(pool[0], recent) == ""  # 没传人设：删完为空就返回空串
    assert dedupe_tail("行。", ["行"], "mom") in _approved("chen")  # 别名


# ---- #188：兜底只从 tailDedupe.fallbackPick 标了的 ask_repeat 里挑（与 JS tests/tail_dedupe.test.js 同一组断言）----
from deepsuck.engine import vague_digits  # noqa: E402

SCENE_RE = re.compile(r"按钮|红的|绿的|页面|菜单|第[一二三四五六七八九两\d]步|打开|登录|填|链接|APP|发|消息|一条|一段|那段|字")


def _picked(pid):
    p = next(x for x in PERSONAS if x["id"] == pid)
    return [p["templates"]["ask_repeat"][i] for i in TAIL_DEDUPE["fallbackPick"][pid]]


@pytest.mark.parametrize("pid", [p["id"] for p in PERSONAS])
def test_fallback_pick_marks_only_plain_lines(pid):
    p = next(x for x in PERSONAS if x["id"] == pid)
    pick = TAIL_DEDUPE["fallbackPick"].get(pid)
    assert pick, pid  # 每个人设筛完都至少剩一句
    for i in pick:
        x = p["templates"]["ask_repeat"][i]
        assert isinstance(x, str) and "{" not in x
        assert not SCENE_RE.search(x), x
        assert len(re.findall(r"[0-9０-９]", x)) <= 1 and vague_digits(x) == x, x


@pytest.mark.parametrize("pid", [p["id"] for p in PERSONAS] + ["mom", "li"])
def test_fallback_only_from_picked(pid):
    rid = resolve_persona_id(pid)
    ok = _picked(rid)
    for t in ["行。", "好的吧", "你再说一遍。", "嗯…我听着呢", "我看看。"]:
        assert dedupe_tail(t, [t], pid) in ok
    out = dedupe_tail("行。", ["行。"] + ok[:2], pid)
    assert out == "" or (out in ok and out not in ok[:2])


def test_fallback_without_pick_falls_back_to_old_pool(monkeypatch):
    picked = _picked("wang")
    monkeypatch.setitem(TAIL_DEDUPE, "fallbackPick", {})
    pool = _approved("wang")
    outs = {dedupe_tail(t, [t], "wang") for t in ["行。", "好的吧", "你再说一遍。", "嗯…我听着呢", "我看看。", "a", "b", "c"]}
    assert outs <= set(pool) and outs - set(picked)  # 没有标记时用原来的整池（含带场景的句子）
