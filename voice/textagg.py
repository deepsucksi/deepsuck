"""流式 TTS 用的中文分句器：LLM 边吐字边切，遇到句末标点立即送合成，遇到逗号等子句标点且攒够字数也送。

和 Pipecat 默认的 SimpleTextAggregator 相比：不等下一个 token 做前瞻，且在逗号处也能切，
第一段文本更早到达 TTS。括号/书名号/引号/Markdown 粗体未闭合时不切，保证 GuardTextFilter
（去括号动作、脱敏）拿到的是完整片段。

#187 / hold_transfer：不足 min_clause_chars 字、又带“转 / 汇”的短句（「转。」「转过去啊。」「转…」）不在句末单独切出去，
接着攒到下一句一起送，让 GuardTextFilter 里的 hold_transfer 看到「转过去啊。卡号多少」这样的整段；回复结束时 flush 照样送出。
只有这类短句会多等一句，其余切法不变。

#261：逗号等子句标点处，若号码 / 金额 / 拆字报姓尚未说完则不切（例如「卡号是6222，」「金额是500，」「弓长张，」），
等后续字到齐或句末 / flush 再送，避免跨段打码漏字；句末标点仍立即切（由 GuardTextFilter 脱敏）。
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Optional

from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType, BaseTextAggregator

SENTENCE_END = set("。！？!?；;…\n")
CLAUSE_END = set("，,、：:")
_HOLD = set("转汇")  # 含这些字的短句先不单独切（见模块说明）
_OPEN = {"（": "）", "(": ")", "【": "】", "[": "]", "《": "》", "“": "”", "‘": "’", "<": ">"}

# #261：号码 / 金额进行中不在子句标点处切（口径对齐 voice/turndigits.digit_state 的引导词与位数）
_DIG = "0-9０-９零〇一二三四五六七八九幺两"
_DIG_AMOUNT = _DIG + "十拾百千千万亿"  # 金额里的数位（万/亿在这里是数，不是单位）
_DIGIT_CHAR = re.compile(rf"[{_DIG}]")
_TAIL_RUN = re.compile(rf"([{_DIG}](?:[\s\-—,，、.·]*[{_DIG}])*)\s*$")
_CN_AMOUNT_TAIL = re.compile(rf"([{_DIG_AMOUNT}](?:[\s\-—,，、.·]*[{_DIG_AMOUNT}])*)\s*$")
_LEADS = (
    (re.compile(r"卡号|银行卡|账号|帐号|账户|帐户|户号"), 16),
    (re.compile(r"手机号?|电话|号码|联系方式"), 11),
    (re.compile(r"验证码|校验码|动态码|密码"), 6),
    (re.compile(r"金额|转账|汇款|打款|保证金"), None),  # 金额：数字后还没跟单位
)
_LOOKBACK = 14
_MONEY_UNIT = re.compile(r"(?:块钱|万元|万块|块|元|角|分)\s*$")  # 不用裸「万/亿」：「一万，二千」里的万是数位

# 拆字报姓（共享核心 extractors nameRules.split.spellings）；末尾是拆字姓时不在逗号处切，免得名单独成段
def _split_end_re() -> re.Pattern:
    from deepsuck.core import load
    spells = load("extractors")["nameRules"]["split"]["spellings"]
    alts = "|".join(re.escape(s) for s in sorted(spells, key=len, reverse=True))
    return re.compile(rf"(?:{alts})\s*$")


_SPLIT_END: Optional[re.Pattern] = None


def _split_at_end(body: str) -> bool:
    global _SPLIT_END
    if _SPLIT_END is None:
        _SPLIT_END = _split_end_re()
    return bool(_SPLIT_END.search(body))


def _split_name_open(core: str) -> bool:
    """拆字报姓未说完，或拆字后只跟了 1–2 字名（「口天吴，一凡，」）仍等后续。"""
    if _split_at_end(core):
        return True
    from deepsuck.core import load
    spells = load("extractors")["nameRules"]["split"]["spellings"]
    for sp in sorted(spells, key=len, reverse=True):
        i = core.rfind(sp)
        if i < 0:
            continue
        rest = core[i + len(sp):].lstrip("，,、：:；;。 \t")
        if re.fullmatch("[\u4e00-\u9fff]{1,2}", rest or ""):
            return True
    return False


def _ndigits(s: str) -> int:
    return len(_DIGIT_CHAR.findall(s))


def clause_incomplete(text: str) -> bool:
    """缓冲区（含刚写入的子句标点）是否仍处于号码 / 金额 / 拆字报姓未说完状态。

    只用于逗号等 CLAUSE_END：句末仍切，flush 仍送。"""
    body = (text or "").rstrip()
    if not body:
        return False
    # 去掉末尾子句标点再判断
    core = body.rstrip("".join(CLAUSE_END) + " ")
    if not core:
        return False
    if _split_name_open(core):
        return True
    # 无单位的金额尾巴（「有一万，」「是500，」）。长阿拉伯数字串交给下面的卡号/手机规则，避免 16 位卡号被当成未完成金额。
    am = _CN_AMOUNT_TAIL.search(core)
    if am and not _MONEY_UNIT.search(core):
        run_am = am.group(1)
        an = len(re.findall(rf"[{_DIG_AMOUNT}]", run_am))
        abefore = core[max(0, am.start(1) - _LOOKBACK):am.start(1)]
        has_cn = bool(re.search(r"[零〇一二三四五六七八九幺两十拾百千千万亿]", run_am))
        ctx = bool(re.search(r"(?:有|是|到|了|剩|还|共|付|交|收|转|汇|打|金额)\s*$", abefore))
        if has_cn and (an >= 2 or ctx):
            return True
        if (not has_cn) and an <= 4 and ctx:  # 「是500，」短阿拉伯金额
            return True
    m = _TAIL_RUN.search(core)
    if not m:
        return False  # 无尾数字串：拆字已在上面处理完
    run = m.group(1)
    n = _ndigits(run)
    before = core[max(0, m.start(1) - _LOOKBACK):m.start(1)]
    for pat, need in _LEADS:
        hit = None
        for h in pat.finditer(before):
            hit = h
        if hit is None:
            continue
        if need is None:  # 金额：数字后面还没跟单位
            return not _MONEY_UNIT.search(core)
        return n < need
    # 无引导词的卡号/手机片段：3–10 或 12–15 位（对齐 turndigits）
    if n >= 3 and n != 11 and n < 16:
        return True
    return False


class ClauseTextAggregator(BaseTextAggregator):
    def __init__(self, *, min_clause_chars: int = 6, **kwargs):
        super().__init__(aggregation_type=AggregationType.SENTENCE, **kwargs)
        self._min = max(1, int(min_clause_chars))
        self._text = ""

    @property
    def text(self) -> Aggregation:
        return Aggregation(text=self._text.strip(" "), type=AggregationType.SENTENCE)

    def _balanced(self) -> bool:
        stack = []
        for ch in self._text:
            if ch in _OPEN:
                stack.append(_OPEN[ch])
            elif stack and ch == stack[-1]:
                stack.pop()
        return not stack and self._text.count("**") % 2 == 0

    def _content_len(self) -> int:
        return sum(1 for ch in self._text if not ch.isspace() and ch not in SENTENCE_END and ch not in CLAUSE_END)

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        for ch in text:
            self._text += ch
            cut = False
            if ch in SENTENCE_END:
                n = self._content_len()
                cut = n > 0 and self._balanced() and not (n < self._min and any(c in _HOLD for c in self._text))
            elif ch in CLAUSE_END:
                cut = (self._content_len() >= self._min and self._balanced()
                       and not clause_incomplete(self._text))  # #261
            if cut:
                out, self._text = self._text.strip(" "), ""
                yield Aggregation(text=out, type=AggregationType.SENTENCE)

    async def flush(self) -> Optional[Aggregation]:
        if self._text.strip():
            out, self._text = self._text.strip(" "), ""
            return Aggregation(text=out, type=AggregationType.SENTENCE)
        self._text = ""
        return None

    async def handle_interruption(self):
        self._text = ""

    async def reset(self):
        self._text = ""
