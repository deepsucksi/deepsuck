"""#259：charExplain 整组**原文**（不只是已打码文本）过 name_say_regions / redact_line 不抛、不残留姓名。

charExplain[15]（ASR 漏逗号、解释链 ≥2 段）曾在 redact.py name_say_regions.end_ok 读后续 unit 的 head 抛 KeyError。"""
import os
import sys

import pytest

from deepsuck import extract_sensitive
from deepsuck.redact import name_say_regions

from conftest import fixture

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CASES = fixture("redact")["charExplain"]


def _redact_line(t):
    from voice.callredact import _redact_line_raw  # 不走 fail-closed 兜底：必须真的不抛
    return _redact_line_raw(t)


@pytest.mark.parametrize("i", range(len(CASES)))
def test_char_explain_raw_no_raise(i):
    t = CASES[i]["text"]
    regs = name_say_regions(t, extract_sensitive(t))
    assert all(0 <= a < b <= len(t) for a, b in regs)
    out = _redact_line(t)
    if CASES[i]["expect"] == "mask":
        assert out != t
        # 被打码的片段（fixture spans）一个都不能原样留下
        for sp in CASES[i]["spans"]:
            frag = t[sp["start"]:sp["end"]].lstrip("，, ")
            if len(frag) >= 2:
                assert frag not in out, (i, sp)


def test_char_explain_15_no_name_left():
    t = CASES[15]["text"]
    assert name_say_regions(t, extract_sensitive(t))   # 修复前：KeyError: 'head'
    out = _redact_line(t)
    for frag in (t[6:9], t[7:9], t[-9:-5], t[-4:]):    # 姓名、名、两段逐字解释
        assert frag not in out


def test_char_explain_regions_match_js_contract():
    """与 tests/redact_char_explain.test.js 的 #259 用例对应：[15] 原文有区间。"""
    t = CASES[15]["text"]
    assert len(name_say_regions(t, extract_sensitive(t))) > 0
