"""#201 人设侧姓名替换读共用字表 site/assets/core/name_stopchars.json（不另抄一份），与 tests/name_stopchars_persona.test.js
同一组用例（tests/fixtures/name_stopchars.json 的 personaReply）：「有」不当姓；「户名和账号」「收款人信息」「户名和开户行」不替成
「那个名字」；拿不准一律当姓名（「户名和平」「收款人姓和」「户名有志强」）。语音 guard_output → unmask 见 voice/tests/test_name_stopchars_guard.py。"""
import pathlib

import pytest

from conftest import fixture
from deepsuck.core import load
from deepsuck.engine import vague_digits
from deepsuck.extractors import stop_surname
from deepsuck.refs import mask_names, speak_masked

PR = fixture("name_stopchars")["personaReply"]


@pytest.mark.parametrize("text", PR["keep"])
def test_persona_words_kept(text):
    assert mask_names(text) == text
    assert speak_masked(text) == text
    assert vague_digits(text) == text


@pytest.mark.parametrize("case", PR["notSurname"], ids=[c["text"] for c in PR["notSurname"]])
def test_you_not_surname(case):
    assert speak_masked(case["text"]) == case["speak"]
    assert vague_digits(case["text"]) == case["vague"]


@pytest.mark.parametrize("case", PR["maskedName"], ids=[c["text"] for c in PR["maskedName"]])
def test_masked_names_still_named(case):
    assert speak_masked(case["text"]) == case["reply"]
    assert vague_digits(case["text"]) == case["reply"]


def test_stop_surname_reads_core_table():
    for r in load("name_stopchars")["chars"]:
        assert stop_surname(r["char"], "**" if not r["surname"] else "\u0001") is (not r["surname"]), r["char"]
    assert stop_surname("张", "**") is None
    assert stop_surname("信", "息") is True and stop_surname("和", "账号") is True and stop_surname("和", "平") is False


def test_no_private_copy():
    root = pathlib.Path(__file__).resolve().parents[1] / "deepsuck"
    for f in ("refs.py", "engine.py"):
        src = (root / f).read_text(encoding="utf-8")
        assert "masked_lead_not_surname" in src and 'in _DE["notSurname"] else' not in src, f
