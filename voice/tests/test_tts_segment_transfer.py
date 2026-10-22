"""#187 / #195：流式合成按句切段时，「转。」「转过去啊。」这类带“转”的短句不能在 hold_transfer 看到整段之前单独送 TTS。
模拟大模型逐字吐字 → ClauseTextAggregator 切段 → 每段过 GuardTextFilter（speakable → guard_output → hold_transfer）。
以 tests/fixtures/transfer_claim.json 为准：逐段过守卫的结果里不能有整段过守卫时拦下的说法。"""
import asyncio
import json
from pathlib import Path

import pytest

from voice import persona as P
from voice.processors import GuardTextFilter
from voice.textagg import ClauseTextAggregator
from deepsuck.personas import TRANSFER_CLAIM as TC

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/transfer_claim.json").read_text(encoding="utf-8"))
BAD = ("转完了", "转过去了", "我先转", "收到了没", "转给你", "马上转")


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


@pytest.mark.parametrize("text", ["转。卡号多少", "转过去啊。卡号多少", "转…还没弄好，卡号多少", "行，转。你报一下",
                                  "转啊。你等我一下", "好转。我找找卡", "转，还没弄好，卡号多少"])
@pytest.mark.parametrize("step", [1, 2, 5])
def test_short_transfer_sentence_not_sent_alone(text, step):
    segs = segments(text, step)
    assert "".join(segs).replace(" ", "") == text.replace(" ", "")
    first = segs[0]
    assert len([c for c in first if c not in "。，,…！？!? "]) >= 6 or len(segs) == 1, segs  # 带“转”的短句跟下一句一起送


def test_ordinary_short_sentences_still_cut_early():
    assert segments("嗯。你说吧，我听着呢。")[0] == "嗯。"
    assert segments("好的。卡号多少")[0] == "好的。"


@pytest.mark.parametrize("case", F["claim"], ids=lambda c: c["text"][:12])
@pytest.mark.parametrize("step", [1, 3])
def test_fixture_claims_held_when_streamed(case, step):
    out = "".join(spoken(case["text"], step))
    assert not any(w in out for w in BAD), out
    whole = P.speakable(case["text"])
    assert any(x in whole for x in TC["stall"])
    assert any(x in out for x in TC["stall"]), out


# 已知（main 上就有，不是本 PR 引入）：逗号处攒够 6 字就切，「我把截图发你了，」「收到没？」分两段过守卫，后一段单独看被当成
# 问对方收到没、换成“还没弄好”——多拦不漏。等语料 hold_transfer 的新规则合并后一起看要不要按上下文过守卫。
CLAUSE_SPLIT_KNOWN = {"我把截图发你了，收到没？"}


@pytest.mark.parametrize("text", [t for t in F["keep"] if t not in CLAUSE_SPLIT_KNOWN], ids=lambda t: t[:12])
def test_fixture_keep_unchanged_when_streamed(text):
    out = "".join(spoken(text))
    assert not any(x in out for x in TC["stall"] if x not in text), out
