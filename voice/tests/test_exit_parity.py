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
        if case["same"]:
            assert out == case["expected"], (case["text"], out)
        else:  # #163 三审：金额 / 号码的含糊说法各出口本来不同，只比姓名部分
            assert "那个名字" in out, (case["text"], out)
        if case["expect"] == "mask":
            assert not re.search("[" + case["leak"] + "*＊]", out), (case["text"], out)


# #250（冒烟 YA6PUTCA）：通话转写出口（records.redact_line，save_transcript / redact_backfill 共用）与语音、web 一致：
# 打码的转写不露拆字说法和姓，转写再过 guard_output / mask_names 与原句结果相同，反例原样
from deepsuck.extractors import extract_sensitive  # noqa: E402
from deepsuck.redact import redact_text  # noqa: E402
from deepsuck.refs import mask_names, speak_masked  # noqa: E402
from voice.records import redact_line  # noqa: E402


def refs_exit(t):  # 与 python/tests/test_exit_parity.py 同一条文本出口（mask_names → redact_text → speak_masked）
    s = mask_names(t)
    return speak_masked(redact_text(s, extract_sensitive(s)))


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_transcript_exit_parity(case):
    out = redact_line(case["text"])
    if case["expect"] == "keep":
        assert out == case["text"], (case["text"], out)
        return
    assert not re.search("[" + case["leak"] + "]", out), (case["text"], out)
    assert "那个名字" in out, (case["text"], out)
    if case["same"]:  # same=false：号码 / 卡号在转写里本来就打成星号，各出口的含糊说法不同，只比姓名部分
        assert guard_output(out) == guard_output(case["text"]), (case["text"], out)
        assert refs_exit(out) == refs_exit(case["text"]), (case["text"], out)


@pytest.mark.parametrize("text,want", [
    ("转给木子李1000元", "转给那个名字1000元"),
    ("转给木子李一千元", "转给那个名字一千元"),
    ("木子李，1000块", "那个名字，1000块"),
    ("弓长张三500", "那个名字500"),
    ("然后转给木子李1000元。", "然后转给那个名字1000元。"),
])
def test_transcript_split_name_amount(text, want):
    assert redact_line(text) == want
    # 语音读法（guard_output）与转写打码读出来一致：「转给木子李一千元」念成「转给那个名字……」
    assert guard_output(redact_line(text)) == guard_output(text)
    assert refs_exit(redact_line(text)) == refs_exit(text)
    assert "那个名字" in guard_output(text)


@pytest.mark.parametrize("text", ["木头1000块", "弓长岭1000元", "成长一千元", "李子1000块", "张三丰来了", "工长张师傅明天来"])
def test_transcript_normal_words_untouched(text):
    assert redact_line(text) == redact_text(text, extract_sensitive(text))
