"""中文打断策略：机器人说话时，“嗯/对/好”这类应答词不触发打断。

Pipecat 的 MinWordsUserTurnStartStrategy 用 text.split() 数词，对不带空格的中文永远是 1 个词。
这里改为数“有效字”：去掉标点、空白和应答词后剩下的汉字（以及字母数字串，各算一个）。
机器人没在说话时，任何非空识别结果都开启用户回合，保证“嗯”作为回答也能被听到。
"""
from __future__ import annotations

import re

from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.min_words_user_turn_start_strategy import MinWordsUserTurnStartStrategy

# 单字应答/语气词；连续出现（“嗯嗯”“对对对”“好的好的”）也只算应答
BACKCHANNEL_CHARS = set("嗯恩啊阿哦噢喔欸诶哎唉呃额哈嘿呀哇吧呢嘛啦喂对是好行")
BACKCHANNEL_WORDS = ("好的", "是的", "对的", "没错", "知道", "明白", "可以", "行吧", "然后呢")
_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:…—\-~～\"'“”‘’（）()\[\]【】《》]+")
_ASCII = re.compile(r"[A-Za-z0-9]+")


_NEGATED = re.compile(r"[不没别]([是对好行])")


def meaningful_chars(text: str) -> int:
    s = _PUNCT.sub("", text or "")
    s = _NEGATED.sub(r"不否", s)  # “不是/不对/不行”是反驳，不是应答，两个字都算
    for w in BACKCHANNEL_WORDS:
        s = s.replace(w, "")
    n = len(_ASCII.findall(s))
    s = _ASCII.sub("", s)
    return n + sum(1 for ch in s if ch not in BACKCHANNEL_CHARS)


class ChineseMinCharsUserTurnStartStrategy(MinWordsUserTurnStartStrategy):
    """机器人说话时需要至少 min_chars 个有效字才开启用户回合（并打断）；否则任意非空文本即可。"""

    def __init__(self, *, min_chars: int = 2, use_interim: bool = True, **kwargs):
        super().__init__(min_words=min_chars, use_interim=use_interim, **kwargs)
        self._min_chars = min_chars

    @property
    def bot_speaking(self) -> bool:
        return self._bot_speaking

    async def _handle_transcription(self, frame: TranscriptionFrame | InterimTranscriptionFrame) -> ProcessFrameResult:
        text = (frame.text or "").strip()
        if self._bot_speaking:
            trigger = meaningful_chars(text) >= self._min_chars
        else:
            trigger = bool(_PUNCT.sub("", text))
        if trigger:
            await self.trigger_user_turn_started()
            return ProcessFrameResult.STOP
        await self.trigger_reset_aggregation()
        return ProcessFrameResult.CONTINUE


def user_turn_strategies(min_chars: int):
    """开始：中文有效字策略（代替默认的 VAD/任意转写即打断）；结束：沿用 Pipecat 默认。"""
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    return UserTurnStrategies(start=[ChineseMinCharsUserTurnStartStrategy(min_chars=min_chars)])
