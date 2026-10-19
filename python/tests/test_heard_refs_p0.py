"""#206 第六条探针（语音 P0）：已打码星号的代称种类，与 llm.js heardRefs 一致。

用例 tests/fixtures/heard_refs_p0.json（与 tests/heard_refs_p0.test.js、voice/tests/test_heard_refs_p0.py 共用）。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from deepsuck import extract_sensitive, redact_text  # noqa: E402
from deepsuck.refs import heard_refs, speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/heard_refs_p0.json").read_text(encoding="utf-8"))


def ok(expect, refs):
    if expect == "name+number":
        return "name" in refs and "number" in refs
    if expect == "number":
        return "number" in refs and "name" not in refs
    if expect == "name":
        return "name" in refs
    return "name" not in refs


def test_case_count():
    assert len(F["cases"]) >= 37


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["text"])
def test_heard_refs_p0(case):
    refs = heard_refs([case["text"]])
    assert ok(case["expect"], refs), (case["text"], case["expect"], refs)


@pytest.mark.parametrize("case", F["speak"], ids=lambda c: c["text"])
def test_probe_otp_spoken_as_number(case):
    red = redact_text(case["text"], extract_sensitive(case["text"]))
    assert red == case["redacted"]
    sp = speak_masked(red)
    assert sp == case["spoken"]
    assert "那个号" in sp and "那个名字" not in sp
    assert sorted(heard_refs([case["text"]])) == case["heard"]
