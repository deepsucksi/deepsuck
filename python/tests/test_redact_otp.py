"""验证码按上下文打码（#33）：与 tests/redact_otp.test.js 对应，规则在 core/extractors.json 的 redact.otp。"""
import re

import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.redact import find_otp_spans

from conftest import fixture

OTP = fixture("redact")["otp"]


def red(t):
    return redact_text(t, extract_sensitive(t))


@pytest.mark.parametrize("case", OTP, ids=[c["text"] for c in OTP])
def test_otp_parity(case):
    assert find_otp_spans(case["text"]) == case["spans"]
    assert red(case["text"]) == case["redacted"]
    masked = red(case["text"]) != redact_text(
        case["text"], extract_sensitive(case["text"]) + [{"start": 0, "end": len(case["text"]), "sensitive": False}])
    assert masked == (case["expect"] == "mask")
    if case["expect"] == "mask":
        for sp in case["spans"]:
            assert not re.search(r"[0-9零〇一二三四五六七八九幺两]", sp["masked"])


def test_otp_examples():
    assert red("您的验证码是472915，请勿告诉他人") == "您的验证码是******，请勿告诉他人"
    assert red("验证码是 4 7 2 9 1 5") == "验证码是 * * * * * *"
    assert red("动态码 472...915") == "动态码 ***...***"
    assert red("校验码⋯四七二⋯九一五") == "校验码⋯***⋯***"
    assert red("验证码收到了。是…472915") == "验证码收到了。是…******"
    assert red("短信码是 4 7 2，9 1 5") == "短信码是 * * *，* * *"
    assert redact_text("验证码 472915", []) == "验证码 ******"
    assert redact_text("验证码 472915", None) == "验证码 ******"


@pytest.mark.parametrize("t", ["472 915", "验证码已发送至尾号1234的手机", "验证码10分钟内有效", "验证码收到了，转了5000元",
                               "金额是5000，验证码还没来", "验证码？订单号A47291", "我家门牌号 2046，下午三点到",
                               "验证码是多少？我念一下：一二三", "验证码是4位的，卡号后四位是8888"])
def test_otp_negatives(t):
    assert red(t) == t


def test_entities_keep_their_own_masks():
    assert red("验证码发到13800001111了") == "验证码发到138****1111了"
    assert red("卡号6222020200112233445，验证码等会给你") == "卡号622202*********3445，验证码等会给你"
    assert find_otp_spans("验证码发到 138 0000 1111 了") == []
