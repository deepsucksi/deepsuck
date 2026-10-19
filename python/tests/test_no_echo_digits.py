"""#121：人设不复述数字（对方说过的也不行），回复发出前过一道数字过滤。

现网探针抓到的三句做回归：「嗯…验证码是472？」「6222开头…尾号0123对吧」「138开头…后面是零零幺三」。
开头几位、尾号都算违规，只允许单个数字（“好像是6开头的”）。过滤在错别字扰动之后、语音合成之前。
网页端同一套规则见 tests/no_echo_digits.test.js（共用 personas.json 的 digitEcho）。
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.core import load  # noqa: E402
from deepsuck.engine import Session, vague_digits  # noqa: E402
from personas.humanize import Humanizer  # noqa: E402

PROBES = ["嗯…验证码是472？", "6222开头…尾号0123对吧", "138开头…后面是零零幺三"]
# 两个及以上数字挨着（阿拉伯、全角、中文数字，夹空格顿号短横、打码星号也算挨着）就是违规
DIGIT = "0-9０-９零〇一幺二两三四五六七八九"
ECHO = re.compile(f"[{DIGIT}](?:[\\s、,，\\-*＊]{{0,2}}[{DIGIT}])+")


def echoes(text):
    # “一下”“一点”这类不是数字；这里只看两个数字挨着的情况，单个汉字数字不算
    return ECHO.findall(text)


def test_probe_lines_have_no_digit_runs_after_filter():
    out = [vague_digits(t) for t in PROBES]
    assert out == ["嗯…验证码是那几个数没听清？", "好像是6开头的…后面几位没听清对吧", "好像是1开头的…后面几位没听清"]
    for o in out:
        assert not echoes(o), o


@pytest.mark.parametrize("text", [
    "验证码 4 7 2 9", "一三八 零零 幺三", "6二22开头的", "幺三八开头", "卡号 6222 **** **** 7890", "尾号 ****7890",
    "130****8600？尾号是8600？", "最后四位是3445吧", "后三位幺三八", "末尾０１２３", "4、7、2对吧", "138-0013",
])
def test_every_form_of_digit_run_is_vague(text):
    out = vague_digits(text)
    assert not echoes(out), (text, out)
    assert re.search("没听清|开头", out), out


@pytest.mark.parametrize("text", ["好像是6开头的", "分期是12期还是24期？", "我刚才那 5 块钱", "两三百块", "等我一下", "一二十分钟吧"])
def test_single_and_double_digits_untouched(text):
    assert vague_digits(text) == text


def test_filter_runs_after_humanize_and_humanize_keeps_digits():
    # 错别字扰动不碰数字及其两边的字（规则不变）；过滤在扰动之后，扰动后的句子过一遍过滤就没有数字串
    for pid in ("wang", "chen", "lin", "zheng"):
        for seed in range(30):
            h = Humanizer(profile=pid, seed=seed)
            for t in PROBES:
                x = h.apply(t).text
                for run in re.findall(r"[0-9]{3,}|[零幺]{2,}[一二三四五六七八九零幺]*", t):
                    assert run in x, (pid, seed, t, x)
                assert not echoes(vague_digits(x)), (pid, seed, x)


def test_record_bot_filters_rule_and_llm_replies():
    s = Session("police", "wang", rng=lambda: 0.3, now=lambda: 0)
    for t in PROBES:
        msg = s.record_bot(t, "coop_step")
        assert not echoes(msg["text"]), msg["text"]


def test_speak_intel_never_says_digits():
    for typ, raw in (("bank_card", "6222020200112233445"), ("phone", "13800138000"), ("qq", "2876543210"), ("alipay", "13800138000")):
        for r in (0.0, 0.34, 0.67, 0.99):
            s = Session("refund", "lin", rng=lambda r=r: r, now=lambda: 0)
            from deepsuck import redact as R
            from deepsuck import extractors as X
            item = next(i for i in X.extract_sensitive(raw if typ != "qq" else "QQ " + raw) if i["type"] in (typ, "phone", "bank_card", "qq"))
            item = dict(item, masked=R.redact_text(raw, [item]) if typ != "qq" else "28******10", label=typ)
            said = s.speak_intel(dict(item, type=typ), raw)
            assert not re.search(r"[0-9]", said), (typ, said)


# 已批准台词里唯一带“两个数字挨着”的人设自报码（小林 otp_stall，自己编的前两位，不是复述对方）。
# 不改已有台词；过滤规则是连续 3 位及以上，所以这句照常发出。要不要换掉由负责人决定（见 PR 说明）。
APPROVED_PAIRS = {"码我看到了，前两位是5、2，后面被通知横幅挡住了，我划一下。"}


def test_rule_replies_never_echo_digits_in_a_session():
    lines = ["我是公安局的，你涉嫌洗钱", "验证码是472，你报一下", "转到6222020200112233445，尾号3445", "打13800138000找我",
             "后面是零零幺三，记住了吗", "你刚才说的卡号是多少？", "验证码多少？念一下"]
    for pid in ("wang", "chen", "lin", "zheng"):
        for seed in range(15):
            from deepsuck.rng import mulberry32
            s = Session("police", pid, rng=mulberry32(seed), now=lambda: 0)
            s.opening()
            for ln in lines:
                r = s.reply(ln)
                if r["text"] in APPROVED_PAIRS:
                    continue
                assert not echoes(r["text"]), (pid, seed, ln, r["text"])


def test_prompt_rules_forbid_echo_without_literal_numbers():
    core = load("personas")
    ih = core["intentHints"]
    for k in ("coop_step", "confirm_intel", "otp_stall"):
        assert "不" in ih[k] and not re.search(r"[0-9]{2,}", ih[k]), (k, ih[k])
    assert "尾号" in ih["coop_step"] and "开头" in ih["coop_step"] and "汉字" in ih["coop_step"]
    assert "后四位" not in ih["confirm_intel"] and "报错一位" not in ih["confirm_intel"]
    assert not any("尾号几位" in r for r in core["promptRules"])


def test_voice_guard_and_tts_text_filtered():
    from voice.persona import guard_output, speakable
    for t in PROBES:
        assert not echoes(guard_output(t)), guard_output(t)
        assert not echoes(speakable(t, calm_tts=True)), speakable(t, calm_tts=True)


def test_llm_ab_digit_echo_metric():
    from voice import llm_ab as AB
    assert AB.digit_echoes("嗯…验证码是472？") == ["472"]
    assert AB.digit_echoes("138开头…后面是零零幺三") == ["138", "0013"]
    assert AB.digit_echoes("好像是6开头的…后面几位没听清") == []
    for t in PROBES:
        assert AB.digit_echoes(vague_digits(t)) == []
