"""#130：打码片段（张**、王*明、李*、bi***tc.top）发出前换成含糊说法；叠出来的“没听清”“那几个数”只留一个；
人设提示词写死“不复述对方说的任何人名”（网页、语音、promptRules 同一句）。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import vague_digits  # noqa: E402

PJ = json.loads((ROOT / "site/assets/core/personas.json").read_text(encoding="utf-8"))
RULE = PJ["nameRule"]


@pytest.mark.parametrize("src,surname", [
    ("户名是张**对吧？", "张"), ("是王*明吗", "王"), ("李*…是这个名字？", "李"), ("姓张**的那个？", "张"),
    ("欧阳**是谁啊", "欧阳"),
])
def test_masked_names_fully_replaced(src, surname):
    out = vague_digits(src)
    assert "*" not in out, out
    assert "那个名字" in out, out
    assert surname + "那个" not in out and "姓王的那个人" not in out, out
    assert vague_digits(out) == out  # 幂等


def test_wang_star_ming_leaves_no_tail():
    assert vague_digits("是王*明吗") == "是那个名字吗"


def test_name_followed_by_function_word_keeps_it():
    assert vague_digits("户名是张**是吧？") == "户名是那个名字是吧？"


def test_other_masks_become_vague():
    for src in ("你发的bi***tc.top", "邮箱ab***@qq.com", "bi***t***.top"):
        out = vague_digits(src)
        assert "*" not in out and not re.search(r"[A-Za-z]{2}", out), out


def test_vague_phrases_not_repeated():
    for src in ("嗯…卡号6222 **** **** 7890，尾号7890，验证码472是吧",
                "6222开头…尾号0123对吧，还有138开头…后面是零零幺三",
                "金额是3000块，3000块对吧，就3000块"):
        out = vague_digits(src)
        assert out.count("没听清") <= 1 and out.count("那几个数") <= 1, out
        assert not re.search(r"\d{2,}|[零一幺二两三四五六七八九]{3,}", out), out
        assert not re.search(r"[，,、…]{2,}[，,、]|[，,、]{2,}", out), out  # 合并后句子通顺，不留连串标点


def test_name_rule_shared_everywhere():
    assert RULE.startswith("不复述对方说的任何人名") and "那个名字" in RULE and "户名没记全" in RULE
    assert PJ["promptRules"][-1] == RULE
    assert all(p["voiceStyle"][-1] == RULE for p in PJ["personas"])


def test_voice_prompt_carries_name_rule():
    from voice.persona import system_prompt
    for pid in ("wang", "chen", "zheng", "lin"):
        assert RULE in system_prompt(pid, "refund", "generic", [], topics={"bank"}, scenes=["refund"])


def test_llm_ab_unmasks_before_model():
    src = (ROOT / "voice/llm_ab.py").read_text(encoding="utf-8")
    assert 'unmask(a["redacted"])' in src
    from voice.persona import unmask
    for raw in ("户名是王*明", "户名是张**"):
        out = unmask(raw)
        assert "*" not in out and "那个号" not in out, out
