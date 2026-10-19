"""#185 / #147：输出守卫的脱敏不能把人设自己的话打成「户名没**」「户名和***」「叫*」。
用例与共享核心同一组：tests/fixtures/name_stopchars.json 的 redactKeep147 / redactKeep / redactMask（字表在 site/assets/core/name_stopchars.json）。"""
import json
import re
from pathlib import Path

import pytest

from voice.persona import guard_output

ROOT = Path(__file__).resolve().parents[2]
FX = json.loads((ROOT / "tests/fixtures/name_stopchars.json").read_text(encoding="utf-8"))
STAR = re.compile(r"[\u4e00-\u9fa5][*＊]")


@pytest.mark.parametrize("text", FX["redactKeep147"] + FX["redactKeep"])
def test_guard_keeps_persona_words(text):
    assert not STAR.search(guard_output(text)), (text, guard_output(text))


@pytest.mark.parametrize("case", FX["redactMask"], ids=[c["text"] for c in FX["redactMask"]])
def test_guard_still_masks_real_names(case):
    out = guard_output(case["text"])
    assert "*" in out or "＊" in out, (case["text"], out)


# ---- #201 人设侧姓名替换读共用字表（与 tests/name_stopchars_persona.test.js、python/tests/test_name_stopchars_persona.py 同一组）
from voice.persona import speakable, unmask  # noqa: E402

PR = FX["personaReply"]


@pytest.mark.parametrize("text", PR["keep"])
def test_guard_unmask_keeps_persona_words(text):
    """「户名和账号」「收款人信息」「户名和开户行」「户名有了吗」不替成「那个名字」。"""
    assert unmask(guard_output(text)) == text
    assert speakable(text, calm_tts=False) == text


@pytest.mark.parametrize("case", PR["notSurname"], ids=[c["text"] for c in PR["notSurname"]])
def test_unmask_you_not_surname(case):
    assert unmask(case["text"]) == case["vague"]
    assert speakable(case["text"], calm_tts=False) == case["vague"]


@pytest.mark.parametrize("case", PR["name"], ids=[c["text"] for c in PR["name"]])
def test_guard_unmask_real_names(case):
    out = unmask(guard_output(case["text"]))
    assert out == case["reply"] and case["name"] not in out, (case["text"], out)
    assert speakable(case["text"], calm_tts=False) == case["reply"]


@pytest.mark.parametrize("case", PR["maskedName"], ids=[c["text"] for c in PR["maskedName"]])
def test_unmask_masked_names(case):
    assert unmask(case["text"]) == case["reply"]
