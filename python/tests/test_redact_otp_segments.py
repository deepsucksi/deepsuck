"""跨 ASR 分段的验证码打码（#92）：与 tests/redact_otp_segments.test.js 对应，规则在 core/extractors.json 的 redact.otp.seg*。"""
import re

import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.engine import Session
from deepsuck.redact import find_otp_spans_segments, otp_seg_window, redact_otp_segments
from deepsuck.rng import mulberry32

from conftest import fixture

SEG = fixture("redact")["otpSegments"]
DIGIT = re.compile(r"[0-9０-９零〇一二三四五六七八九幺两]")


def each(segs):
    return [redact_text(t, extract_sensitive(t)) for t in segs]


@pytest.mark.parametrize("case", SEG, ids=[" | ".join(c["segments"]) for c in SEG])
def test_otp_segments_parity(case):
    e = each(case["segments"])
    assert find_otp_spans_segments(e) == case["spans"]
    assert redact_otp_segments(e) == case["redacted"]
    assert (redact_otp_segments(e) != e) == (case["expect"] == "mask")
    # 可重复执行：对结果再跑一遍不变
    assert redact_otp_segments(case["redacted"]) == case["redacted"]


def test_otp_segments_fixture_covers_two_three_and_negatives():
    mask = [c for c in SEG if c["expect"] == "mask"]
    keep = [c for c in SEG if c["expect"] == "keep"]
    assert any(len(c["segments"]) == 2 for c in mask) and any(len(c["segments"]) == 3 for c in mask)
    assert len(keep) >= 8
    for c in mask:  # 跨段命中时，被拆开的验证码各段数字都不留
        for sps in c["spans"]:
            for sp in sps:
                assert not DIGIT.search(sp["masked"])


def test_otp_segments_examples():
    assert redact_otp_segments(["验证码是 38", "27 15"]) == ["验证码是 **", "** **"]
    assert redact_otp_segments(["验证码是 38。", "27，", "15"]) == ["验证码是 **。", "**，", "**"]
    assert redact_otp_segments(["校验码是三八", "二七", "一五"]) == ["校验码是**", "**", "**"]
    assert redact_otp_segments(["验证码收到了吧", "那你先转 3000 元"]) == ["验证码收到了吧", "那你先转 3000 元"]
    assert redact_otp_segments(["验证码已发送", "下午 3 点", "15 分到"]) == ["验证码已发送", "下午 3 点", "15 分到"]
    assert redact_otp_segments([]) == [] and redact_otp_segments(None) == []
    assert redact_otp_segments(["验证码 472915"]) == ["验证码 ******"]   # 单段时与 find_otp_spans 一致
    assert redact_otp_segments([None, "验证码 38", "2715"]) == ["", "验证码 **", "****"]


def test_otp_segments_window():
    assert otp_seg_window() == 2
    far = ["验证码是", "嗯", "嗯", "嗯", "嗯", "嗯", "38 27 15"]   # 隔得太远（超出前后 2 段）不算
    assert redact_otp_segments(far) == far
    assert redact_otp_segments(["验证码是 38", "嗯", "27 15"], window=0) == ["验证码是 38", "嗯", "27 15"]


def test_session_masks_split_otp_across_turns():
    s = Session(scenario="refund", persona="lin", rng=mulberry32(1), now=lambda: 0)
    a1 = s.ingest("验证码是 38")
    assert a1["redacted"] == "验证码是 38"   # 只听到前半段时还判断不了
    s.record_bot("嗯你慢点说", "generic")
    a2 = s.ingest("27 15")
    assert a2["redacted"] == "** **"
    scam = [m["text"] for m in s.messages if m["role"] == "scammer"]
    assert scam == ["验证码是 **", "** **"]
    assert "38" not in str(s.report())


def test_session_keeps_amount_after_otp_keyword():
    s = Session(scenario="refund", persona="lin", rng=mulberry32(1), now=lambda: 0)
    s.ingest("验证码收到了吧")
    assert s.ingest("那你先转 3000 元")["redacted"] == "那你先转 3000 元"
    assert s.ingest("下午 3 点")["redacted"] == "下午 3 点"
