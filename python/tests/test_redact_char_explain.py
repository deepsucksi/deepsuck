"""逐字解释名字打码（#158）：与 tests/redact_char_explain.test.js 对应，规则在 core/extractors.json 的 nameRules.explain。"""
import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.core import load
from deepsuck.engine import vague_digits
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
    if case.get("xfail"):
        assert case["leak"] in out, "已知缺陷已修好，请去掉 xfail：" + case["text"]
    else:
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
    assert red("伟大的伟早晨的晨") == "****，****"
    assert red("立早章，文章的章，晓得的晓，帆船的帆") == "立早章，文章的章，****，****"


def test_surname_explain_kept():
    for t in ("木子李，就是李子的李", "立早章，文章的章"):
        assert red(t) == t
    assert red("木子李，就是李子的李，春天的春") == "木子李，就是李子的李，****"


def test_negative_ordinary_text():
    for t in ("伟大的祖国", "明天的会", "我的卡", "伟大的伟人", "东方的东西", "明天的明天会更好", "这是大家的家",
              "他说好的好处呢", "我的卡号发你了，明天的会别迟到", "李子的李"):
        assert red(t) == t


def test_regression_no_star_de_wei():
    """回归：「伟大的伟」不能打成「**的伟」，整段打掉，人设不会读成「那个号的伟」。"""
    import re
    for t in ("弓长张，伟大的伟", "收款人叫张伟晨，伟大的伟", "收款户名张伟晨，弓长张，伟大的伟，早晨的晨", "伟是伟大的伟，晨是早晨的晨"):
        out = red(t)
        assert not re.search(r"\*的|的伟|的晨", out), (t, out)
        said = vague_digits(out)
        assert not re.search(r"的伟|的晨|号的", said), (t, said)


def test_joiner_when_explain_abuts_masked_name():
    t = "户名写耳东陈陈东屿东是东方的东，岛屿的屿"
    out = red(t)
    assert out == "户名写耳东陈***" + load("extractors")["nameRules"]["explain"]["joiner"] + "******，****"
    assert vague_digits(out) == "户名写那个名字"


@pytest.mark.parametrize("t", ["收款人叫张伟明，弓长张，伟大的伟，明天的明。", "收款人叫张伟明，弓长张，伟大的伟。",
                               "收款人叫张伟明，龚厂长，伟大的伟，明天的明。", "好的，龚厂长，伟大的伟，明天的明，我记下了"])
def test_probe_and_asr_gongchangzhang_no_single_char(t):
    """#185 拆字探针原句与 ASR「龚厂长」：解释段不露单字「伟」「明」。"""
    out = red(t)
    for leak in ("伟", "明", "**的"):
        assert leak not in out, (t, out)


XFAIL = [c for c in CASES if c.get("xfail")]


@pytest.mark.parametrize("case", XFAIL, ids=[c["text"] for c in XFAIL])
@pytest.mark.xfail(strict=True, reason="#185 已知缺陷：ASR 拆字变体「龚厂长」+ 单段解释仍露「伟」，修复归语音（#163）")
def test_known_gap_asr_split_variant(case):
    assert case["leak"] not in red(case["text"])
