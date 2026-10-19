"""#167：人设说出口的话不带两位及以上数字（线上探针 XXMX5LPV 说出「好像是62开头的」）。

用例在 tests/fixtures/digit_cap.json，与 tests/digit_cap.test.js 共用，Python 与 JS 逐字一致；语音端 guard_output / speakable 同样过滤。
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import Session, vague_digits  # noqa: E402

F = json.loads((ROOT / "tests" / "fixtures" / "digit_cap.json").read_text(encoding="utf-8"))
DIGIT = "0-9０-９零〇一幺二两三四五六七八九"
PAIR = re.compile(f"[{DIGIT}](?:[\\s、,，\\-－—·*＊]{{0,2}}[{DIGIT}])+")
APPROX = re.compile("^(?:一两|一二|两三|二三|三四|四五|五六|六七|七八|八九)$")


def pairs(text):
    # 汉字约数（两三天、一二十分钟）和 TRC20 这类写法不是号码
    return [m for m in PAIR.findall(re.sub("TRC20|ERC20|BEP20", "", str(text))) if not APPROX.match(m)]


def test_fixture_has_required_cases():
    ins = [x["in"] for x in F["positive"]]
    for k in ("好像是62开头的", "六二开头", "前两位是6、2"):
        assert k in ins
    assert "好像是6开头的" in F["negative"]


def test_persona_templates_have_no_two_digit_runs():
    # #198：小林 otp_stall[12] / loan_stall[5] / coop_step[7] 换成不带数字的已批台词后，台词库里不再有两个数字挨着的句子
    core = json.loads((ROOT / "site" / "assets" / "core" / "personas.json").read_text(encoding="utf-8"))
    bad = [(p["id"], k, i, t) for p in core["personas"] for k, v in (p.get("templates") or {}).items()
           for i, x in enumerate(v) for t in [x if isinstance(x, str) else x.get("t", "")] if pairs(t)]
    assert bad == []
    lin = next(p for p in core["personas"] if p["id"] == "lin")["templates"]
    for t in (lin["otp_stall"][12], lin["loan_stall"][5], lin["coop_step"][7]["t"]):
        assert t in F["negative"] and vague_digits(t) == t


@pytest.mark.parametrize("case", F["positive"], ids=lambda x: x["in"])
def test_positive_capped_and_same_as_js(case):
    out = vague_digits(case["in"])
    assert out == case["out"]
    assert not pairs(out), out
    assert "好像是好像是" not in out and "像是像是" not in out


@pytest.mark.parametrize("text", F["negative"])
def test_negative_untouched(text):
    assert vague_digits(text) == text


def test_record_bot_filters_two_digit_runs():
    s = Session("police", "wang", rng=lambda: 0.3, now=lambda: 0)
    for x in F["positive"]:
        assert not pairs(s.record_bot(x["in"], "coop_step")["text"]), x["in"]


def test_voice_guard_and_tts_text_capped():
    from voice.persona import guard_output, speakable
    for x in F["positive"]:
        for out in (guard_output(x["in"]), speakable(x["in"], calm_tts=True)):
            assert not pairs(out), (x["in"], out)
