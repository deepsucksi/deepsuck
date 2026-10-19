"""#153：跨轮去重 deepsuck.engine.dedupe_tail 与 JS engine.dedupeTail 逐项一致（tests/fixtures/tail_dedupe.json 由 JS 生成）。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python")]

from deepsuck.engine import _td_norm, dedupe_tail, tail_sentence  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/tail_dedupe.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["text"][:12] or "empty")
def test_matches_js(case):
    assert dedupe_tail(case["text"], case["recent"]) == case["expected"]
    assert tail_sentence(case["text"]) == case["tail"]


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["text"][:12] or "empty")
def test_never_repeats_recent_tail(case):
    out = dedupe_tail(case["text"], case["recent"])
    recent = {_td_norm(x) for x in case["recent"][-FIX["window"]:]} - {""}
    if _td_norm(out):
        assert _td_norm(tail_sentence(out)) not in recent, out
    assert dedupe_tail(out, case["recent"]) == out  # 改写后再过一遍不变


def test_pure_and_window():
    recent = ["你再说一遍。", "a", "b", "c"]
    assert dedupe_tail("你再说一遍。", recent) == "你再说一遍。"  # 超出最近三轮的不算
    before = list(recent)
    dedupe_tail("c", recent)
    assert recent == before  # 不改入参、不存状态
    assert dedupe_tail("c", recent) == dedupe_tail("c", recent)
