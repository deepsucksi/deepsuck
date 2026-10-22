"""#259 复审必修：拆字报姓后不带逗号直接接逐字解释（「耳东陈耳朵的耳东边的东」）时，拆字部分与解释一并读成「那个名字」，
与带逗号写法一致，不留拆字姓。与 tests/redact_char_explain.test.js 的同名用例对应。"""
import os
import sys

import pytest

from deepsuck import extract_sensitive
from deepsuck.redact import say_names
from deepsuck.refs import mask_names

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SPLIT, EXPL = "耳东陈", "耳朵的耳东边的东"
CASES = [
    (SPLIT + EXPL, "那个名字"),
    (SPLIT + "，" + EXPL, "那个名字"),
    ("户名" + SPLIT + EXPL + "，1000元", "户名那个名字，1000元"),
    ("户名" + SPLIT + "，" + EXPL + "，1000元", "户名那个名字，1000元"),
]
NEEDLES = (SPLIT, "耳东", "耳朵的耳", "东边的东")


@pytest.mark.parametrize("t,want", CASES)
def test_say_names(t, want):
    assert say_names(t, extract_sensitive(t)) == want


@pytest.mark.parametrize("t,want", CASES)
def test_exits_no_split_surname(t, want):
    from voice.callredact import _redact_line_raw
    for out in (_redact_line_raw(t), mask_names(t)):  # trace.redact 依赖 loguru，见 voice/tests/test_redact_259_nocomma_voice.py
        assert not any(n in out for n in NEEDLES), out
        assert "那个名字" in out or "*" in out, out
