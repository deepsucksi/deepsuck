"""流式 TTS 用的中文分句器：LLM 边吐字边切，遇到句末标点立即送合成，遇到逗号等子句标点且攒够字数也送。

和 Pipecat 默认的 SimpleTextAggregator 相比：不等下一个 token 做前瞻，且在逗号处也能切，
第一段文本更早到达 TTS。括号/书名号/引号/Markdown 粗体未闭合时不切，保证 GuardTextFilter
（去括号动作、脱敏）拿到的是完整片段。
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType, BaseTextAggregator

SENTENCE_END = set("。！？!?；;…\n")
CLAUSE_END = set("，,、：:")
_OPEN = {"（": "）", "(": ")", "【": "】", "[": "]", "《": "》", "“": "”", "‘": "’", "<": ">"}


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
                cut = self._content_len() > 0 and self._balanced()
            elif ch in CLAUSE_END:
                cut = self._content_len() >= self._min and self._balanced()
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
