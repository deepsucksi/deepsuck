"""#216 P0：对方没报过户名时的露字。用例 tests/fixtures/unsaid_leaks.json，与 tests/unsaid_leaks.test.js 共用。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck import extract_sensitive, redact_text  # noqa: E402
from deepsuck.refs import collapse_spaced_stars, heard_refs, speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/unsaid_leaks.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["text"])
def test_redact(case):
    assert redact_text(case["text"], extract_sensitive(case["text"])) == case["redacted"]


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["text"])
def test_speak(case):
    out = speak_masked(case["redacted"])
    assert out == case["speak"]
    assert not re.search(r"[*＊]", out)


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["text"])
def test_heard_refs(case):
    assert sorted(heard_refs([case["redacted"]])) == case["refs"]


def test_person_name_extracted():
    vals = [e["value"] for e in extract_sensitive("对方叫李四是吧") if e["type"] == "name"]
    assert vals == ["李四"]
    for t in ("对方叫什么", "他叫我等着", "对方叫你转账", "他叫王经理"):
        assert not [e for e in extract_sensitive(t) if e["type"] == "name"], t


@pytest.mark.parametrize("text", ["138 **** 1234", "6222 **** **** 1234", "尾号 **** 1234"])
def test_number_separators_untouched(text):
    assert collapse_spaced_stars(text) == text
    assert "name" not in heard_refs([text])
