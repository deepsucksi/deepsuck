"""#73：提示词里的号码例子不能被模型原样说出来——llm_ab 的“数字泄露”指标。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "python"):
    sys.path.insert(0, str(p))

from voice import llm_ab as AB  # noqa: E402


def test_norm_digits_handles_spoken_forms():
    assert AB.norm_digits("尾号八六零零是吧") == "尾号8600是吧"
    assert AB.norm_digits("幺三零…后面") == "130…后面"
    assert AB.norm_digits("八 六、零-〇") == "8600"
    assert AB.norm_digits("８６００") == "8600"


def test_cn_readings():
    assert AB.cn_readings("8600") == ["八千六百", "八千六"]
    assert AB.cn_readings("130") == ["一百三十", "一百三"]
    assert AB.cn_readings("8060") == ["八千零六十"]
    assert AB.cn_readings("0451") == [] and AB.cn_readings("12") == []


def test_digit_leaks_counts_prompt_examples_not_said_by_scammer():
    assert AB.digit_leaks("嗯…尾号8600是吧", "把你银行卡尾号报一下") == ["8600"]
    assert AB.digit_leaks("尾号八六零零…对吧", "") == ["8600"]
    assert AB.digit_leaks("八千六…我记不清", "") == ["8600"]
    assert AB.digit_leaks("幺三零…后面忘了", "你手机号多少") == ["130"]
    # 对方先报过的号码，人设复述不算泄露（数字或汉字写法都认）
    assert AB.digit_leaks("尾号8600是吧", "卡号6222 **** 8600") == []
    assert AB.digit_leaks("尾号8600是吧", "尾号八六零零") == []
    assert AB.digit_leaks("哦…卡号我找找。", "把尾号报一下") == []
    assert AB.digit_leaks("尾号3307？", "", examples={"3307"}) == ["3307"]


def test_prompt_digits_extracts_runs():
    assert AB.prompt_digits("比如“尾号8600是吧…”“幺三零…后面是多少来着”；一次 1–2 句") == {"8600", "130"}
    assert AB.prompt_digits("一次 1–2 句、不超过 50 字") == set()


def test_scripts_add_digit_probes_at_end():
    sc = AB.scripts()
    play = [s for s in sc if not s["leak_check"]]
    assert len(play) == 7 and all(s["lines"][-1] == AB.DIGIT_PROBES[s["scenario"]] for s in play)
    assert all(AB.DIGIT_PROBES[s["scenario"]] not in s["lines"] for s in AB.scripts(digit_probes=False))
    # 报尾号那一句本身不能带数字，否则“对方先说过”会把泄露抵掉
    assert not any(AB.prompt_digits(x) for x in AB.DIGIT_PROBES.values())
    # 闲聊（抢话口径 0/18）不动
    assert [s["lines"] for s in sc if s["leak_check"]] == [AB.SMALL_TALK] * 3


def test_summary_digit_leak_fields():
    def row(call, turn, reply, dl):
        return {"reply": reply, "turn": turn, "call": call, "leak_check": False, "leaked": [], "guarded": False,
                "style": AB.style(reply), "ttft_ms": 1, "total_ms": 1, "in": 1, "out": 1, "digit_leaked": dl}
    rows = [row(0, 0, "哦…是我。", []), row(0, 5, "尾号8600是吧", ["8600"]), row(1, 5, "幺三零…", ["130"]),
            row(1, 6, "尾号8600", ["8600"]), row(2, 5, "我找找卡", [])]
    s = AB.summarize(rows, "qwen3.7-flash")
    assert s["digit_leak_replies"] == 3 and s["digit_leak_calls"] == 2 and s["digit_leak_hits"] == ["130", "8600"]


def _all_prompts():
    from voice import persona as P
    for pid in P.PERSONA_BY_ID:
        for sid in P.SCENARIO_BY_ID:
            for hint in P.INTENT_HINTS:
                for first in (True, False):
                    for topics in (None, set(), {"url", "bank", "phone", "invest", "wallet"}):
                        yield P.system_prompt(pid, sid, hint, ["卡号"], said_first="嗯…", topics=topics, first_turn=first)


def test_prompts_have_no_literal_number_examples():
    from voice import persona as P
    assert "8600" not in P.RULE_DIGITS and not AB.prompt_digits(P.RULE_DIGITS)
    assert "尾号" in P.RULE_DIGITS and "不要自己编号码" in P.RULE_DIGITS and "后四位" not in P.RULE_DIGITS  # #121：不再允许复述后四位
    for sp in _all_prompts():
        assert not AB.prompt_digits(sp), AB.prompt_digits(sp)
        assert P.RULE_DIGITS in sp


def test_voice_openings_and_fillers_have_no_number_strings():
    from voice import persona as P
    for lst in list(P.VOICE_OPENINGS.values()) + list(P.FILLERS.values()):
        assert not any(AB.prompt_digits(x) for x in lst)
