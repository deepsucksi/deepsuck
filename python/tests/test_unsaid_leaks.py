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


NOT_NAME = [c for c in F["cases"] if c.get("notName")]


@pytest.mark.parametrize("case", NOT_NAME, ids=lambda c: c["text"])
def test_not_name_untouched(case):
    """#221：「叫」后面不是名字（他叫你转账、对方叫黄牛、她叫钱先到账……）不打码、不念成「那个名字」。"""
    t = case["text"]
    assert redact_text(t, extract_sensitive(t)) == t
    assert speak_masked(t) == t and "那个名字" not in speak_masked(t)


@pytest.mark.parametrize("case", [c for c in F["cases"] if c.get("keepTail") or c.get("mustMask")], ids=lambda c: c["text"])
def test_keep_tail_and_must_mask(case):
    """#221：「**明说他转」「张**让你转账」不丢后面的字；「对方叫钱明」「他叫马丽」「叫安华」照样打码。"""
    out = speak_masked(redact_text(case["text"], extract_sensitive(case["text"])))
    assert "*" not in out
    if case.get("keepTail"):
        assert out.endswith(case["keepTail"]), out
    else:
        assert case["mustMask"] not in out and "那个名字" in out, out


@pytest.mark.parametrize("case", [c for c in F["cases"] if c.get("voiceExpect")], ids=lambda c: c["text"])
def test_surname_star_place_not_leaked(case):
    """#221 语音 P0：「李*那边」念「那个名字那边」，不露姓；「我在*那边」照旧不当姓名。"""
    out = speak_masked(redact_text(case["text"], extract_sensitive(case["text"])))
    assert not re.search(r"[李王张刘](?:你发的)?那个", out) and "*" not in out, out
    assert ("那个名字" in out) == ("那个名字" in case["voiceExpect"]), out
