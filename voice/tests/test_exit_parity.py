"""#163 复审：语音出口（speakable / guard_output）与 web、refs（夹具 tests/fixtures/redact.json 的 exitParity）逐项一致、不露姓名。"""
import json
import re
from pathlib import Path

import pytest

from voice.persona import guard_output, speakable

CASES = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/redact.json").read_text(encoding="utf-8"))["exitParity"]


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_voice_exit_parity(case):
    for out in (speakable(case["text"]), guard_output(case["text"])):
        assert out == case["expected"], (case["text"], out)
        if case["expect"] == "mask":
            assert not re.search("[" + case["leak"] + "*＊]", out), (case["text"], out)
