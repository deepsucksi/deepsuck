"""两边说话人、卡号片段、人设侧兜底（#120）：与 tests/redact_dialog.test.js 对应，规则在 core/extractors.json 的 redact.card / redact.persona。"""
import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import find_card_spans, redact_card_segments, redact_dialog_segments, redact_persona

from conftest import fixture

DLG = fixture("redact")["dialog"]


def each(segs):
    return [redact_text(t, extract_sensitive(t)) for t in segs]


@pytest.mark.parametrize("case", DLG, ids=[" | ".join(c["segments"]) for c in DLG])
def test_dialog_parity(case):
    out = redact_dialog_segments(each(case["segments"]), case["roles"])
    assert out == case["redacted"]
    assert (out != case["segments"]) == (case["expect"] == "mask")
    assert redact_dialog_segments(out, case["roles"]) == out   # 可重复执行


def test_dialog_fixture_has_both_kinds():
    assert sum(c["expect"] == "mask" for c in DLG) >= 8
    assert sum(c["expect"] == "keep" for c in DLG) >= 6


def test_probe_regressions():
    """探针三句：人设复述的半截验证码、卡号片段、手机号前缀都不留数字。"""
    assert redact_dialog_segments(["嗯…验证码是472？"], ["bot"]) == ["嗯…验证码是***？"]
    assert redact_dialog_segments(["6222开头…尾号0123对吧"], ["bot"]) == ["****开头…尾号****对吧"]
    assert redact_dialog_segments(["138开头…后面是零零幺三"], ["bot"]) == ["***开头…后面是****"]


def test_scammer_side_unchanged_for_public_intel():
    assert redact_dialog_segments(["138开头…后面是零零幺三"], ["scammer"]) == ["138开头…后面是零零幺三"]
    assert redact_dialog_segments(["你手机尾号0123是吧"], ["scammer"]) == ["你手机尾号0123是吧"]
    assert redact_dialog_segments(["6222开头…尾号0123对吧"], ["scammer"]) == ["****开头…尾号****对吧"]


def test_card_spans():
    assert find_card_spans("400开头的电话") == []
    assert find_card_spans("138开头") == []
    assert find_card_spans("银行卡客服 400 开头") == []
    assert [s["masked"] for s in find_card_spans("银行卡 955 开头")] == ["***"]
    assert redact_card_segments(["你那张卡", "尾号多少", "尾号 0123"]) == ["你那张卡", "尾号多少", "尾号 ****"]


def test_persona_fallback_amount_and_time():
    """人设侧兜底：连续 3 位以上逐位数字打码（金额 1000 也打），带位值的中文数和不足 3 位的不打。"""
    assert redact_persona("我只有1000块") == "我只有****块"
    assert redact_persona("我只有五百块，下午三点半到") == "我只有五百块，下午三点半到"
    assert redact_persona("10:30 到，就 20 块钱") == "10:30 到，就 20 块钱"
    assert redact_persona("幺三八") == "***"
    assert redact_persona(None) == ""
