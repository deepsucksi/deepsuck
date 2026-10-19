"""#206 第六条探针（语音 P0）：通话里 voice.persona.heard_refs 对已打码星号的判断。

用例 tests/fixtures/heard_refs_p0.json（与 tests/heard_refs_p0.test.js、python/tests/test_heard_refs_p0.py 共用）。
"""
import json
from pathlib import Path

import pytest

from voice import persona as P

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/heard_refs_p0.json").read_text(encoding="utf-8"))

CASES = [pytest.param(c, marks=pytest.mark.xfail(reason=c["xfail"], strict=True)) if c.get("xfail") else c for c in F["cases"]]


def ok(expect, refs):
    if expect == "name+number":
        return "name" in refs and "number" in refs
    if expect == "number":
        return "number" in refs and "name" not in refs
    if expect == "name":
        return "name" in refs
    return "name" not in refs


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["text"])
def test_voice_heard_refs_p0(case):
    refs = P.heard_refs([case["text"]])
    assert ok(case["expect"], refs), (case["text"], case["expect"], refs)


@pytest.mark.parametrize("case", F["speak"], ids=lambda c: c["text"])
def test_voice_probe_otp_is_number(case):
    assert sorted(P.heard_refs([case["text"]])) == case["heard"]
