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
    if "那个名字" in out:  # #227：字段词 + 姓 + 星号念「那个名字」，此时原名的姓和名一个字都不能出现
        text, red = case["text"], case["redacted"]
        stars = [i for i, c in enumerate(red) if c in "*＊"]
        assert stars, case
        name = text[stars[0] - 1:stars[-1] + 1]  # 姓 + 被星号盖住的名
        assert not any(c in out for c in name), (text, out, name)
    else:
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
    # #222（负责人定）：有「speak」的用例（打码金额「我只有****块钱」）语音与文本端 sanitizeReply 一致，念 speak；「vague」是文本端 vagueDigits 的出口
    want = case.get("speak", case["vague"])
    assert unmask(case["text"]) == want
    assert speakable(case["text"], calm_tts=False) == want


@pytest.mark.parametrize("case", PR["name"], ids=[c["text"] for c in PR["name"]])
def test_guard_unmask_real_names(case):
    out = unmask(guard_output(case["text"]))
    assert out == case["reply"] and case["name"] not in out, (case["text"], out)
    assert speakable(case["text"], calm_tts=False) == case["reply"]


@pytest.mark.parametrize("case", PR["maskedName"], ids=[c["text"] for c in PR["maskedName"]])
def test_unmask_masked_names(case):
    assert unmask(case["text"]) == case["reply"]
