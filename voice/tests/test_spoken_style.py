"""#64：口语风格——句子约一半带「…」、每通第一句不抢着反问。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "python"):
    sys.path.insert(0, str(p))

from voice import llm_ab as AB  # noqa: E402
from voice import persona as P  # noqa: E402
from voice.tests.test_no_leak import FORBIDDEN  # noqa: E402


def test_style_rule_half_ellipsis_not_always_questions():
    assert "大约一半的句子带“…”" in P.STYLE_RULE and "不要每句都带" in P.STYLE_RULE
    assert "多反问" not in P.STYLE_RULE and "不是每句都问" in P.STYLE_RULE


def test_first_turn_rule_only_on_first_turn_and_last():
    on = P.system_prompt("wang", "refund", "generic", topics=set(), first_turn=True)
    off = P.system_prompt("wang", "refund", "generic", topics=set())
    assert on.rstrip().endswith(P.FIRST_TURN_RULE) and P.FIRST_TURN_RULE not in off
    assert not FORBIDDEN.search(P.FIRST_TURN_RULE)  # 规则本身不能把对方没提的话题带进来


def test_first_turn_shots_never_open_with_question():
    p = P.PERSONA_BY_ID["wang"]
    for sid in ("refund", "police", "pig", "task", "loan", "campus", "boss"):
        lines = P.voice_style(p, sid, topics={"url", "bank", "phone", "invest", "wallet"}, first_turn=True)
        shots = [x for x in lines if x.startswith("对方：")]
        assert all(not P.first_sentence_is_question(x.split("\n你：", 1)[1]) for x in shots), sid


def test_first_sentence_is_question():
    assert P.first_sentence_is_question("退…退款？哪个")
    assert P.first_sentence_is_question("嗯…信贷啊？哪个机构的")
    assert not P.first_sentence_is_question("哦…卡的事啊。哪张卡？")
    assert not P.first_sentence_is_question("")


def test_update_prompt_marks_first_turn():
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32
    from voice.processors import IntelProcessor

    s = Session(scenario="refund", persona="wang", rng=mulberry32(11), now=lambda: 0)
    ip = IntelProcessor(s)
    P.voice_opening(s)
    s.ingest("您好，我是售后客服，您买的衣服有质量问题。")
    assert P.FIRST_TURN_RULE in ip.update_prompt()
    s.ingest("要给您两千块赔付。")
    assert P.FIRST_TURN_RULE not in ip.update_prompt()


def test_ab_sentence_metrics():
    assert AB.sentences("衣服？…哪件啊？你再说一遍…") == ["衣服？", "…哪件啊？", "你再说一遍…"]
    assert AB.first_question("衣服？哪件") and not AB.first_question("哦…是我。哪件？")
    rows = [{"reply": r, "turn": t, "leak_check": False, "leaked": [], "guarded": False, "style": AB.style(r),
             "ttft_ms": 1, "total_ms": 1, "in": 1, "out": 1}
            for t, r in [(0, "哦…是我。哪件？"), (1, "两千。那你说"), (0, "卡？哪张")]]
    s = AB.summarize(rows, "qwen3.7-flash")
    assert s["sentences"] == 6 and s["sent_ellipsis_pct"] == 16.7 and s["first_question"] == 1 and s["calls"] == 2
