"""#80：人设不报具体数字。

- coop_step 给大模型的提示只允许含糊地说（“好像是…开头的”），不再允许“至多两位虚构数字”，提示里也不放具体数字例子（#77：例子里的数字会被照说）。
- 规则引擎里故意看错数字的台词（“像9又像4”“前两位是5、2”）保留，但这些数字拼起来凑不成完整的号码、卡号或验证码。
"""
import re

from deepsuck import extractors as X
from deepsuck import redact as R
from deepsuck.core import load
from deepsuck.personas import PERSONAS

INTENT_HINTS = load("personas")["intentHints"]

_DIGIT_CHARS = "0-9０-９零〇一二三四五六七八九幺两"
_CN = dict(list(zip("零〇一二三四五六七八九幺两", "0012345678912")) + list(zip("０１２３４５６７８９", "0123456789")))
_D = "[" + _DIGIT_CHARS + "]"
_Q = "[\"“”']?"
# 故意看错 / 看不全的数字台词
MISREAD = [re.compile("像" + _Q + "(" + _D + ")" + _Q + "又像" + _Q + "(" + _D + ")" + _Q),
           re.compile(r"前[两二三]位是(" + _D + r")[、，,\s]*(" + _D + ")")]


def _texts(lst):
    return [x if isinstance(x, str) else x["t"] for x in lst]


def _all_lines(p):
    for intent, pool in p["templates"].items():
        for t in _texts(pool):
            yield intent, t


def _misread_digits(text):
    out = []
    for rx in MISREAD:
        for m in rx.finditer(text):
            out += [_CN.get(g, g) for g in m.groups()]
    return out


def test_coop_step_hint_is_vague_only():
    h = INTENT_HINTS["coop_step"]
    assert "两位" not in h and "数字串" in h and "开头" in h, h
    assert not re.search("[0-9０-９]", h), h  # 提示里不放具体数字例子


def test_coop_step_rule_lines_reveal_no_digits():
    for p in PERSONAS:
        for x in _texts(p["templates"]["coop_step"]):
            # 只允许界面上的字样（“2小时到账”）和下载进度，不报任何号码数字
            rest = re.sub(r"\d+\s*小时到账|\d+\s*%", "", x)
            assert not re.search("[0-9０-９]", rest), (p["id"], x)


def test_misread_lines_kept():
    found = {p["id"]: [t for _, t in _all_lines(p) if _misread_digits(t)] for p in PERSONAS}
    for pid in ("wang", "lin", "zheng"):
        assert found[pid], pid  # “像9又像4”这类台词保留


def test_misread_digits_cannot_form_number():
    for p in PERSONAS:
        lines = [t for _, t in _all_lines(p) if _misread_digits(t)]
        for t in lines:
            assert len(_misread_digits(t)) <= 2, (p["id"], t)
            assert not X.extract_sensitive(t), (p["id"], t)
        # 一个人设所有看错数字的台词全说一遍，拼起来也不到验证码最短的 4 位（更到不了手机号 11 位、卡号 16 位）
        digits = "".join(d for t in lines for d in _misread_digits(t))
        assert len(digits) < 4, (p["id"], digits)
        joined = "，".join(lines)
        assert not X.extract_sensitive(joined), (p["id"], joined)
        assert not R.find_otp_spans("验证码是" + digits), (p["id"], digits)
        assert not R.find_otp_spans("验证码" + joined), (p["id"], joined)


def test_otp_stall_has_no_other_digits():
    """otp_stall 里除了看错数字的那句，不报别的数字（防止和看错的那几位拼起来）。"""
    for p in PERSONAS:
        for t in _texts(p["templates"]["otp_stall"]):
            rest = t
            for rx in MISREAD:
                rest = rx.sub("", rest)
            assert not re.search("[0-9０-９]", rest), (p["id"], t)
