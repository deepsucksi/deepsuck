"""#95：每通第一句不再套「哦…X的事啊。」——规则不给固定格式，第一句说法示例每通挑几条不同句式，llm_ab 统计模板重复率。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "python"):
    sys.path.insert(0, str(p))

from voice import llm_ab as AB  # noqa: E402
from voice import persona as P  # noqa: E402
from voice.tests.test_no_leak import FORBIDDEN  # noqa: E402

PIDS = ("wang", "chen", "lin", "zheng")


def test_rule_bans_fixed_pattern_without_positive_template():
    r = P.FIRST_TURN_HEAD + P.FIRST_TURN_RULE
    assert "固定句式" in r and "每通第一句换着说" in r and "不加问号" in r and "句号断开" in r
    # 原来的格式示例不再写死在规则里（模型会照搬）
    for old in ("衣服的事啊", "卡的事啊", "交朋友啊"):
        assert old not in r
    assert not FORBIDDEN.search(r)


def test_openers_are_varied_statements_without_topics():
    pool = P.FIRST_TURN_OPENERS + P.FIRST_TURN_ECHOES + [x for v in P.FIRST_TURN_OPENERS_BY_PERSONA.values() for x in v]
    assert len(set(pool)) == len(pool) >= 20
    for x in pool:
        assert not AB.opening_template(x), x          # 不是「哦…X的事啊」那一套
        assert not P.first_sentence_is_question(x) and "！" not in x and x.endswith("。"), x
        assert not FORBIDDEN.search(x), x
        assert "的事" not in x, x
    assert len({AB.opening_skeleton(x) for x in pool}) == len(pool)  # 句式各不相同
    assert set(P.FIRST_TURN_OPENERS_BY_PERSONA) == set(PIDS)


def test_openers_pick_depends_on_first_line():
    a = P.first_turn_openers("wang", "您好，我是售后客服。")
    assert a == P.first_turn_openers("wang", "您好，我是售后客服。")  # 可复现
    assert len(a) == len(set(a)) == P._OPENERS_SHOWN
    assert sum(x in P.FIRST_TURN_OPENERS_BY_PERSONA["wang"] for x in a) <= 1
    own = [sum(x in P.FIRST_TURN_OPENERS_BY_PERSONA["wang"] for x in P.first_turn_openers("wang", f"{i}|喂")) for i in range(40)]
    assert 0 in own and 1 in own  # 本人设的说法有的通放、有的通不放
    assert sum(x in P.FIRST_TURN_ECHOES for x in a) == 2
    picks = {tuple(P.first_turn_openers("chen", f"第{i}句")) for i in range(20)}
    assert len(picks) >= 10


def test_first_turn_prompt_has_openers_only_on_first_turn():
    on = P.system_prompt("zheng", "loan", "generic", topics=set(), first_turn=True, opener_key="老板你好")
    off = P.system_prompt("zheng", "loan", "generic", topics=set(), opener_key="老板你好")
    shown = P.first_turn_openers("zheng", "老板你好")
    assert all(f"- {x}" in on for x in shown) and not any(f"- {x}" in off for x in shown)  # few-shot 里的第一句说法
    last = on.rstrip().split("\n")[-1]
    assert last == P.first_turn_rule(shown) and last.endswith(P.FIRST_TURN_RULE)
    # #169：第一句说法只在“第一句的说法”里列一次，第一轮规则里不再重复
    assert not any(f"“{x}”" in last for x in shown) and all(on.count(x) == 1 for x in shown)
    assert P.FIRST_TURN_RULE not in off


def test_update_prompt_uses_first_scammer_line():
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32
    from voice.processors import IntelProcessor

    s = Session(scenario="refund", persona="chen", rng=mulberry32(11), now=lambda: 0)
    ip = IntelProcessor(s)
    P.voice_opening(s)
    s.ingest("您好，我是网店客服，您给孩子买的童装有问题。")
    sp = ip.update_prompt()
    first = next(m["text"] for m in s.messages if m["role"] == "scammer")
    assert all(f"- {x}" in sp for x in P.first_turn_openers("chen", f"{ip.opener_salt}|{first}"))


def test_ab_opening_template_metric():
    yes = ["哦…衣服的事啊。你说吧", "嗯，卡的事啊。", "哦…退款的事啊…哪件", "嗯…银行卡的事呀。", "哦，贷款的事情啊。"]
    echo = ["哦…交朋友啊。", "嗯，电商老板啊。\n哪个", "嗯，衣服啊…哪件呀"]
    no = ["嗯，你说。", "喂，在听呢。", "衣服？哪件", "嗯，点赞啊？几块", "等下啊…宝宝在旁边，你说。", "啊，这样…你往下说。"]
    assert all(AB.opening_template(x) and AB.opening_template(x, strict=True) for x in yes)
    assert all(AB.opening_template(x) and not AB.opening_template(x, strict=True) for x in echo)
    assert not any(AB.opening_template(x) or AB.opening_template(x, strict=True) for x in no)
    assert AB.opening_skeleton("哦…衣服的事啊。你说吧") == AB.opening_skeleton("嗯，交朋友啊。") == "哦X啊"
    assert AB.opening_skeleton("嗯，你说。") == "哦你说" and AB.opening_skeleton("喂，在听呢。") == "喂在听呢"
    # 复述对方的词记成 X
    assert AB.opening_skeleton("嗯，衣服…我想想。", "您买的衣服有问题") == AB.opening_skeleton("哦，退款…我想想。", "给您退款") == "哦X我想想"
    rows = [{"reply": r, "turn": 0, "call": i, "scammer": "", "leak_check": False, "leaked": [], "guarded": False, "style": AB.style(r),
             "ttft_ms": 1, "total_ms": 1, "in": 1, "out": 1}
            for i, r in enumerate(["哦…衣服的事啊。", "嗯，卡的事啊。哪张", "嗯，你说。", "喂，在听呢。"])]
    s = AB.summarize(rows, "qwen3.7-flash")
    assert (s["first_template"], s["first_template_strict"], s["first_template_pct"], s["calls"]) == (2, 2, 50.0, 4)
    assert s["first_skeleton_top"] == 2 and s["first_skeleton_top_text"] == "哦X啊" and s["first_skeletons"] == 3


def test_opening_examples_carry_no_scene_or_topic():
    """#4：第一句示例和补充示范不带场景词、话题词，免得把对方还没说的事带进提示词。"""
    from voice.persona import scenes_in, topics_in
    pool = (P.FIRST_TURN_ECHOES + P.FIRST_TURN_OPENERS + sum(P.FIRST_TURN_OPENERS_BY_PERSONA.values(), [])
            + [a + b for a, b in P.FIRST_TURN_DEMOS] + list(P._SHOT_TAILS))
    assert [x for x in pool if scenes_in(x) or topics_in(x)] == []


def test_opener_salt_varies_per_call():
    """对方第一句话一样（“喂，你好…”）时，不同的通话也挑出不同的示例。"""
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32
    from voice.processors import IntelProcessor
    salts = {IntelProcessor(Session(scenario="refund", persona="wang", rng=mulberry32(1), now=lambda: 0)).opener_salt
             for _ in range(5)}
    assert len(salts) == 5
