"""#4 人设抢先提及骗子没提的场景：系统提示词里不能有后台选的场景（场景名、描述、按场景挑的称呼和例句），
只能有对方已经说出的场景。全部离线；台词文字不改，只改怎么挑、怎么拼进提示词。"""
import asyncio
import json
from pathlib import Path

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from deepsuck.personas import PERSONAS, SCENARIOS
from deepsuck.rng import mulberry32
from voice import llm_ab as AB
from voice import persona as P
from voice.processors import IntelProcessor
from voice.tests.test_no_leak import RecCtx

ROOT = Path(__file__).resolve().parents[2]
# 不带任何场景、话题的开场（对方还没说来干什么）
NEUTRAL = ["喂，你好，听得到吗？", "是本人吧？我这边找你有点事。", "你现在方便说话吗？"]
CASES = [(p["id"], s["id"]) for p in PERSONAS for s in SCENARIOS]
# 一听就知道场景的称呼（小伙子、小姑娘这种不算）
TELLING_CALLS = ("警察同志", "领导", "经理", "警官", "老总")


def _run(pid, sid, lines, seed=1):
    s = Session(scenario=sid, persona=pid, rng=mulberry32(seed), now=lambda: 0)
    ctx = RecCtx([{"role": "system", "content": "old"}])
    p = IntelProcessor(s, context=ctx)
    frames = [TranscriptionFrame(text=t, user_id="u", timestamp="t") for t in lines]
    asyncio.run(run_test(p, frames_to_send=frames, expected_down_frames=[TranscriptionFrame] * len(frames)))
    return ctx.prompts, s


@pytest.mark.parametrize("pid,sid", CASES)
def test_neutral_opening_prompt_has_no_scene(pid, sid):
    scen = next(x for x in SCENARIOS if x["id"] == sid)
    prompts, s = _run(pid, sid, NEUTRAL)
    assert P.heard_scenes(s) == [] and len(prompts) == len(NEUTRAL)
    for sp in prompts:
        assert scen["title"] not in sp and scen["desc"] not in sp
        assert not P.scenes_in(sp), (pid, sid, P.scenes_in(sp))  # 任何场景的词都不进提示词
        assert not any(c in sp for c in TELLING_CALLS), (pid, sid)
        assert "先不用称呼对方" in sp and "说话口气参考" not in sp  # 没认出场景就不放例句


@pytest.mark.parametrize("pid,sid", CASES)
def test_prompt_only_carries_heard_scenes(pid, sid):
    """对方按剧本一句句说，每一轮提示词里出现的场景都必须是对方已经说出的。"""
    pb = json.loads((ROOT / "voice/static/scam_playbooks.json").read_text(encoding="utf-8"))["scenarios"][sid]
    lines = [AB.re.sub(r"\{([^}]+)\}", lambda m: AB.FILL.get(m.group(1), "那个"), st["lines"][0]) for st in pb["steps"]]
    prompts, _s = _run(pid, sid, lines)
    for i, sp in enumerate(prompts):
        heard = set().union(*(P.scenes_in(x) for x in lines[:i + 1]))
        heard |= {y for x in heard for y in P.SCENE_IMPLIES.get(x, [])}
        assert P.scenes_in(sp) <= heard, (pid, sid, i, P.scenes_in(sp) - heard)


def test_app_opening_prompt_is_scene_free():
    for p in PERSONAS:
        for s in SCENARIOS:
            sp = P.system_prompt(p["id"], s["id"], "opening", topics=set(), scenes=[])
            assert not P.scenes_in(sp) and s["title"] not in sp, (p["id"], s["id"])


def test_call_follows_heard_scene_not_backend_scenario():
    p = P.PERSONA_BY_ID["wang"]
    assert "警察同志" not in P.system_prompt("wang", "police", "generic", topics=set(), scenes=[])
    sp = P.system_prompt("wang", "refund", "generic", topics=set(), scenes=["police"])
    assert f"称呼对方为\"{p['call']['police']}\"" in sp


def test_shots_only_from_heard_scenes_and_texts_unchanged():
    p = P.PERSONA_BY_ID["chen"]
    allowed = {(x["scammer"], x["reply"]) for x in p["voiceShots"]}
    lines = P.voice_style(p, ["task"], topics={"bank", "url", "phone"})
    shots = [x for x in lines if x.startswith("对方：")]
    assert shots
    for x in shots:
        scammer, reply = x[len("对方："):].split("\n你：", 1)
        assert (scammer, reply) in allowed  # 原样引用已批准的台词
        assert P.scenes_in(scammer + reply) <= {"task"}
    assert not [x for x in P.voice_style(p, [], topics=set()) if x.startswith("对方：")]


def test_style_example_dropped_only_when_scene_unheard():
    p = P.PERSONA_BY_ID["wang"]
    off = "\n".join(P.voice_style(p, [], topics=set()))
    on = "\n".join(P.voice_style(p, ["refund"], topics=set()))
    assert "退…退款" not in off and "退…退款" in on
    assert "语序可以断断续续" in off and "大约一半的句子带这种断续" in off  # 规则本身还在


def test_heard_scenes_order():
    s = Session(scenario="loan", persona="wang", rng=mulberry32(1), now=lambda: 0)
    s.ingest("你好，听得到吗")
    assert P.heard_scenes(s) == []
    s.ingest("我是市公安局的民警，你的卡涉嫌洗钱")
    s.ingest("你有一笔贷款额度")
    assert P.heard_scenes(s) == ["police", "loan"]


def test_llm_ab_scene_leak_metric():
    assert AB.scene_leaks("你是哪个派出所的？", "你好，交个朋友吧") == ["police"]
    assert AB.scene_leaks("派出所？哪个派出所", "我是派出所的民警") == []
    assert {sc["persona"] for sc in AB.scripts()} <= {p["id"] for p in PERSONAS}
    base = {"guarded": False, "ttft_ms": 400.0, "total_ms": 900.0, "turn": 1}
    rows = [dict(base, reply="x", scene_leaked=["police"], call=1, style=AB.style("x")),
            dict(base, reply="y", scene_leaked=[], call=2, style=AB.style("y"))]
    s = AB.summarize(rows, "qwen3.8-flash")
    assert s["scene_leak_replies"] == 1 and s["scene_leak_calls"] == 1 and s["scene_leak_hits"] == ["police"]


def test_tech_trouble_not_on_first_turn():
    s = Session(scenario="pig", persona="chen", rng=mulberry32(1), now=lambda: 0)
    s.ingest("你好呀，我是在网上看到你的，想跟你交个朋友。")
    assert P.gate_intent("tech_trouble", s) == "generic"
    s.ingest("我在云南这边")
    assert P.gate_intent("tech_trouble", s) == "tech_trouble"
