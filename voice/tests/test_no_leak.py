"""人设不抢话（10-19 小林“杀猪盘”露馅）：对方只说交朋友、云南、线下见面时，
每个人设 × 每个场景实际选出的意图和生成的系统提示词都不能引导去问投资、平台、网址、渠道、转账。全部离线。"""
import asyncio
import re

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from deepsuck.personas import PERSONAS, SCENARIOS
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.processors import IntelProcessor

SMALL_TALK = [
    "你好呀，我是在网上看到你的，想跟你交个朋友。",
    "我在云南这边，平时挺忙的。",
    "云南这边天气特别好，四季如春。",
    "有空我们线下见面吧，一起吃个饭。",
    "你平时都喜欢干什么呀？",
    "我觉得我们挺有缘分的。",
    "我那边最近下雨，你那里呢？",
]
FORBIDDEN = re.compile(r"投资|平台|网址|渠道|转账|链接|账户|卡号|充值|收益|下载|钱包")
PRESUPPOSING = {"elicit_url", "elicit_account", "elicit_wallet", "elicit_contact", "fake_progress", "greedy",
                "task_stall", "loan_stall", "campus_stall", "coop_step", "confirm_intel", "otp_stall", "secrecy",
                "verify_identity", "scared", "urgency_stall"}
CASES = [(p["id"], s["id"]) for p in PERSONAS for s in SCENARIOS]


class RecCtx(LLMContext):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.prompts = []

    def set_messages(self, messages):
        if messages and messages[0].get("role") == "system":
            self.prompts.append(messages[0]["content"])
        return super().set_messages(messages)


def _dynamic(prompt: str) -> list:
    """提示词里随场景/意图/对话变化的部分：角色行、本轮策略行、例句。固定规则（含“不要先提平台、网址……”）不算。"""
    lines = prompt.split("\n")
    out = [x for x in lines if x.startswith("角色：") or x.startswith("本轮建议策略") or x.startswith("对方已经提到")]
    if any(x.startswith("说话口气参考") for x in lines):
        i = next(i for i, x in enumerate(lines) if x.startswith("说话口气参考"))
        out += [x for x in lines[i + 1:] if x.startswith("对方：") or x.startswith("你：")]
    return out


def _run_llm(pid, sid, seed):
    msgs = []

    async def notify(m):
        msgs.append(m)

    s = Session(scenario=sid, persona=pid, rng=mulberry32(seed), now=lambda: 0)
    ctx = RecCtx([{"role": "system", "content": "old"}])
    p = IntelProcessor(s, context=ctx, notify=notify)
    frames = [TranscriptionFrame(text=t, user_id="u", timestamp="t") for t in SMALL_TALK]
    asyncio.run(run_test(p, frames_to_send=frames, expected_down_frames=[TranscriptionFrame] * len(frames)))
    return [m["intent"] for m in msgs if m["type"] == "scammer"], ctx.prompts, s


@pytest.mark.parametrize("pid,sid", CASES)
def test_small_talk_never_steers_to_unmentioned_topics(pid, sid):
    scen = next(x for x in SCENARIOS if x["id"] == sid)
    for seed in (1, 7, 42):
        intents, prompts, _s = _run_llm(pid, sid, seed)
        assert len(intents) == len(SMALL_TALK) and len(prompts) == len(SMALL_TALK)
        bad = [i for i in intents if i in PRESUPPOSING]
        assert not bad, (pid, sid, seed, intents)
        for sp in prompts:
            assert scen["title"] not in sp and scen["desc"] not in sp  # 场景名和描述不进人设提示词
            assert P.NO_LEAK_RULE in sp
            assert "仍希望诱导" not in sp and "对方已经提到" not in sp  # 对方没提过的情报不进“想要”的清单
            for line in _dynamic(sp):
                assert not FORBIDDEN.search(line), (pid, sid, seed, line)


@pytest.mark.parametrize("pid,sid", CASES)
def test_rule_mode_small_talk_intents_neutral(pid, sid):
    s = Session(scenario=sid, persona=pid, rng=mulberry32(3), now=lambda: 0)
    s.intent_gate = lambda i: P.gate_intent(i, s)
    for t in SMALL_TALK:
        msg = s.rule_reply(s.ingest(t))
        assert msg["intent"] not in PRESUPPOSING, (pid, sid, msg)


def test_voice_opening_is_neutral():
    for p in PERSONAS:
        s = Session(scenario="pig", persona=p["id"], rng=mulberry32(1), now=lambda: 0)
        msg = P.voice_opening(s)
        assert msg["intent"] == "opening" and not FORBIDDEN.search(msg["text"])
        assert not re.search(r"订单|理赔|校园贷|客服|警", msg["text"])


def test_intent_hints_do_not_presuppose_platforms():
    # 门控之外的提示也不能自带“问对方平台/网址”
    for k in ("romance", "greedy", "misunderstand", "generic", "slow_walk", "ask_repeat", "tech_trouble", "opening"):
        assert not re.search(r"平台|网址|链接|渠道|投资|转账|账户", P.INTENT_HINTS[k]), k


def test_gate_allows_elicit_after_scammer_mentions_it():
    s = Session(scenario="pig", persona="lin", rng=mulberry32(1), now=lambda: 0)
    s.ingest("想跟你交个朋友")
    assert P.gate_intent("elicit_url", s) == "generic"
    assert P.gate_intent("elicit_account", s) == "generic"
    s.last_intent = "generic"
    assert P.gate_intent("elicit_url", s) == "slow_walk"
    s.last_intent = None
    s.ingest("我有个内部渠道的平台，你下载一下这个APP")
    assert P.gate_intent("elicit_url", s) == "elicit_url"
    assert P.gate_intent("elicit_account", s) == "generic"
    s.ingest("先充值一千，转到我给你的账户")
    assert P.gate_intent("elicit_account", s) == "elicit_account"
    assert P.gate_intent("elicit_contact", s) == "generic"
    s.ingest("加我微信详细聊")
    assert P.gate_intent("elicit_contact", s) == "elicit_contact"


def test_missing_goals_only_after_mention():
    s = Session(scenario="pig", persona="lin", rng=mulberry32(1), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "old"}])
    p = IntelProcessor(s, context=ctx)
    s.ingest("你好，交个朋友")
    sp = p.update_prompt()
    assert "对方已经提到" not in sp and p.prompt_sha and len(p.prompt_sha) == 8
    s.ingest("你下载这个APP看看")
    sp = p.update_prompt()
    assert "对方已经提到、但还没说清楚的：网址/下载链接" in sp and "钱包" not in sp.split("对方已经提到")[1].split("\n")[0]


def test_voice_shots_filtered_by_topic():
    wang = next(p for p in PERSONAS if p["id"] == "wang")
    shots = "\n".join(x for x in P.voice_style(wang, "refund", topics=set()) if x.startswith("对方："))
    assert "链接" not in shots and "微信" not in shots and "外套" in shots
    full = "\n".join(x for x in P.voice_style(wang, "refund", topics={"url", "phone", "bank"}) if x.startswith("对方："))
    assert "链接" in full or "微信" in full
