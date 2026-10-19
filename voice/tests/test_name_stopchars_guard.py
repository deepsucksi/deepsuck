"""#185 / #147：输出守卫的脱敏不能把人设自己的话打成「户名没**」「户名和***」「叫*」。
用例与共享核心同一组：tests/fixtures/name_stopchars.json 的 redactKeep / redactMask（字表在 site/assets/core/name_stopchars.json）。"""
import json
import re
from pathlib import Path

import pytest

from voice.persona import guard_output

ROOT = Path(__file__).resolve().parents[2]
FX = json.loads((ROOT / "tests/fixtures/name_stopchars.json").read_text(encoding="utf-8"))
STAR = re.compile(r"[\u4e00-\u9fa5][*＊]")


@pytest.mark.parametrize("text", FX["redactKeep"])
def test_guard_keeps_persona_words(text):
    assert not STAR.search(guard_output(text)), (text, guard_output(text))


@pytest.mark.parametrize("case", FX["redactMask"], ids=[c["text"] for c in FX["redactMask"]])
def test_guard_still_masks_real_names(case):
    out = guard_output(case["text"])
    assert "*" in out or "＊" in out, (case["text"], out)
