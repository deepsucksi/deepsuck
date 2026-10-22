"""#163 偏旁说法与没有提示词的单段解释：与 tests/redact_radical_explain.test.js 对应，夹具 redact.json 的 radicalExplain。"""
import re

import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import find_name_spans

from conftest import fixture

CASES = fixture("redact")["radicalExplain"]
LEAK = re.compile("韦|江|工|花|伟|晨|旁一个|点水|字头|字旁|的李|子的")


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_radical_explain_parity(case):
    ents = extract_sensitive(case["text"])
    assert find_name_spans(case["text"], ents) == case["spans"]
    out = redact_text(case["text"], ents)
    assert out == case["redacted"]
    assert (out != case["text"]) == (case["expect"] == "mask")
    if case["expect"] == "mask":
        assert not LEAK.search(out), (case["text"], out)


def test_fixture_has_both_kinds():
    assert sum(c["expect"] == "mask" for c in CASES) >= 12
    assert sum(c["expect"] == "keep" for c in CASES) >= 8
