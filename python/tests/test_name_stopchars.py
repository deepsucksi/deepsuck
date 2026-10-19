"""#185 共用字表 site/assets/core/name_stopchars.json 的格式检查（与 tests/name_stopchars.test.js 一致）。"""
from deepsuck.core import load


def test_name_stopchars_format():
    s = load("name_stopchars")
    assert s["schema"] == "deepsuck.core.name_stopchars/v1"
    assert "用途" in s["comment"]
    chars = [r["char"] for r in s["chars"]]
    assert len(chars) == len(set(chars))
    surnames = load("extractors")["nameRules"]["surnames"]
    for r in s["chars"]:
        assert len(r["char"]) == 1 and "\u4e00" <= r["char"] <= "\u9fa5"
        assert r["char"] not in surnames
        assert r["negatives"] and all(r["char"] in t for t in r["negatives"])
    for c in "对是嗯好行哦有没只和谁啥":
        assert c in chars
    words = [r["word"] for r in s.get("words", [])]
    assert len(words) == len(set(words)) and {"什么", "多少"} <= set(words)
    for r in s["words"]:
        assert len(r["word"]) >= 2 and r["negatives"] and all(r["word"] in t for t in r["negatives"])


# ---- #185 行为：应答字、虚词不能当成姓（与 tests/name_stopchars_extract.test.js 同一组用例）
import pytest  # noqa: E402

from conftest import fixture  # noqa: E402
from deepsuck import extract, extract_sensitive, redact_text  # noqa: E402
from deepsuck.engine import Session  # noqa: E402
from deepsuck.extractors import NAME_STOPCHARS  # noqa: E402
from deepsuck.rng import mulberry32  # noqa: E402

FX = fixture("name_stopchars")
STOP = load("name_stopchars")["chars"]


def _names(t):
    return [e["value"] for e in extract(t) if e["type"] == "name"]


def test_stopchars_loaded_from_core():
    assert NAME_STOPCHARS == {r["char"] for r in STOP}


@pytest.mark.parametrize("char,text", [(r["char"], t) for r in STOP for t in r["negatives"]])
def test_core_negatives(char, text):
    assert not any(n[0] == char for n in _names(text)), (text, _names(text))


@pytest.mark.parametrize("text", FX["negatives"])
def test_fixture_negatives(text):
    assert _names(text) == []


@pytest.mark.parametrize("case", FX["positives"], ids=[c["text"] for c in FX["positives"]])
def test_fixture_positives(case):
    assert _names(case["text"]) == [case["name"]]


def test_session_keeps_no_fake_name():
    s = Session(scenario="pig", persona="lin", rng=mulberry32(1000), now=lambda: 0)
    for t in FX["negatives"]:
        s.ingest(t)
    assert not any(i["type"] == "name" for i in s.intel.values())


@pytest.mark.parametrize("word,text", [(r["word"], t) for r in load("name_stopchars")["words"] for t in r["negatives"]])
def test_core_word_negatives(word, text):
    assert not any(n.startswith(word) for n in _names(text)), (text, _names(text))


def test_redact_keep_147_count():
    assert len(FX["redactKeep"]) == 23


@pytest.mark.parametrize("text", FX["redactKeep"])
def test_redact_keep_147(text):
    """#147 输出守卫误打码的人设原话（「户名没记全」「户名和开户行」「户名到底填谁」「户名是啥」）：脱敏后原样不变。"""
    assert redact_text(text, extract_sensitive(text)) == text


@pytest.mark.parametrize("case", FX["redactMask"], ids=[c["text"] for c in FX["redactMask"]])
def test_redact_mask_real_names(case):
    assert redact_text(case["text"], extract_sensitive(case["text"])) == case["redacted"]
