import re
"""#140：按通话打码。同一通电话里已提取的姓名、号码再次出现（全名、去姓的名、拆字说法、号码换写法）时，
进模型、送 TTS、记会话前都要打码。回归用例来自现网探针 KZIZA65L（a97f7f7 上线后，假名）。"""
import asyncio

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import run_test

from deepsuck.engine import Session
from voice.callredact import CallRedactor, name_patterns
from voice.persona import speakable, unmask
from voice.processors import GuardTextFilter, IntelProcessor

SEG1 = "收款户名张三丰，弓长张，三丰。"        # 第一段 ASR 进 session 前的原文
SEG1_LIVE = "收款户名张**。弓长张三丰。"        # 现网 ingest 后的文本（逐句规则只打了第一次出现的全名）
REPLY = "张三丰？… 这名字挺大啊。哪个银行户头？"  # 人设当时的回复
SEG2 = "户名张三丰你记下了吗？"                  # 第二段


def _tf(text):
    return TranscriptionFrame(text=text, user_id="u", timestamp="t")


def _session():
    from deepsuck.rng import mulberry32
    return Session(scenario="refund", persona="wang", rng=mulberry32(7), now=lambda: 0)


def _clean(s):
    assert "张三丰" not in s and "三丰" not in s and "弓长" not in s, s
    assert "*" not in s and "＊" not in s, s


def _run(p, *texts):
    """几段依次过 IntelProcessor（同一通电话），返回交给模型的文本。"""
    down, _ = asyncio.run(run_test(p, frames_to_send=[_tf(t) for t in texts],
                                   expected_down_frames=[TranscriptionFrame] * len(texts)))
    return [f.text for f in down]


def test_kziza65l_model_input_and_speech_have_no_name():
    msgs = []

    async def notify(m):
        msgs.append(m)

    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx, notify=notify, filler_prob=0.0)
    to_model = _run(p, SEG1, SEG2)
    for t in to_model:
        _clean(t)
        assert "那个名字" in t, t
    assert to_model[1] == "户名那个名字你记下了吗？"
    # 与共享核心的拆字规则（#142：“弓长张，三丰”→“弓长张，**”）叠加：不双重打码、不出现“那个号”这类怪句
    assert to_model[0] == "收款户名那个名字，那个名字。", to_model[0]
    assert "那个号" not in to_model[0]
    # 会话记录（系统提示词里的 heard、看板、通话记录都从这里取）和推给面板的文字也不含原名
    for m in s.messages:
        if m.get("role") == "scammer":
            assert "三丰" not in m["text"] and "弓长" not in m["text"], m
    assert all("三丰" not in str(m) for m in msgs)
    for m in ctx.get_messages():
        assert "三丰" not in str(m.get("content")), m
    # 现网 ingest 后的那句（逐句规则漏了拆字 + 名）按通话集合补打码
    live = unmask(p.redactor.apply(SEG1_LIVE))
    _clean(live)
    assert live == "收款户名那个名字。那个名字。"
    # 送 TTS：人设复述了全名，同一通电话的 GuardTextFilter 先打码再 speakable
    f = GuardTextFilter(p.redactor)
    for t in (REPLY, "弓长张，三丰是吧？", "三丰我记下了", SEG2):
        spoken = asyncio.run(f.filter(t))
        _clean(spoken)
        assert "那个名字" in spoken, spoken
    assert re.match("那个名字[？…]", speakable(p.redactor.apply(REPLY), calm_tts=True))  # #132：第一句快速反问的问号换成“…”


def test_name_said_before_extracted_is_redacted_in_context_too():
    """先说了“三丰”（还没提取到户名），下一段报出户名后，模型上下文里前一段也补打码。"""
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx, filler_prob=0.0)
    first = unmask(s.ingest("我们这边经理叫三丰，你等一下")["redacted"])
    assert "三丰" in first  # 还没提取到，逐句规则不打
    ctx.add_message({"role": "user", "content": first})  # 上一回合已经进了模型上下文
    _run(p, SEG1)
    assert not any("三丰" in m["text"] for m in s.messages if m.get("role") == "scammer")
    assert all("三丰" not in str(m.get("content")) for m in ctx.get_messages())


def test_no_false_hit_in_call_without_that_name():
    """没提取过“三丰”的通话里，正常词不受影响。"""
    s = _session()
    ctx = LLMContext([{"role": "system", "content": "x"}])
    p = IntelProcessor(s, context=ctx, filler_prob=0.0)
    out = _run(p, "我们在三丰路营业厅，弓长岭那边也有网点。")
    assert out[0] == "我们在三丰路营业厅，弓长岭那边也有网点。"
    assert len(p.redactor) == 0
    f = GuardTextFilter(p.redactor)
    assert "三丰路" in asyncio.run(f.filter("三丰路营业厅是吧"))
    # 提取到的是别人（李强）时，“三丰”照旧
    r = CallRedactor()
    r.add("name", "李强")
    assert r.apply("三丰路的李强，木子李强") == "三丰路的李*，李*"
    assert r.apply("强调一下") == "强调一下"  # 单字名不按“去姓的名”匹配


def test_numbers_in_other_spellings():
    r = CallRedactor()
    r.add("phone", "13812345678")
    r.add("bank_card", "6222 0212 3456 7893 445")
    t = "打 138-1234-5678 或者 138 1234 5678，卡号6222021234567893445"
    out = unmask(r.apply(t))
    assert out == "打 那个号 或者 那个号，卡号那个号", out
    assert r.apply("金额13812345678900") == "金额13812345678900"  # 前后紧挨数字的不算
    assert r.apply("转 5000 元") == "转 5000 元"


def test_name_patterns_variants():
    pats = name_patterns("张三丰")
    import re
    for t in ("弓长张三丰", "弓长张，三丰", "弓长的张", "张三丰", "三丰"):
        assert any(re.fullmatch(p, t) for p in pats), t
    r = CallRedactor()
    r.add("name", "欧阳娜娜")  # 复姓：去姓的名是“娜娜”
    assert unmask(r.apply("户名欧阳娜娜，娜娜")) == "户名那个名字，那个名字"
    r2 = CallRedactor()
    r2.add("name", "陈立")  # 名只有 1 个字：只认全名和拆字
    assert unmask(r2.apply("耳东陈，立刻转")) == "那个名字，立刻转"
    assert unmask(r2.apply("户名耳东陈立")) == "户名那个名字"
    # 核心已打码的拆字后的名（#142）连星号一起换
    r3 = CallRedactor()
    r3.add("name", "张三丰")
    for t in ("弓长张，**", "弓长张**", "弓长张 **"):
        assert unmask(r3.apply("户名" + t + "。")) == "户名那个名字。", t
