"""#169：历史窗口。超过 12 轮的长通话：整块丢最老 4 轮，固定保留对方第一段自我介绍；已拿到的情报、缺项、称呼、场景
都从 session 算，不受截断影响；人设在被丢掉的几轮里说过的事实（哪家银行、多少钱、借口）留在提示词里；
按通话打码名单（CallRedactor）和去重用的人设历史回复（session.messages）不受影响。用假的大模型离线跑，核对发出去的提示词。"""
import copy
import re

from pipecat.processors.aggregators.llm_context import LLMContext

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.persona import gate_intent, guard_output, heard_scenes, unmask
from voice.processors import HISTORY_DROP, HISTORY_TRIM_AT, IntelProcessor, persona_facts, window_history

CARD = "6222021234567890128"
INTRO = "您好，我是淘宝客服，您买的衣服有质量问题，要给您退款。"
SCRIPT = [
    INTRO,
    "您是哪家银行的卡？退款要退到卡里。",
    "退款金额是三百元，要先交两百块的保证金。",
    f"收款卡号是{CARD}，户名张三丰，弓长张，三丰。",
    "您记下了吗？快点操作。",
    "您打开支付宝，找到转账。",
    "点那个转账，输入刚才的卡号。",
    "金额填两百。",
    "好了没有？我们这边要结单了。",
    "您别挂电话，我等您。",
    "您到底弄好没有？",
    "操作很简单的，您再看看。",
    "您现在在哪儿？",
    "您先别跟家里人说。",
    "我是为您好，过了今天就退不了了。",
    "您再确认一下那个卡号。",
]
# 假的大模型：前几轮说出关键事实（哪家银行、多少钱、借口），后面拖延
REPLIES = [
    "哦…是我。你说。",
    "我那张是农行的卡…退休金在里面。",
    "两百块啊…我得想想。",
    "那个号…我记一下。",
    "我在外面呢…没带老花镜。",
] + ["嗯…你说的那个…我找找。"] * 20


def _run(n):
    s = Session(scenario="refund", persona="wang", rng=mulberry32(3), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx)
    ctx.add_message({"role": "assistant", "content": P.voice_opening(s)["text"]})
    sent = []  # 每轮“发给大模型”的完整消息列表
    for i, text in enumerate(SCRIPT[:n]):
        a = p.call_redact(s.ingest(text))
        p.intent = gate_intent(s.fresh_intent(s.choose_intent(a)), s)
        s.last_intent = p.intent
        before = (copy.deepcopy(s.messages), list(s._recent), list(s._recent_picks), len(p.redactor))
        p.update_prompt()
        after = (s.messages, list(s._recent), list(s._recent_picks), len(p.redactor))
        assert before == after  # update_prompt（含截断）不改 session 和按通话打码名单
        ctx.add_message({"role": "user", "content": unmask(a["redacted"])})
        sent.append(copy.deepcopy(ctx.get_messages()))
        reply = REPLIES[i]
        ctx.add_message({"role": "assistant", "content": reply})
        s.record_bot(guard_output(p.redactor.apply(reply)), p.intent)
    return s, p, ctx, sent


def _users(msgs):
    return [m["content"] for m in msgs if m["role"] == "user"]


def test_window_history_drops_whole_blocks_and_keeps_first_round():
    rest = [{"role": "assistant", "content": "喂？"}]
    for k in range(14):
        rest += [{"role": "user", "content": f"u{k}"}, {"role": "assistant", "content": f"a{k}"}]
    kept, dropped = window_history(rest)
    users = _users(kept)
    assert users[0] == "u0" and kept[0]["content"] == "喂？" and kept[2]["content"] == "a0"  # 开场 + 第一轮固定
    assert len(users) == 14 - HISTORY_DROP and users[1] == f"u{1 + HISTORY_DROP}"
    assert _users(dropped) == [f"u{k}" for k in range(1, 1 + HISTORY_DROP)]
    k2, d2 = window_history(kept)  # 截完再算一次不再丢（两次截断之间前缀稳定）
    assert k2 == kept and d2 == []
    short = rest[:1 + 2 * HISTORY_TRIM_AT]
    assert window_history(short) == (short, [])


def test_long_call_prompt_after_trim():
    s, p, ctx, sent = _run(len(SCRIPT))
    assert len(SCRIPT) > HISTORY_TRIM_AT
    last = sent[-1]
    fixed, turn = last[0]["content"], last[-2]["content"]
    assert last[0]["role"] == last[-2]["role"] == "system" and last[-1]["role"] == "user"
    assert sum(m["role"] == "system" for m in last) == 2  # 上一轮的可变部分已换掉，不会越积越多
    users = _users(last)
    # (c) 对方第一段自我介绍固定保留；中间几轮整块丢掉
    assert users[0] == INTRO and len(users) < len(SCRIPT) and p.dropped_rounds > 0
    assert all(_users(m)[0] == INTRO for m in sent)
    # session.messages 不截：情报、话题、场景、去重用的人设历史回复都还在
    assert sum(m["role"] == "scammer" for m in s.messages) == len(SCRIPT)
    assert sum(m["role"] == "bot" for m in s.messages) == len(SCRIPT) + 1
    # (a) 已拿到的卡号、户名汇总在可变部分；第 12 轮之后不再当缺项追问
    for msgs in sent[HISTORY_TRIM_AT:]:
        t = msgs[-2]["content"]
        assert "对方已经报过、你这边已经记下的：" in t and "收款银行卡号" in t.split("记下的：")[1].split("。")[0]
        assert "收款人姓名" in t.split("记下的：")[1].split("。")[0]
        miss = t.split("还没说清楚的：")[1].split("，")[0] if "还没说清楚的：" in t else ""
        assert "收款银行卡号" not in miss and "收款人姓名" not in miss
    # 称呼和场景还在（和截断前同一行）
    role = next(x for x in fixed.split("\n") if x.startswith("角色："))
    assert role == next(x for x in sent[4][0]["content"].split("\n") if x.startswith("角色："))
    assert "refund" in heard_scenes(s)
    # (b) 人设在被丢掉的几轮里说过的事实还在提示词里
    assert "你前面自己说过" in turn and "农行" in turn and "两百块" in turn
    # (d) 按通话打码：卡号、户名在任何一条消息里都不出现原值；提示词里没有长数字串
    blob = "\n".join(str(m["content"]) for m in last)
    assert CARD not in blob and "三丰" not in blob and "弓长" not in blob
    assert not re.search(r"[0-9]{3,}", fixed + turn)
    assert len(p.redactor) >= 2


def test_fixed_prefix_stable_between_turns():
    _, _, _, sent = _run(len(SCRIPT))
    # 场景认出来以后（称呼定了），固定部分每轮相同；历史只在截断那一轮变
    fixed = [m[0]["content"] for m in sent[2:]]
    assert len(set(fixed)) == 1
    for prev, cur in zip(sent[2:], sent[3:]):
        hp, hc = prev[1:-2], cur[1:-2]
        if hc[:len(hp)] != hp:  # 只有整块丢的那一轮前缀会变
            assert len(_users(hc)) < len(_users(hp)) + 1


def test_persona_facts_redacted_and_digit_free():
    from voice.callredact import CallRedactor
    s = Session(scenario="refund", persona="wang", rng=mulberry32(1), now=lambda: 0)
    s.ingest("户名张三丰。")
    r = CallRedactor()
    r.learn(s)
    out = persona_facts("我那张是农行的卡。张三丰是谁啊。尾号8600的那张在家里。", r)
    assert any("农行" in x for x in out)
    assert not any("三丰" in x or re.search(r"[0-9]{2,}", x) for x in out)
    assert persona_facts("嗯…你说。") == []
