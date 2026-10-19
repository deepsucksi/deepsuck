"""#215：输出端拦住拆字解释。模型自己复述「收款人是弓长张，伟大的伟对吧」「龚厂长，伟大的伟对吧」「是伟大的伟吗」时，
拆字解释连同它解释的姓名整体换成已批的「那个名字」（规则替换，不是新台词）。

每条用例分别按整句、逐字流式、每 3 字流式送进 ClauseTextAggregator → GuardTextFilter(CallRedactor())（内部走 speakable /
guard_output），断言：任何一个分句里都不出现姓名里的字（也不出现拆字说法本身）、没有星号；输出里去掉「那个名字」以后，
每个字都是原句里有的（一个字的新台词都不加）。反例（「伟大的祖国」「宫长张罗了一桌菜」「尔东陈列馆」、小林三句已批台词）不改。
"""
import asyncio
import json
from pathlib import Path

import pytest

from voice import persona as P
from voice.callredact import CallRedactor
from voice.processors import GuardTextFilter
from voice.textagg import ClauseTextAggregator

ROOT = Path(__file__).resolve().parents[2]
NP = P.NAME_PHRASE


async def _stream(text: str, step: int):
    agg, flt, out = ClauseTextAggregator(min_clause_chars=6), GuardTextFilter(CallRedactor()), []
    for i in range(0, len(text), step):
        async for a in agg.aggregate(text[i:i + step]):
            out.append(await flt.filter(a.text))
    r = await agg.flush()
    if r:
        out.append(await flt.filter(r.text))
    return out


def chunks(text: str, mode: str):
    if mode == "整句":
        return [P.speakable(text, calm_tts=False)], asyncio.run(_stream(text, len(text)))
    return [], asyncio.run(_stream(text, 1 if mode == "逐字流式" else 3))


# (类别, 模型复述的话, 不许出现的字 / 说法)
CASES = [
    # 「X大的X」「X名的X」这类逐字解释
    ("X大的X", "伟大的伟对吧", ("伟",)),
    ("X大的X", "收款人是弓长张，伟大的伟对吧", ("伟", "张", "弓长")),
    ("X大的X", "户名是伟大的伟，明天的明", ("伟", "明")),
    ("X大的X", "伟是伟大的伟，晨是早晨的晨", ("伟", "晨")),
    ("X名的X", "著名的著，对吗", ("著",)),
    ("X名的X", "收款人叫有名的名对吧", ("名",)),
    ("X名的X", "就是著名的著", ("著",)),
    # 拆字报姓和 ASR 同音变体
    ("拆字", "收款人是弓长张，伟大的伟对吧", ("伟", "张", "弓长")),
    ("拆字", "龚厂长，伟大的伟对吧", ("伟", "龚厂长", "长")),
    ("拆字", "工长张，明天的明对吧", ("明", "张", "工长")),
    ("拆字", "户名耳东陈，东方的东是吧", ("陈", "东")),
    ("拆字", "二东陈，东方的东", ("陈", "东", "二东")),
    ("拆字", "口天吴，一凡，记好了", ("吴", "口天", "一凡", "凡")),
    ("拆字", "扣田吴，著名的著吗", ("吴", "著", "扣田")),
    ("拆字", "弓长张三丰", ("张", "三丰", "弓长")),
    ("拆字", "好的，龚厂长，伟大的伟，明天的明，我记下了", ("伟", "明", "龚厂长")),
    # 问句
    ("问句", "是伟大的伟吗", ("伟",)),
    ("问句", "是伟大的伟吗？", ("伟",)),
    ("问句", "是弓长张吗", ("张", "弓长")),
    ("问句", "收款人是不是耳东陈，东方的东？", ("陈", "东")),
    ("问句", "那个伟是伟大的伟吗", ("伟",)),
    # 人设口头前缀
    ("口头前缀", "哦，那是伟大的伟吗", ("伟",)),
    ("口头前缀", "哦，那……弓长张，伟大的伟对吧", ("伟", "张", "弓长")),
    ("口头前缀", "你刚说龚厂长，伟大的伟？", ("伟", "龚厂长")),
    ("口头前缀", "你刚说口天吴，一凡，对吧", ("吴", "一凡", "口天")),
    ("口头前缀", "哦，你刚说的是耳东陈，东方的东是吧", ("陈", "东")),
]
MODES = ("整句", "逐字流式", "每3字流式")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind,text,leak", CASES, ids=[f"{k}:{t}" for k, t, _ in CASES])
def test_explain_never_spoken(kind, text, leak, mode):
    whole, parts = chunks(text, mode)
    for seg in whole + parts:
        bare = seg.replace(NP, "")
        for w in leak:
            assert w not in bare, (mode, text, seg, w)
        assert "*" not in seg and "＊" not in seg, (mode, text, seg)
    joined = "".join(parts)
    assert NP in joined, (mode, text, parts)
    extra = set(joined.replace(NP, "")) - set(text) - set("，,。？?！!…、 ")
    assert not extra, ("加了新字", mode, text, joined, extra)


@pytest.mark.parametrize("text,want", [
    ("收款人是弓长张，伟大的伟对吧", "收款人是那个名字对吧"),
    ("龚厂长，伟大的伟对吧", "那个名字对吧"),
    ("是伟大的伟吗", "是那个名字吗"),
    ("哦，那是伟大的伟吗", "哦，那是那个名字吗"),
    ("你刚说弓长张，伟大的伟？", "你刚说那个名字？"),
])
def test_explain_replaced_whole(text, want):
    assert P.guard_output(text) == want
    assert P.speakable(text, calm_tts=False) == want
    for step in (1, 3):  # 流式分句各自替换后，GuardTextFilter 不重复「那个名字」
        assert "".join(asyncio.run(_stream(text, step))) == want


@pytest.mark.parametrize("text", ["伟大的祖国", "宫长张罗了一桌菜", "尔东陈列馆", "这是大家的家", "伟大的伟人", "明天的明天会更好",
                                  "东方的东西", "我的卡", "户名和账号", "收款人信息", "弓长岭"])
@pytest.mark.parametrize("mode", MODES)
def test_counterexamples_untouched(text, mode):
    assert P.drop_name_explain(text) == text
    whole, parts = chunks(text, mode)
    assert all(NP not in seg for seg in whole + parts), (mode, text, whole, parts)


# 小林三句已批台词（#198 / #200，逐字照抄批文）
LIN_APPROVED = {
    ("otp_stall", 12): "码我看到了，就露出来开头一点，后面被通知横幅挡住了，我划一下。",
    ("loan_stall", 5): "分期能分多少期？短的长的你都说下，我先拿计算器算一下…",
    ("coop_step", 7): "在下载了，进度条走了一大半，好了跟你说。",
}
_PJ = json.loads((ROOT / "site/assets/core/personas.json").read_text(encoding="utf-8"))
_LIN = next(p for p in _PJ["personas"] if p["id"] == "lin")


@pytest.mark.parametrize("key", list(LIN_APPROVED), ids=lambda k: f"{k[0]}[{k[1]}]")
def test_lin_approved_lines_unchanged(key, monkeypatch):
    line = _LIN["templates"][key[0]][key[1]]
    line = line["t"] if isinstance(line, dict) else line
    assert line == LIN_APPROVED[key]  # 台词文件里逐字不变
    assert P.drop_name_explain(line) == line
    got = P.guard_output(line)
    monkeypatch.setattr(P, "drop_name_explain", lambda s: s)
    assert got == P.guard_output(line)  # 加了拆字拦截以后，输出守卫对这三句的结果和以前一样
    for step in (1, 3, len(line)):
        assert NP not in "".join(asyncio.run(_stream(line, step)))


def test_persona_lines_untouched():
    """台词库里没有一句会被拆字拦截改动（说明字段除外）。"""
    bad = []

    def walk(o, path):
        if isinstance(o, str):
            if P.drop_name_explain(o) != o:
                bad.append((path, o))
        elif isinstance(o, dict):
            for k, v in o.items():
                if "omment" not in k:
                    walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(_PJ, "")
    assert not bad, bad


# ---- #219 情报复审必改 3、4 --------------------------------------------------------------------------------------
# 必改 3：粗体星号 + 拆字 / 逐字解释。负责人定的顺序：先 guard_output（drop_name_explain 先生效），姓名替换在它之后。
# main d798641 实测：「收款人是**弓长张**」→「收款人那个名字那个名字」（不露字）；#219 5285347 回归成「收款人那个名字长那个名字」。
@pytest.mark.parametrize("text,want,main_d798641", [
    ("收款人是**弓长张**", "收款人那个名字", "收款人那个名字那个名字"),
    ("**伟大的伟**对吧", "那个名字对吧", "那个号伟大的那个名字对吧"),
    ("收款人是**弓长张，伟大的伟**对吧", "收款人那个名字对吧", None),
])
@pytest.mark.parametrize("mode", ["整句", "逐字流式", "三字流式"])
def test_bold_stars_with_explain_r219(text, want, main_d798641, mode):
    whole, parts = chunks(text, mode)
    for out in whole + ["".join(parts)]:
        for c in "弓长张伟大的":
            assert c not in out, (out, c)
        assert "那个号" not in out and "*" not in out, out
    if whole:
        assert whole[0] == want
        if main_d798641:  # 相对 main 不回退：main 不露的现在也不露，且只用「那个名字」
            assert set(main_d798641.replace(NP, "")) >= set(whole[0].replace(NP, ""))


# 必改 4：引号、空格、逗号、前置「X，」「X——」变体（负责人定：拿不准就打码）
@pytest.mark.parametrize("text,leak", [
    ("伟大的“伟”对吧", "伟"), ("伟大的「伟」对吧", "伟"), ("伟大的『伟』对吧", "伟"), ("伟大的'伟'对吧", "伟"),
    ('伟大的"伟"对吧', "伟"), ("伟大的‘伟’对吧", "伟"),
    ("伟大的 伟对吧", "伟"), ("伟大的，伟对吧", "伟"), ("伟，伟大的伟", "伟"), ("伟——伟大的伟", "伟"),
    ("“伟”，伟大的伟", "伟"), ("弓长 张，伟大的伟", "张伟"), ("收款人是弓 长 张", "弓长张"), ("收款人是弓  长张，明天的明", "长张明"),
])
@pytest.mark.parametrize("mode", ["整句", "逐字流式", "三字流式"])
def test_explain_variants_r219(text, leak, mode):
    whole, parts = chunks(text, mode)
    for out in whole + ["".join(parts)]:
        for c in leak:
            assert c not in out, (out, c)
        assert NP in out and "那个号" not in out, out


@pytest.mark.parametrize("text", ["伟大的祖国", "尔东陈列馆", "宫长张罗了一桌菜", "伟大的伟人", "东方的东西", "这个**很重要**"])
def test_variants_counterexamples_r219(text):
    assert NP not in P.speakable(text, calm_tts=False)
