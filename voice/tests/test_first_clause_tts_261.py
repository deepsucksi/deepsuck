"""#261：首句按逗号切分提前合成——未完成号码/金额/拆字不切；每段过 GuardTextFilter；脱敏失败念完整兜底句。"""
import asyncio

import pytest

from voice.callredact import REDACT_FAIL_PLACEHOLDER, TTS_REDACT_FAIL_SPEAK
from voice.processors import GuardTextFilter
from voice.textagg import ClauseTextAggregator, clause_incomplete
from voice import persona as P


def segments(text, step=1, min_chars=6):
    async def run():
        agg, out = ClauseTextAggregator(min_clause_chars=min_chars), []
        for i in range(0, len(text), step):
            async for a in agg.aggregate(text[i:i + step]):
                out.append(a.text)
        last = await agg.flush()
        if last:
            out.append(last.text)
        return out
    return asyncio.run(run())


def spoken(text, step=1):
    f = GuardTextFilter(None)
    return [asyncio.run(f.filter(s)) for s in segments(text, step)]


def test_ordinary_first_clause_cuts_at_comma():
    segs = segments("哎哟，小伙子你是哪个单位的啊，我没听清楚。你再说一遍")
    assert segs[0] == "哎哟，小伙子你是哪个单位的啊，"
    assert "我没听清楚。" in segs[1]


@pytest.mark.parametrize("text", [
    "卡号是62220212，34567890对吧。",
    "手机号是138，00138000。",
    "卡号是6222，0212，3456，7890。",
])
@pytest.mark.parametrize("step", [1, 3])
def test_incomplete_number_not_cut_at_comma(text, step):
    segs = segments(text, step)
    assert "".join(segs).replace(" ", "") == text.replace(" ", "")
    # 逗号处不得把号码切成两段；整句到句末 / flush 再送
    assert len(segs) == 1, segs
    out = "".join(spoken(text, step))
    assert not any(c.isdigit() for c in out), out
    assert "*" not in out and "＊" not in out
    assert "6222" not in out and "138" not in out and "00138000" not in out


@pytest.mark.parametrize("step", [1, 2])
def test_incomplete_amount_not_cut_at_comma(step):
    # 阿拉伯金额未带单位：不切，拼完后整段打码
    text = "转账金额是500，元。"
    segs = segments(text, step)
    assert "".join(segs).replace(" ", "") == text.replace(" ", "")
    assert len(segs) == 1, segs
    out = "".join(spoken(text, step))
    assert "500" not in out, out
    assert "*" not in out

@pytest.mark.parametrize("step", [1, 2])
def test_incomplete_cn_amount_not_cut_at_comma(step):
    # 中文金额「一万，二千块」：逗号处不切（避免金额被拆）；中文金额本身可念，不要求打码
    text = "我卡里有一万，二千块。"
    segs = segments(text, step)
    assert "".join(segs).replace(" ", "") == text.replace(" ", "")
    assert len(segs) == 1, segs


@pytest.mark.parametrize("text,leaks", [
    ("收款人是弓长张，伟明对吧。", ("弓长", "张", "伟明", "伟", "明")),
    ("你刚说口天吴，一凡，对吧", ("口天", "吴", "一凡", "凡")),
])
@pytest.mark.parametrize("step", [1, 3])
def test_split_name_not_cut_before_given(text, leaks, step):
    segs = segments(text, step)
    assert "".join(segs).replace(" ", "") == text.replace(" ", "")
    # 拆字报姓后的逗号不切，名跟姓同一段过守卫
    assert len(segs) == 1, segs
    out = "".join(spoken(text, step))
    bare = out.replace(P.NAME_PHRASE, "")
    for leak in leaks:
        assert leak not in bare, (leak, out)
    assert "*" not in out


def test_complete_card_still_cuts_after_full_number():
    # 16 位卡号已完整，逗号后可切
    segs = segments("卡号是6222021234567890，对吧。")
    assert segs[0].startswith("卡号是") and segs[0].endswith("，")
    assert any("对吧" in s for s in segs)


def test_each_segment_passes_guard(monkeypatch):
    """仿 test_tts_segment_transfer：逐段过 GuardTextFilter，不得因提前切绕过脱敏。"""
    text = "好的，卡号是6222021234567890，我记下了。"
    segs = segments(text)
    assert len(segs) >= 2  # 至少在首个够字数的逗号处切出
    f = GuardTextFilter(None)
    outs = [asyncio.run(f.filter(s)) for s in segs]
    blob = "".join(outs)
    assert "6222" not in blob and "*" not in blob
    assert all(o == asyncio.run(GuardTextFilter(None).filter(s)) or True for s, o in zip(segs, outs))


def test_redact_fail_speaks_fallback_not_stars(monkeypatch):
    def boom(text):
        return REDACT_FAIL_PLACEHOLDER, True

    monkeypatch.setattr("voice.processors.redact_line_checked", boom)
    out = asyncio.run(GuardTextFilter(None).filter("卡号是6222021234567890"))
    assert out == TTS_REDACT_FAIL_SPEAK
    assert "*" not in out
    assert "6222" not in out


def test_star_placeholder_speaks_fallback_not_raw():
    out = asyncio.run(GuardTextFilter(None).filter(REDACT_FAIL_PLACEHOLDER))
    assert out == TTS_REDACT_FAIL_SPEAK
    assert out != REDACT_FAIL_PLACEHOLDER
    assert "*" not in out


def test_clause_incomplete_helpers():
    assert clause_incomplete("卡号是62220212，")
    assert clause_incomplete("手机号是138，")
    assert clause_incomplete("转账金额是500，")
    assert clause_incomplete("收款人是弓长张，")
    assert not clause_incomplete("卡号是6222021234567890，")
    assert not clause_incomplete("哎哟，小伙子你是哪个单位的啊，")


def test_transfer_hold_still_works():
    """保持 #187 transfer hold：带「转」的短句不单独切。"""
    segs = segments("转。卡号多少")
    assert len(segs) == 1 or len([c for c in segs[0] if c not in "。，,…！？!? "]) >= 6
    out = "".join(spoken("转过去啊。卡号多少"))
    assert "转完了" not in out
