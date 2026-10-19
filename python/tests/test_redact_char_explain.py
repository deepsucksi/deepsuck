"""逐字解释名字打码（#158）：与 tests/redact_char_explain.test.js 对应，规则在 core/extractors.json 的 nameRules.explain。"""
import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import find_name_spans

from conftest import fixture

CASES = fixture("redact")["charExplain"]


def red(t):
    return redact_text(t, extract_sensitive(t))


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_char_explain_parity(case):
    ents = extract_sensitive(case["text"])
    assert find_name_spans(case["text"], ents) == case["spans"]
    out = redact_text(case["text"], ents)
    assert out == case["redacted"]
    assert (out != case["text"]) == (case["expect"] == "mask")


def test_fixture_has_both_kinds():
    assert sum(c["expect"] == "mask" for c in CASES) >= 12
    assert sum(c["expect"] == "keep" for c in CASES) >= 10


def test_issue_sentence():
    t = "收款户名张伟晨，弓长张，伟大的伟，早晨的晨"
    out = red(t)
    assert out == "收款户名张**，弓长张，****，****"
    for leak in ("伟", "晨", "**的"):
        assert leak not in out, (t, out)


def test_split_then_explain():
    assert red("弓长张，伟大的伟") == "弓长张，****"
    assert red("耳东陈，东方的东") == "耳东陈，****"
    assert red("户名陈东，耳东陈，东方的东") == "户名陈*，耳东陈，****"
    assert red("弓长张伟大的伟") == "弓长张****"


def test_leads_and_chains():
    assert red("伟是伟大的伟，晨是早晨的晨") == "******，******"
    assert red("就是伟大的伟") == "就是****"
    assert red("伟大的伟早晨的晨") == "********"
    assert red("立早章，文章的章，晓得的晓，帆船的帆") == "立早章，文章的章，****，****"


def test_surname_explain_kept():
    for t in ("木子李，就是李子的李", "立早章，文章的章"):
        assert red(t) == t
    assert red("木子李，就是李子的李，春天的春") == "木子李，就是李子的李，****"


def test_negative_ordinary_text():
    for t in ("伟大的祖国", "明天的会", "我的卡", "伟大的伟人", "东方的东西", "明天的明天会更好", "这是大家的家",
              "他说好的好处呢", "我的卡号发你了，明天的会别迟到", "李子的李"):
        assert red(t) == t
