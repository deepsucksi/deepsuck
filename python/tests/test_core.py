"""Python 端独有行为的单元测试。"""
import json

from deepsuck import Session, extract_sensitive, redact_text, extract


def test_report_never_leaks_raw():
    s = Session("police", "li")
    s.reply("把钱转到 六二二二 零二零二 零零一一 二二三三 四四五，有问题打 幺三九 零零幺幺 二二三三")
    s.end()
    js = json.dumps(s.report(), ensure_ascii=False)
    assert "二二三三" not in js and "6222020200112233445" not in js
    assert sorted(i["type"] for i in s.intel_list()) == ["bank_card", "phone"]
    raw = {i["type"]: i["raw"] for i in s.raw_intel()}
    assert raw["phone"].replace(" ", "") == "13900112233"
    assert "非官方项目，与 DeepSeek 无关" in s.report()["generator"]


def test_bot_output_is_redacted():
    s = Session("refund", "wang")
    msg = s.record_bot("我的卡号是 6222020200112233445", "generic")
    assert "6222020200112233445" not in msg["text"]


def test_redact_text_roundtrip():
    t = "加 微 信 kefu_tb2026，电话 13900112233"
    out = redact_text(t, extract(t))
    assert "kefu_tb2026" not in out and "13900112233" not in out
    assert len(extract_sensitive(t)) == 2
