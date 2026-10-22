"""#259 复审：拆字报姓后有逗号 / 无逗号接逐字解释，voice 侧 trace.redact 不留拆字姓（python/tests/test_redact_259_nocomma.py 的 voice 部分）。"""
import pytest

from voice import trace as TR

SPLIT, EXPL = "耳东陈", "耳朵的耳东边的东"
CASES = [SPLIT + EXPL, SPLIT + "，" + EXPL, "户名" + SPLIT + EXPL + "，1000元", "户名" + SPLIT + "，" + EXPL + "，1000元"]
NEEDLES = (SPLIT, "耳东", "耳朵的耳", "东边的东")


@pytest.mark.parametrize("t", CASES)
def test_trace_redact_no_split_surname(t):
    out = TR.redact(t)
    assert not any(n in out for n in NEEDLES), out
    assert "那个名字" in out or "*" in out, out
