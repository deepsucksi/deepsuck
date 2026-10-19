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
    assert "xfail" not in case  # #163：xfail 已全部修好
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


@pytest.mark.parametrize("t", ["收款人是弓长张，伟大的伟对吧", "收款人是弓长张，伟大的伟", "户名是弓长张，伟大的伟，明天的明",
                               "收款人是弓长张，伟大的伟，对吧", "收款人弓长张，伟大的伟对吗", "收款人是龚厂长，伟大的伟对吧"])
def test_p0_206_probe(t):
    """#206 P0 探针：拆字说法前有「是」、解释后跟「对吧」时不露「伟」「明」。"""
    out = red(t)
    for leak in ("伟", "明", "**的"):
        assert leak not in out, (t, out)


TAIL = fixture("redact")["splitExplainTail"]


@pytest.mark.parametrize("case", TAIL, ids=[c["text"] for c in TAIL])
def test_split_explain_tail_parity(case):
    """#206 夹具 splitExplainTail：与 JS 逐项一致；正例不露「伟」「明」。"""
    ents = extract_sensitive(case["text"])
    assert find_name_spans(case["text"], ents) == case["spans"]
    out = redact_text(case["text"], ents)
    assert out == case["redacted"]
    assert (out != case["text"]) == (case["expect"] == "mask")
    if case["expect"] == "mask":
        for leak in ("伟", "明", "**的"):
            assert leak not in out, (case["text"], out)


def test_p0_206_exact():
    assert red("收款人是弓长张，伟大的伟对吧") == "收款人是弓长张，****对吧"


# #202 复审：同音写法没有解释时按姓名打码（必改 1）；带提示词无逗号不露解释里的字（必改 2）；「龚厂长（的）张」+ 名打码（必改 3）。与 JS 同一组
REVIEW_202 = [
    ("收款人是龚长张", "收款人是龚**"),
    ("收款人是宫长张", "收款人是宫**"),
    ("收款人是龚厂长", "收款人是龚**"),
    ("收款人是工长张", "收款人是工**"),
    ("收款人是尔东陈", "收款人是尔**"),
    ("收款人是龚厂长伟大的伟", "收款人是龚**，****"),
    ("收款人龚厂长伟大的伟", "收款人龚**，****"),
    ("户名龚厂长伟大的伟对吧", "户名龚**，****对吧"),
    ("收款人是工长张伟大的伟", "收款人是工长张****"),
    ("收款人是龚厂长的张伟", "收款人是龚**的张*"),
    ("收款人是龚厂长张伟", "收款人是龚**张*"),
    ("收款人是龚厂长的张，伟大的伟", "收款人是龚**的张，****"),
    ("收款人是龚厂长的张伟大的伟", "收款人是龚**的张****"),
    # 负责人决定（拿不准就遮）：首字是真姓（nameRules.surnames）的同音写法本身也打码，解释段照样打码
    ("收款人是宫长张，伟大的伟", "收款人是宫**，****"),
    ("收款人是龚长张，伟大的伟", "收款人是龚**，****"),
    ("收款人是龚厂长，伟大的伟", "收款人是龚**，****"),
    ("收款人是宫长张伟大的伟", "收款人是宫**，****"),
    ("好的龚厂长，伟大的伟", "好的龚**，****"),
    ("宫长张，伟明，伟大的伟", "宫**，**，****"),
    ("收款人叫张伟明，龚厂长，伟大的伟，明天的明。", "收款人叫张**，龚**，****，****。"),
    ("收款人是弓长张，伟大的伟", "收款人是弓长张，****"),
    ("收款人是工长张，伟大的伟", "收款人是工长张，****"),
    ("收款人是工长张伟大的伟", "收款人是工长张****"),
    ("收款人是尔东陈，晓燕，知晓的晓", "收款人是尔东陈，**，****"),
    ("尔东陈，晓燕，知晓的晓", "尔东陈，**，****"),
    # 情报复审 issuecomment-6265768538 必改表
    ("收款人是龚厂长，伟大的伟对吧", "收款人是龚**，****对吧"),
    ("收款人是宫长张，伟大的伟对吧", "收款人是宫**，****对吧"),
    ("户名宫长张，伟大的伟，明天的明", "户名宫**，****，****"),
    ("户名龚长张，伟大的伟", "户名龚**，****"),
    ("收款人是宫长张伟大的伟是吗", "收款人是宫**，****是吗"),
    ("收款人是龚长张，伟大的伟，早晨的晨对吧", "收款人是龚**，****，****对吧"),
    ("收款人是龚厂长伟，伟大的伟", "收款人是龚***，****"),
]


@pytest.mark.parametrize("t,want", REVIEW_202, ids=[c[0] for c in REVIEW_202])
def test_review_202(t, want):
    assert red(t) == want


def test_name_pattern_has_asr_split_prefix():
    C = load("extractors")
    sp = C["nameRules"]["split"]
    for k, sur in sp["asrSplit"].items():
        assert k + sp["link"] + "(?=" + sur + ")" in C["patterns"]["name"]["source"], k


def test_asr_real_surname_uses_shared_surnames():
    """#202：哪些同音写法本身打码，只看共享核心 nameRules.surnames 里有没有它的首字（龚、宫有；工、尔没有）。"""
    C = load("extractors")
    sp, sur = C["nameRules"]["split"], C["nameRules"]["surnames"]
    for k in sp["asrSplit"]:
        out = red("收款人是" + k + "，伟大的伟")
        assert out == "收款人是" + (k[0] + "*" * (len(k) - 1) if k[0] in sur else k) + "，****", (k, out)


@pytest.mark.parametrize("t", ["收款人是龚厂长，是伟大的伟吗", "收款人是龚厂长！伟大的伟", "收款人是龚厂长——伟大的伟", "收款人是龚厂长，伟 大 的 伟"])
def test_review_202_suggest_lead_masked(t):
    """#202 情报复审建议项（main 原有，分隔符 / 包住 / 带空格的解释另行跟进）：真姓开头的写法本身照样打码。"""
    out = red(t)
    assert "龚厂长" not in out and "龚**" in out, out
