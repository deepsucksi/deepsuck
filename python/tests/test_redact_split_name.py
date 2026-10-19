"""拆字报姓打码（#139）：与 tests/redact_split_name.test.js 对应，规则在 core/extractors.json 的 nameRules.split。"""
import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import find_name_spans, redact_dialog_segments
from deepsuck.sim import NAMES, load_scripts, split_name

from conftest import fixture

SPLIT = fixture("redact")["splitName"]


def red(t):
    return redact_text(t, extract_sensitive(t))


@pytest.mark.parametrize("case", SPLIT, ids=[c["text"] for c in SPLIT])
def test_split_name_parity(case):
    ents = extract_sensitive(case["text"])
    assert find_name_spans(case["text"], ents) == case["spans"]
    out = redact_text(case["text"], ents)
    assert out == case["redacted"]
    assert (out != case["text"]) == (case["expect"] == "mask")


def test_fixture_has_both_kinds():
    assert sum(c["expect"] == "mask" for c in SPLIT) >= 8
    assert sum(c["expect"] == "keep" for c in SPLIT) >= 6


def test_probe_sentence():
    """线上探针原句与 ASR 输出：不留 张三丰 / 三丰 / 弓长张三丰。"""
    for t in ("收款户名张三丰，弓长张，三丰", "收款户名张三丰。弓长张三丰。"):
        out = red(t)
        for leak in ("张三丰", "三丰", "弓长张三丰"):
            assert leak not in out, (t, out)
    assert red("收款户名张三丰，弓长张，三丰") == "收款户名张**，弓长张，**"
    assert red("收款户名张三丰。弓长张三丰。") == "收款户名张**。弓长张**。"


def test_split_without_trigger():
    assert red("木子李四") == "木子李*"
    assert red("耳东陈小明") == "耳东陈**"
    assert red("户名木子李四") == "户名木子李*"
    assert [e["value"] for e in extract_sensitive("户名木子李四") if e["type"] == "name"] == ["李四"]


def test_negative_ordinary_text():
    for t in ("他的成长很快，木头桌子，长木凳", "长期有效，木材加工厂", "弓长张，你好", "木子李，就是李子的李",
              "三丰路营业厅", "弓长岭", "去弓长岭的三丰路营业厅"):
        assert red(t) == t


def test_bare_given_name_not_masked_by_static_rule():
    """单独出现的名（「三丰」）不归静态规则管，交给按通话打码（voice #141）。"""
    assert red("三丰会接电话") == "三丰会接电话"


def test_phone_rules_unchanged():
    assert red("弓长张三丰，电话13812345678") == "弓长张**，电话138****5678"
    assert redact_dialog_segments(["弓长张三丰，138开头…后面是零零幺三"], ["scammer"]) == ["弓长张三丰，138开头…后面是零零幺三"]


SIM_NAMES = list(NAMES) + ["张三丰", "李四", "陈小明", "黄晓东", "程一", "林夕", "许嵩", "王小二"]


def test_sim_split_reveal_lines_masked():
    """模拟器台词：报完户名再用拆字复述（eval/scammer-scripts.json 的 revealSplitName），全名与拆字+名都不留。"""
    tpls = load_scripts("legacy")["common"]["revealSplitName"]
    assert len(tpls) >= 3
    checked = 0
    for name in SIM_NAMES:
        sp = split_name(name)
        if not sp:
            continue
        for tpl in tpls:
            line = tpl.format(name=name, **sp)
            out = red(line)
            assert name not in out, (line, out)
            assert sp["name_split"] + sp["name_given"] not in out, (line, out)
            assert sp["name_split"] + "，" + sp["name_given"] not in out, (line, out)
            if len(sp["name_given"]) >= 2:
                assert sp["name_given"] not in out, (line, out)
            assert name[0] + "*" * (len(name) - 1) in out   # 格式与现有姓名打码一致（张**）
            checked += 1
    assert checked >= 40
