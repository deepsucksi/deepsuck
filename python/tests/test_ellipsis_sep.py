"""省略号当数字分隔（断续报号、ASR 转写），与 tests/extractor_fixes.test.js 同一组断言。"""
from deepsuck import extract_sensitive


def types(t):
    return {e["type"] for e in extract_sensitive(t)}


def test_ellipsis_digit_sep():
    assert "bank_card" in types("卡号6222…0212…3456…7890…123")
    assert "phone" in types("手机号138…0013…8000")
    assert "bank_card" in types("卡号六二二二…零二一二…三四五六…七八九零…一二三")
    assert not types("给你转了200…等等")
    assert not types("嗯…等一下…好")
