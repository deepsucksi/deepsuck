"""#215：语音真实链路上的号码 / 姓名星号（本地、离线，不调模型、不打电话）。

在 #214 审查用的 chain_check.py 基础上改成 pytest。每条用例走完整链路：
对方的话：TranscriptionFrame（整句 / 分段）→ IntelProcessor（Session.ingest 共享核心脱敏 → CallRedactor → frag_redact）
→ 用户聚合器（每段一条 user 消息）→ ContextGuard → 给模型的文本；heard_refs = IntelProcessor.heard_refs()。
人设复述：speakable（整句），以及逐字送进 ClauseTextAggregator → GuardTextFilter(本通的 CallRedactor())（TTS 流式）。

用例：voice/tests/fixtures/chain_p0_cases.json（p0-cases；「转到* / ** / ***」原期望 number 写错了，改成 name），
语料与人设提的转账动词用例（期望 name），「卡号是***，户名***」（期望 number + name），#203 姓名回归，姓名单字不露（「*明」「*华」）。

依赖别的 PR 的用例标 xfail(strict=False)，reason 写明依赖哪个 PR（合并顺序 #195 → #214 → 本 PR）：
- #214：共享核心的新判断（号码词 + 1–3 个星号是 number、「我在***上班」不当姓名、「卡号是***，户名***」分段判断）；
- #216：「我在*上班」（main 上就有的多遮，#214 后仍失败）。
分段送入（号码词 / 姓名锚和星号落在两段里）由本 PR 处理：unmask(prev=…) 按上一段念段首星号，heard_refs 按上一段算（#214 复审）。
用 `pytest --runxfail voice/tests/test_chain_p0.py` 可以看到这些用例在当前代码上的真实结果。
"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from pipecat.frames.frames import LLMContextFrame, TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.callredact import CallRedactor
from voice.processors import ContextGuard, GuardTextFilter, IntelProcessor
from voice.textagg import ClauseTextAggregator

F = json.loads((Path(__file__).parent / "fixtures" / "chain_p0_cases.json").read_text(encoding="utf-8"))
DIG = re.compile(r"[0-9０-９]{2,}")
NUM_SAY = ("那个号", "那几位")


def _tf(t):
    return TranscriptionFrame(text=t, user_id="u", timestamp="t")


async def _tts(text, redactor):
    """人设复述按 TTS 流式送：逐字喂 ClauseTextAggregator（min_clause_chars=6），每个分句过 GuardTextFilter。"""
    agg, flt, out = ClauseTextAggregator(min_clause_chars=6), GuardTextFilter(redactor), []
    for ch in text:
        async for a in agg.aggregate(ch):
            out.append(await flt.filter(a.text))
    r = await agg.flush()
    if r:
        out.append(await flt.filter(r.text))
    return "".join(out)


def chain(segs):
    s = Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    red = CallRedactor()
    p = IntelProcessor(s, context=ctx, filler_prob=0.0, redactor=red)
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf(t) for t in segs],
                                   expected_down_frames=[TranscriptionFrame] * len(segs)))
    for f in down:  # 用户聚合器：每段一条 user 消息
        ctx.add_message({"role": "user", "content": f.text})
    asyncio.run(run_test(ContextGuard(p), frames_to_send=[LLMContextFrame(context=ctx)],
                         expected_down_frames=[LLMContextFrame]))
    model = " ".join(m["content"] for m in ctx.get_messages() if m.get("role") == "user")
    sess = " ".join(m["text"] for m in s.messages if m.get("role") == "scammer")
    return dict(model=model, sess=sess, refs=set(p.heard_refs()),
                tts_model=asyncio.run(_tts(model, red)),   # 人设照着模型看到的话复述
                tts_sess=asyncio.run(_tts(sess, red)),     # 人设复述打码原文（星号版本）
                speak=P.speakable(sess, calm_tts=False))   # 整句复述


def problems(segs, expect, leak=(), keep=None):
    r = chain(segs)
    outs = [r["model"], r["tts_model"], r["tts_sess"], r["speak"]]
    said = [r["model"], r["speak"]]
    why = []
    if any("*" in o or "＊" in o for o in outs):
        why.append("星号残留")
    if any(DIG.search(o) for o in outs):
        why.append("数字露出")
    for w in leak:
        if any(w in o for o in outs):
            why.append(f"露出「{w}」")
    if expect == "number":
        if "number" not in r["refs"] or "name" in r["refs"]:
            why.append(f"refs={sorted(r['refs'])}≠number")
        if not all(any(k in o for k in NUM_SAY) and P.NAME_PHRASE not in o for o in said):
            why.append("念法不是那个号")
    elif expect == "name":
        if "name" not in r["refs"]:
            why.append(f"refs={sorted(r['refs'])} 无 name")
        if not all(P.NAME_PHRASE in o for o in said):
            why.append("念法不是那个名字")
    elif expect == "not_name":
        if "name" in r["refs"]:
            why.append("refs 含 name")
        if any(P.NAME_PHRASE in o for o in outs):
            why.append("念成了那个名字")
    elif expect == "both":
        if not {"number", "name"} <= r["refs"]:
            why.append(f"refs={sorted(r['refs'])} 不含 number+name")
        for o in said:
            head, _, tail = o.rpartition("户名")
            if not (P.NAME_PHRASE in tail and not any(k in tail for k in NUM_SAY)):
                why.append(f"户名没念成那个名字：{o}")
            if not (any(k in head for k in NUM_SAY) and P.NAME_PHRASE not in head):
                why.append(f"卡号没念成那个号：{o}")
        if len(segs) == 1 and r["model"] != "卡号是那个号，户名那个名字":
            why.append(f"给模型的不是「卡号是那个号，户名那个名字」：{r['model']}")
    elif expect == "keep":
        if any(o.replace("。", "") != keep for o in said):
            why.append("没有原样保留")
        if "name" in r["refs"]:
            why.append("refs 含 name")
    return why, r


# ---- 用例 ----------------------------------------------------------------------------------------------------------
# 依赖哪个 PR：在本分支、+#195（711d4c9）、+#214（b411fbe）、+#195+#214 上用 --runxfail 逐条实测后定的。
# 分段送入（号码词和星号落在两段）由本 PR 的 unmask(prev=…) / split_lead_refs 处理，不再依赖 #195。
DEP_214 = "#214（共享核心：号码词 + 1–3 个星号是 number、「我在***上班」不当姓名、「卡号是***，户名***」按逗号分段判断）"
DEP_216 = ("#216（「我在*上班」：单个星号后跟一个字按宁可多遮当姓名，念「我在那个名字班」；main 上就失败，"
           "试合 #214 b411fbe 后仍失败，#214 的 fixture 也标了 xfail）")
_NUMBER_WORDS = ("验证码是", "卡号是", "尾号是", "密码是", "账号是", "手机号是")


def _depends(group, segs, expect):
    if group.startswith("p0") and segs[0].startswith(_NUMBER_WORDS) and len(segs) == 1:
        return DEP_214
    if group.startswith("p0") and segs[0].startswith("我在"):
        return DEP_216 if segs == ["我在*上班"] else DEP_214
    if group.startswith("号码+户名") and segs[0].startswith("卡号是***"):
        return DEP_214
    return None


def _cases():
    out = []

    def add(group, segs, expect, leak=(), keep=None):
        cid = f"{group}:{' / '.join(segs)}"
        dep = _depends(group, segs, expect)
        marks = [pytest.mark.xfail(reason=f"依赖 {dep}", strict=False)] if dep else []
        out.append(pytest.param(segs, expect, tuple(leak), keep, id=cid, marks=marks))

    for c in F["cases"]:
        t = c["text"]
        add("p0 整句", [t], c["expect"])
        star = t.find("*")
        if star > 0:
            add("p0 分段", [t[:star], t[star:]], c["expect"])
        if c["expect"] == "number" and t.endswith("***") and t.count("*") == 3:  # 明文 3 位数字（ASR 原样）
            raw = t.replace("***", "123")
            add("p0 明文 整句", [raw], "number")
            add("p0 明文 分段", [raw[:-3], raw[-3:]], "number")
    for t in F["transfer_verbs"]["texts"]:
        add("转账动词", [t], "name")
        star = t.find("*")
        add("转账动词 分段", [t[:star], t[star:]], "name")
    for t in F["number_and_name"]["texts"]:
        add("号码+户名", [t], "both")
        add("号码+户名 分段", ["卡号是***，", "户名***"], "both")
        add("号码+户名 分段", ["卡号是", "***，户名***"], "both")  # #214 复审第 2 条：分段开头的星号按上一段「卡号是」算号码
        add("号码+户名 分段", ["卡号是", "***，户名", "***"], "both")
    # #214 语料复审：一句里两段 **，不能被当成 Markdown 粗体删掉星号
    add("两段星号", ["验证码是**，密码是**"], "number")
    add("两段星号", ["卡号是**，户名**"], "both")
    # 户名 / 收款人 / 名下 / 对方叫 紧跟星号（#215 人设侧）
    for t in ("户名***", "户名**", "户名*", "收款人***", "收款人**", "对方叫***", "他名下**", "户名：**", "户名为***"):
        add("姓名锚", [t], "name")
    # #203 姓名回归（明文）与正常词保留
    for t, leak in (("户名张三", ("张三", "三")), ("收款人叫李四", ("李四", "四")), ("收款人姓和", ()),
                    ("户名和平", ("和平", "平")), ("户名有志强", ("志强",))):
        add("#203 姓名", [t], "name", leak)
    for t in ("户名和账号", "收款人信息"):
        add("#203 保留", [t], "keep", keep=t)
    # 姓名单字不露（宁可多遮）
    for t, leak in (("户名*明", ("明",)), ("收款人**华", ("华",)), ("对方叫*明", ("明",)), ("户名**明，卡号是****", ("明",)),
                    ("转给*明", ("明",)), ("转到*明", ("明",)), ("卡号是*华", ("华",)), ("验证码是*明", ("明",)),
                    ("转给王*明", ("明",)), ("转到张**", ()), ("户名是**，卡号是****", ())):
        add("不露单字", [t], "leak", leak)
    return out


@pytest.mark.parametrize("segs,expect,leak,keep", _cases())
def test_chain(segs, expect, leak, keep):
    why, r = problems(segs, expect, leak, keep)
    assert not why, (why, r)


# ---- _unmask_names 单元（#215，不依赖共享核心改动）------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    ("户名***", "户名那个名字"), ("户名**", "户名那个名字"), ("户名*", "户名那个名字"), ("户名是***", "户名那个名字"),
    ("户名为**", "户名那个名字"), ("户名：**", "户名：那个名字"), ("户名 是 **", "户名那个名字"),
    ("收款人***", "收款人那个名字"), ("收款人是**", "收款人那个名字"), ("收款人：***", "收款人：那个名字"),
    ("对方叫***", "对方叫那个名字"), ("对方叫*", "对方叫那个名字"), ("名下***", "名下那个名字"), ("他名下**", "他名下那个名字"),
    ("户名***的卡", "户名那个名字的卡"), ("户名**和卡号", "户名那个名字和卡号"),
    ("户名*明", "户名那个名字"), ("收款人**华", "收款人那个名字"), ("对方叫*明", "对方叫那个名字"), ("户名**明，", "户名那个名字，"),
    ("转到**名下", "转到那个名字名下"),
    # 正常词不动
    ("户名和账号", "户名和账号"), ("收款人信息", "收款人信息"), ("我名下有两套房", "我名下有两套房"), ("对方叫我别挂", "对方叫我别挂"),
    # 星号后面紧跟数字是打码号码，不算姓名
    ("户名***1234", "户名***1234"),
])
def test_unmask_names_anchor(text, want):
    assert P._unmask_names(text) == want


def test_huming_after_card_number_says_name():
    """「卡号是***，户名***」户名那半念「那个名字」，不再是「户名那个号」（#215 人设侧，main 上就成立）。"""
    s = P.speakable("卡号是***，户名***", calm_tts=False)
    assert s.rpartition("户名")[2] == "那个名字" and "*" not in s


@pytest.mark.xfail(reason="依赖 #214（「卡号是***」的「是」不当姓，靠共享核心 stars_not_name）", strict=False)
def test_card_number_and_huming_full():
    assert P.unmask("卡号是***，户名***") == "卡号是那个号，户名那个名字"


# ---- #214 复审（b411fbe）并进来的三条 ----------------------------------------------------------------------------
@pytest.mark.parametrize("text,want", [
    # 第 3 条：星号前的动词 / 「人」不当姓吞掉
    ("转给***", "转给那个名字"), ("收款人***", "收款人那个名字"), ("转到*名下", "转到那个名字名下"), ("汇给**", "汇给那个名字"),
    ("转入**", "转入那个名字"), ("存到**", "存到那个名字"), ("打到**的卡上", "打到那个名字的卡上"), ("转给**的账户", "转给那个名字的账户"),
    ("转到**名下", "转到那个名字名下"),
    # 第 1 条整句部分：户名后的星号
    ("户名***", "户名那个名字"), ("户名：**", "户名：那个名字"), ("户名为**", "户名那个名字"),
    # 前字是真姓时照旧整个换掉，不露姓
    ("户名和*", "户名那个名字"), ("转给王*明", "转给那个名字"), ("转到张**", "转到那个名字"),
])
def test_keep_lead_char(text, want):
    assert P.speakable(text, calm_tts=False) == want


@pytest.mark.parametrize("text,prev,refs,want", [
    # 第 1 条：单独一段（或段首）的纯星号按上一段 / refs 念
    ("***", "转给", None, "那个名字"), ("**", "汇给", None, "那个名字"), ("***", "户名", None, "那个名字"),
    ("**", "户名是", None, "那个名字"), ("***", "收款人", None, "那个名字"), ("**的卡上", "打到", None, "那个名字的卡上"),
    ("***", "验证码是", None, "那个号"), ("***，户名***", "卡号是", None, "那个号，户名那个名字"),
    ("***", "", {"name"}, "那个名字"), ("***", "", {"name", "number"}, "那个号"), ("***", "", {"number"}, "那个号"),
    ("***", "", None, "那个号"),
])
def test_lead_stars_by_prev_segment(text, prev, refs, want):
    assert P.unmask(text, prev=prev, refs=refs) == want


@pytest.mark.parametrize("segs,want", [
    # 第 2 条：「卡号是」/「***，户名***」refs 要同时有 number 和 name
    (["卡号是", "***，户名***"], {"number", "name"}),
    (["转给", "***"], {"name"}),
    (["户名", "**"], {"name"}),
])
def test_heard_refs_split_segments(segs, want):
    _, r = problems(segs, "none")
    assert want <= r["refs"], (segs, r)


@pytest.mark.parametrize("text,want", [
    # #214 语料复审：两段 ** 先换代称再去 Markdown 粗体，念法与网页 / Python（#214 后）一致
    ("验证码是**，密码是**", "验证码是那个号，密码是那个号"),
    ("卡号是**，户名**", "卡号是那个号，户名那个名字"),
    ("卡号是**，尾号是**", "卡号是那个号，尾号是那几位"),
    ("账号是***，户名***", "账号是那个号，户名那个名字"),
])
def test_two_star_pairs_not_bold(text, want):
    assert P.speakable(text, calm_tts=False) == want
    assert P.guard_output(text) == want
    for step in (1, 3, len(text)):  # TTS 流式（ClauseTextAggregator + GuardTextFilter）
        agg_out = asyncio.run(_tts_step(text, step))
        assert agg_out.replace("，", "") == want.replace("，", ""), (step, agg_out)


def test_markdown_bold_still_stripped():
    assert P.guard_output("这个**很重要**，你记一下") == "这个很重要，你记一下"


async def _tts_step(text, step):
    agg, flt, out = ClauseTextAggregator(min_clause_chars=6), GuardTextFilter(CallRedactor()), []
    for i in range(0, len(text), step):
        async for a in agg.aggregate(text[i:i + step]):
            out.append(await flt.filter(a.text))
    r = await agg.flush()
    if r:
        out.append(await flt.filter(r.text))
    return "".join(out)
