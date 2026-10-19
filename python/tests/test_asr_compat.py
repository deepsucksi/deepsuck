"""#157：ASR 换 qwen-audio-3.1-asr-flash-streaming 前的人设侧核对用例（与 tests/asr_compat.test.js 对应）。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import vague_digits  # noqa: E402
from deepsuck.extractors import extract  # noqa: E402
from deepsuck.redact import redact_text  # noqa: E402

RAW = ["户名写耳东陈陈晓燕，晓是知晓的晓，燕子的燕。", "户名写耳东陈陈晓燕晓是知晓的晓，燕子的燕。"]


def _redact(t):
    return redact_text(t, extract(t))


@pytest.mark.parametrize("raw", RAW)
def test_split_spelled_masked_name_becomes_name(raw):
    out = vague_digits(_redact(raw))
    assert out.startswith("户名写那个名字"), out
    assert not any(x in out for x in ("耳东", "号", "*")), out
    assert vague_digits(out) == out


def test_split_prefix_before_literal_name_dropped():
    # 语音侧 unmask 已把 陈*** 换成“那个名字”，vague_digits 要去掉残留的“耳东”
    assert vague_digits("户名写耳东那个名字，晓是") == "户名写那个名字，晓是"
    assert vague_digits("弓长张**对吧") == "那个名字对吧"
