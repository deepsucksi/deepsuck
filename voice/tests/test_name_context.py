"""#222：姓名语境里的真名（转给 / 打给 / 汇给 X、是 X 吗、我叫 / 我是 X）在语音链路上的表现。

规则只有一份：core/extractors.json nameRules.nameContext（deepsuck.extractors.find_name_context）。语音不另写正则：
- 骗子说的话：Session.ingest → extract_sensitive 抽出 name → raw_intel → IntelProcessor.call_redact 让 CallRedactor 学到这个名字，
  送进模型的是「我叫张*」；之后机器人复述（「张三是吧」）由 CallRedactor 打码。
- 机器人自己说的：GuardTextFilter → speakable → guard_output 里的 redact_text 走同一条规则，念「那个名字」。
「张三是吧」由 #226 的共享「名字+是吧」规则覆盖。"""
import asyncio

import pytest

from deepsuck.engine import Session
from deepsuck.extractors import find_name_context
from deepsuck.refs import heard_refs
from deepsuck.rng import mulberry32
from voice import persona as P
from voice.callredact import CallRedactor
from voice.processors import GuardTextFilter, IntelProcessor
from voice.textagg import ClauseTextAggregator


async def _chain(text, red, refs, step):
    agg = ClauseTextAggregator()
    f = GuardTextFilter(red, refs=(lambda: refs) if refs is not None else None)
    segs = []
    for i in range(0, len(text), step):
        async for a in agg.aggregate(text[i:i + step]):
            segs.append(a.text)
    last = await agg.flush()
    if last:
        segs.append(last.text)
    return "".join([await f.filter(s) for s in segs])


def run(text, red=None, refs=(), step=1):
    return asyncio.run(_chain(text, red if red is not None else CallRedactor(),
                              heard_refs(list(refs)) if refs is not None else None, step))


BOT_MASKED = {
    "转给李四": "转给那个名字",
    "是李四吗": "是那个名字吗",
    "是李明吗": "是那个名字吗",
    "我叫张三": "我叫那个名字",
}
UNCHANGED = ["我是退休的", "我是他妈", "我是王阿姨", "是马上吗", "是真的吗", "转给银行", "打给客服"]


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("refs", [None, ()])
@pytest.mark.parametrize("text,want", list(BOT_MASKED.items()))
def test_bot_output_name_context_masked(text, want, refs, step):
    assert find_name_context(text), "共享规则应认出这个名字"
    assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("text", UNCHANGED)
def test_not_names_unchanged(text, step):
    assert not find_name_context(text)
    assert run(text, step=step) == text


def _reported(said):
    s = Session(scenario="police", persona="wang", rng=mulberry32(5), now=lambda: 0)
    p = IntelProcessor(s)
    a = p.call_redact(s.ingest(said))
    return p, a


@pytest.mark.parametrize("said,name,echo,want", [
    ("我叫张三", "张三", "张三是吧", "那个名字是吧"),
    ("转给李四", "李四", "李四是吧", "那个名字是吧"),
    ("是李四吗", "李四", "是李四吗", "是那个名字吗"),
])
def test_scammer_said_name_learned_and_echo_masked(said, name, echo, want):
    p, a = _reported(said)
    assert name not in a["redacted"]  # 送进模型的已打码
    assert name not in "".join(m["text"] for m in p.session.messages if m.get("role") == "scammer")
    for step in (1, 3):
        assert run(echo, red=p.redactor, refs=[said], step=step) == want


@pytest.mark.parametrize("text,want", [("张三是吧", "那个名字是吧"), ("王五是吧", "那个名字是吧"), ("李四是吧", "那个名字是吧")])
def test_name_shiba_masked_without_prior_mention(text, want):
    """#226 合入的共享「名字+是吧」规则：对方没报过也打码。"""
    for refs in (None, ()):
        for step in (1, 3):
            assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("text", ["王总是吧", "张经理是吧", "对是吧", "好是吧", "王阿姨是吧"])
def test_title_shiba_unchanged(text):
    assert run(text) == text


@pytest.mark.parametrize("text", ["户名*元", "户名***元", "户名**元"])
def test_huming_stars_yuan_reads_name(text):
    """负责人定：「户名*元」念「户名那个名字」，户名保留，不剩「元」。"""
    for refs in (None, ()):
        for step in (1, 3):
            assert run(text, refs=refs, step=step) == "户名那个名字"


def test_transfer_name_amount_unreported_now_masked():
    """#216 的缺口：共享规则单独看整句仍不认「转给李四五百块」；语音 guard_output 在金额开头截断后用 find_name_context 补上（#227）。"""
    assert find_name_context("转给李四五百块"), "#220 起共享规则已认整句"
    assert run("转给李四五百块") == "转给那个名字五百块"


@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("echo,want", [
    ("转给李四五百块", "转给那个名字五百块"),
    ("给李四三千", "给那个名字三千"),
    ("李四两万块", "那个名字两万块"),
    ("转给李四五百", "转给那个名字五百"),
    ("李四，五百块", "那个名字，五百块"),
])
def test_reported_name_then_amount_keeps_digit(echo, want, step):
    """#222：报过名字后，名字后面紧跟的中文金额不被吞字（原来念「转给那个名字百块」）。"""
    p, _ = _reported("收款人叫李四")
    assert run(echo, red=p.redactor, refs=["收款人叫李四"], step=step) == want


@pytest.mark.parametrize("text,want", [
    ("王*五", "那个名字"),            # 中间打码的三字名，「五」是名字里的字，照旧吃掉
    ("王*五是吧", "那个名字是吧"),
    ("户名王*五", "户名那个名字"),
    ("转给王*五", "转给那个名字"),
    ("王*二", "那个名字"),
    ("李*五百块", "那个名字五百块"),   # 数字后面还跟着数字 / 单位：金额，不吃
    ("李*三千元", "那个名字三千元"),
    ("打给张*两千", "打给那个名字两千"),
    ("打给张经理两千", "打给张经理两千"),  # 称呼不是名字，不动
])
def test_single_star_amount_vs_middle_mask(text, want):
    assert P.speakable(text, calm_tts=False) == want
    assert run(text) == want


# ---- #222 追加（情报复查）：报过 / 已打码的名字后面紧跟金额 ----------------------------------------------------
@pytest.mark.parametrize("step", [1, 3])
@pytest.mark.parametrize("echo,want", [
    ("转给李四五百块", "转给那个名字五百块"),
    ("汇给张三三万块", "汇给那个名字三万块"),
])
def test_reported_two_names_amount(echo, want, step):
    p, _ = _reported("收款人叫李四")
    p.redactor.add("name", "张三")
    out = run(echo, red=p.redactor, refs=["收款人叫李四"], step=step)
    assert out == want
    assert "那么些钱" not in out


@pytest.mark.parametrize("step", [1, 3])
def test_reported_name_arabic_amount_no_surname_leak(step):
    """「转给李四500」：不露「李」、不念「你发的那个号」、不留星号。500 本身按 #121 / #167 数字过滤念含糊说法（不在本 PR 改）。"""
    p, _ = _reported("收款人叫李四")
    out = run("转给李四500", red=p.redactor, refs=["收款人叫李四"], step=step)
    assert out.startswith("转给那个名字")
    assert "李" not in out and "你发的那个号" not in out and "*" not in out


@pytest.mark.parametrize("text,want_prefix", [
    ("转给李*五百块", "转给那个名字五百块"),
    ("张**三万块", "那个名字三万块"),
    ("汇给张**三万块", "汇给那个名字三万块"),
    ("李**500", "那个名字"),
    ("转给李**500", "转给那个名字"),
    ("是**明吗", "是那个名字吗"),
    ("张**三", "那个名字"),          # 残名单字照旧吃掉
])
def test_raw_masked_name_amount_chain(text, want_prefix):
    for refs in (None, ()):
        for step in (1, 3):
            out = run(text, refs=refs, step=step)
            assert out.startswith(want_prefix), out
            assert not any(c in out for c in "*＊李张明") and "你发的那个号" not in out


@pytest.mark.parametrize("text", ["卡号是6222**500", "尾号*500"])
def test_number_context_stars_digits_unchanged_semantics(text):
    """号码语境里的星号 + 数字仍按号码念，不当名字。"""
    assert "那个名字" not in P.speakable(text, calm_tts=False)


# ---- #227 情报复审（必改）：没打码的原文里真名后面紧跟金额，数字过滤先跑会露姓 ----------------------------------
@pytest.mark.parametrize("step", [1, 3, 50])
@pytest.mark.parametrize("refs", [None, ()])
@pytest.mark.parametrize("text,want", [
    ("汇给张三三万块", "汇给那个名字三万块"),
    ("打给王五两千", "打给那个名字两千"),
    ("转给李四五百块", "转给那个名字五百块"),
    ("转给王五五百块", "转给那个名字五百块"),   # 名字里带数字字（王五）+ 中文金额
    ("打给王五", "打给那个名字"),
])
def test_raw_name_then_cn_amount(text, want, refs, step):
    assert P.speakable(text, calm_tts=False) == want
    assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("step", [1, 3])
def test_raw_name_then_arabic_amount_no_surname(step):
    """「转给李四500」：不露「李」；500 按 #121 / #167 念含糊说法（负责人定：不复述 2 位以上数字）。"""
    for out in (P.guard_output("转给李四500"), P.speakable("转给李四500", calm_tts=False), run("转给李四500", step=step)):
        assert out.startswith("转给那个名字") and "李" not in out and "500" not in out and "你发的那个号" not in out


@pytest.mark.parametrize("text", ["转给他三千", "打给客服两千", "卡号6222021234567890123"])
def test_non_name_amounts_unchanged_by_early_mask(text):
    assert "那个名字" not in P.guard_output(text)


@pytest.mark.parametrize("step", [1, 3])
@pytest.mark.parametrize("refs", [None, ()])
@pytest.mark.parametrize("text,want", [
    ("我是李四十岁", "我是那个名字十岁"),   # #227 四审：名字后面紧跟「十岁」
    ("姓名张三", "姓名那个名字"),           # #227 四审：字段词后的真名
    # #227 五审（情报 review 5583446683 必改；name_amount.json 只在未合并的 #220，用例先放 voice 测试）
    ("姓名*五百块", "姓名那个名字五百块"),   # 字段词 + 星号 + 中文金额不吞金额（同 #220）
    ("户名**五百块", "户名那个名字五百块"),
    ("张三三点钟", "那个名字三点钟"),       # r220b：句首名字 + 时间
])

def test_voice_side_name_leaks_fixed(text, want, refs, step):
    assert P.guard_output(text) == want
    assert P.speakable(text, calm_tts=False) == want
    assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("text,want", [
    ("给王五三千块", "给那个名字三千块"), ("给张明三万", "给那个名字三万"),
    ("是张三五百块", "是那个名字五百块"), ("叫李三三万", "叫那个名字三万"),
])
def test_lead_gei_shi_jiao_wait_220(text, want):
    assert P.speakable(text, calm_tts=False) == want


@pytest.mark.parametrize("text", ["转给张三1000元", "汇给王五1000元", "打给李明1000元"])
def test_fuzz_lead_name_arabic_amount_no_surname(text):
    """#227 五审 fuzz 类：转给 / 汇给 / 打给 + 名字 + 1000元 不露姓（数字照 #121 念含糊说法）。"""
    for out in (P.guard_output(text), P.speakable(text, calm_tts=False)):
        assert out.startswith(text[:2] + "那个名字") and text[2] not in out and "1000" not in out


@pytest.mark.parametrize("text", ["转给王总三万", "是三万吧", "给你三千块"])
def test_fuzz_non_names_untouched(text):
    assert "那个名字" not in P.guard_output(text)


@pytest.mark.parametrize("step", [1, 3])
def test_surname_stars_digits_no_surname(step):
    """#227 四审：「张**1234」不露「张」，整段按号码念含糊说法。"""
    for out in (P.guard_output("张**1234"), P.speakable("张**1234", calm_tts=False), run("张**1234", step=step)):
        assert "张" not in out and "1234" not in out and "那个名字" not in out


def test_compound_surname_amount_gap():
    out = P.guard_output("汇给欧阳娜娜两万")
    assert not any(c in out for c in "欧阳娜")


# ---- 负责人定：字段词 收款人 / 户名 / 姓名 / 账户名 后的打码姓名，字段词一个字不吃，后面不剩「元」---------------
@pytest.mark.parametrize("text,want", [
    ("收款人**元", "收款人那个名字"), ("收款人*元", "收款人那个名字"),
    ("户名*元", "户名那个名字"), ("户名***元", "户名那个名字"),
    ("姓名**元", "姓名那个名字"), ("姓名*元", "姓名那个名字"), ("姓名***元", "姓名那个名字"), ("姓名**", "姓名那个名字"),
    ("姓名：***", "姓名：那个名字"), ("姓名是张**", "姓名是那个名字"),
    ("账户名**元", "账户名那个名字"), ("账户名*元", "账户名那个名字"), ("账户名：李*", "账户名：那个名字"),
])
def test_field_word_kept_no_leftover(text, want):
    for refs in (None, ()):
        for step in (1, 3):
            assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("text", ["我姓名都忘了", "填姓名的地方"])
def test_field_word_without_stars_unchanged(text):
    assert run(text) == text


@pytest.mark.parametrize("text,want", [
    ("收款人**元宝", "收款人那个名字"),     # 不吃「人」
    ("收款人马**元", "收款人那个名字"),     # 不剩「元」
    ("户名：高**元", "户名：那个名字"),
    ("开户名**元", "开户名那个名字"),
    ("户名*元宝", "户名那个名字"),
])
def test_field_word_corpus220_edges(text, want):
    """与语料 #220 的边界修正对齐。"""
    for refs in (None, ()):
        for step in (1, 3):
            assert run(text, refs=refs, step=step) == want


@pytest.mark.parametrize("text,want", [("转给李四五百块", "转给那个名字五百块"), ("转给李四几百块", "转给那个名字几百块")])
def test_raw_speakable_keeps_first_amount_char(text, want):
    """情报（#216）：speakable 原文路径不能吞掉金额第一个字。"""
    for calm in (False, True):
        assert P.speakable(text, calm_tts=calm) == want
    assert run(text) == want


@pytest.mark.parametrize("step", [1, 3])
@pytest.mark.parametrize("text,want", [("是张伟，500", "是那个名字，"), ("是张伟，五百块", "是那个名字，五百块")])
def test_shi_name_comma_amount_masked(text, want, step):
    """#227 fuzz 模板 c：名字和金额之间隔逗号，也不露姓（数字照 #121 念含糊说法）。"""
    for out in (P.guard_output(text), P.speakable(text, calm_tts=False), run(text, step=step)):
        assert out.startswith(want) and "张" not in out and "500" not in out


@pytest.mark.parametrize("text", ["是的，500", "给你，500", "给钱三万"])
def test_comma_amount_non_names_untouched(text):
    for out in (P.guard_output(text), P.speakable(text, calm_tts=False)):
        assert "那个名字" not in out and out.startswith(text[:2])
