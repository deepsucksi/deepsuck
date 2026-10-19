"""大模型骗子重测（eval/llm_scammer.py）暴露的露馅句修补回归：反套话 / 消遣式台词不回来，高频拖延意图句池够大。"""
import re

from deepsuck.engine import Session
from deepsuck.personas import PERSONAS

# 基线里被大模型骗子当成“反套话 / 在消遣我”而挂断的回复（docs/EVAL.md「大模型扮演骗子」）
REMOVED = [
    "有意思，展开讲讲",
    "这是社团招新吗",
    "学校通知的那个反诈 APP",
    "请勿泄露给任何人，包括客服",
    "有没有监管牌照",
    "能把你的警号和单位全称发我吗",
    "你是我孙子的同事吗",
    "他以前是派出所的",
    "我好跟我闺女解释",
]
INTENTS = ("generic", "otp_stall", "tech_trouble", "slow_walk", "ask_repeat", "info_stall", "urgency_stall")


def _texts(lst):
    return [it if isinstance(it, str) else it["t"] for it in lst]


def test_leaky_lines_removed():
    for p in PERSONAS:
        for k, lst in p["templates"].items():
            for t in _texts(lst):
                for bad in REMOVED:
                    assert bad not in t, (p["id"], k, t)


def test_frequent_stall_pools_large_enough():
    for p in PERSONAS:
        for k in INTENTS:
            t = [x for x in p["templates"][k] if isinstance(x, str)]
            assert len(set(t)) >= 5, (p["id"], k, len(t))
            for x in t:
                assert not re.search(r"\d{6,}", x) and "诈骗" not in x and "反诈" not in x, x


def test_scenario_specific_lines_are_conditional():
    """只在对应话题下才说的误解 / 要链接句带 when：不会在没发链接时说“链接打不开”，也不会把校园贷当兼职。"""
    lin = next(p for p in PERSONAS if p["id"] == "lin")
    s = Session("campus", "lin", rng=lambda: 0.0, now=lambda: 0)
    for _ in range(12):
        t = s.pick("misunderstand", "这个账户不注销会影响征信，今天必须处理")
        assert "兼职" not in t
    s = Session("boss", "lin", rng=lambda: 0.0, now=lambda: 0)
    for _ in range(12):
        assert "链接打不开" not in s.pick("elicit_url", "先帮我转一笔钱给合作方")
    cond = [it for it in lin["templates"]["elicit_url"] if not isinstance(it, str)]
    assert any("链接打不开" in it["t"] for it in cond)


def test_offtopic_misunderstandings_only_on_topic():
    """寄东西、发鸡蛋、进货这类误解只在相关话题下出现（第二轮重测里被当成答非所问）。
    原李大爷的“订牛奶 / 居委会”句随人设归档（personas/archive/li.json）。"""
    for pid, bad in (("wang", "菜鸟驿站"), ("wang", "发鸡蛋"), ("zheng", "订的那批货"), ("zheng", "商户发的"), ("chen", "接龙团购")):
        s = Session("police", pid, rng=lambda: 0.0, now=lambda: 0)
        for _ in range(15):
            assert bad not in s.pick("misunderstand", "你涉嫌洗钱，马上把钱转到安全账户配合调查")
    assert "进货押金" in Session("refund", "zheng", rng=lambda: 0.0, now=lambda: 0).pick("misunderstand", "您的会员要自动续费了")
