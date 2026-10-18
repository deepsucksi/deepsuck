"""每轮延迟拆解（服务端观测，不改管线）：挂到 PipelineTask(observers=[LatencyObserver(...)])。

以“用户回合”为单位（UserStartedSpeakingFrame … UserStoppedSpeakingFrame），时间点（time.monotonic，秒）：
  speech_end  回合结束前最后一次 VAD 停说时刻 - VAD stop_secs（估计的真实停说时刻）
  turn_end    UserStoppedSpeakingFrame（回合判定结束、触发大模型）
  其余各点都取 speech_end 之后、下一个用户回合开始之前的第一次出现：
  asr_final   TranscriptionFrame
  llm_start / llm_first   LLMFullResponseStartFrame / LLMTextFrame
  tts_start / tts_first   TTSStartedFrame / TTSAudioRawFrame（回复首包，不含填充音）
  bot_start   BotStartedSpeakingFrame 或 tts_first 中较早者（含填充音）

导出（毫秒）：asr = asr_final - speech_end；turn_ms = turn_end - speech_end；llm_ttft = llm_first - llm_start；
agg = tts_start - llm_first（分句等待）；tts_ttfb = tts_first - tts_start；
e2e_reply = tts_first - speech_end；e2e_any = bot_start - speech_end。
rule 模式没有大模型，llm_* / agg 为空。

上报时机：回复首包（tts_first）一到就结算并通知客户端（此时各字段都已确定）；没有回复首包的回合
在下一个用户回合开始或 flush() 时兜底结算。

去重：同一帧在每两个处理器之间都会触发一次 on_push_frame，按 Pipecat 的 Frame.id（进程内单调递增）去重。
不能用 Python 的 id(frame)：帧释放后内存地址会被新帧复用，新的 UserStartedSpeakingFrame 会被当成
“已见过”而丢掉，结果整通电话只结算第一个回合、且要到挂断 flush 时才结算（线上 n=0 的根因）。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Awaitable, Callable, Dict, List, Optional

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

FIELDS = ("asr", "turn_ms", "llm_ttft", "agg", "tts_ttfb", "e2e_reply", "e2e_any")


def _ms(a: Optional[float], b: Optional[float]) -> Optional[int]:
    return None if a is None or b is None else int(round((b - a) * 1000))


def percentile(xs: List[float], p: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarize(turns: List[dict]) -> Dict[str, dict]:
    out = {}
    for f in FIELDS:
        vals = [t[f] for t in turns if t.get(f) is not None]
        out[f] = {"n": len(vals), "p50": percentile(vals, 50), "p90": percentile(vals, 90)}
    return out


class LatencyObserver(BaseObserver):
    def __init__(self, *, vad_stop_secs: float = 0.2, notify: Optional[Callable[[dict], Awaitable[None]]] = None,
                 clock=time.monotonic, **kwargs):
        super().__init__(**kwargs)
        self.vad_stop_secs = vad_stop_secs
        self.notify = notify
        self.clock = clock
        self.turns: List[dict] = []
        self._cur: Optional[dict] = None   # {"start", "turn_end", "speech_end", "ev": [(t, kind)]}
        self._in_turn = False
        self._last_stop: Optional[float] = None
        self._seen: set = set()          # 最近见过的 Frame.id
        self._seen_order: deque = deque()

    @staticmethod
    def _first(ev, kind, after):
        return next((t for t, k in ev if k == kind and t >= after), None)

    async def _finish(self) -> None:
        c, self._cur = self._cur, None
        if not c or c.get("turn_end") is None:
            return
        se, ev = c["speech_end"], c["ev"]
        first = {k: self._first(ev, k, se) for k in ("asr", "llm_start", "llm_first", "tts_start", "tts_first", "bot")}
        bot = min([x for x in (first["bot"], first["tts_first"]) if x is not None], default=None)
        row = {"asr": _ms(se, first["asr"]), "turn_ms": _ms(se, c["turn_end"]),
               "llm_ttft": _ms(first["llm_start"], first["llm_first"]),
               "agg": _ms(first["llm_first"], first["tts_start"]) if first["llm_first"] else None,
               "tts_ttfb": _ms(first["tts_start"], first["tts_first"]),
               "e2e_reply": _ms(se, first["tts_first"]), "e2e_any": _ms(se, bot)}
        if row["e2e_reply"] is None and row["e2e_any"] is None:
            return  # 回合没有得到任何回复（例如被下一句话合并、打断）
        self.turns.append(row)
        logger.info(f"latency turn {len(self.turns)}: {row}")
        if self.notify is not None:
            await self.notify({"type": "latency", "turn": len(self.turns), **row})

    async def on_push_frame(self, data: FramePushed):
        f = data.frame
        if not isinstance(f, _TRACKED):
            return
        fid = getattr(f, "id", None)
        if fid is None:
            fid = ("py", id(f))
        if fid in self._seen:
            return
        self._seen.add(fid)
        self._seen_order.append(fid)
        if len(self._seen_order) > _SEEN_MAX:
            self._seen.discard(self._seen_order.popleft())
        t = self.clock()
        if isinstance(f, VADUserStoppedSpeakingFrame):
            self._last_stop = t - (getattr(f, "stop_secs", None) or self.vad_stop_secs)
        elif isinstance(f, UserStartedSpeakingFrame):
            # 广播帧上下游各一份：已在回合内则忽略
            if not self._in_turn:
                self._in_turn = True
                await self._finish()
                self._cur = {"start": t, "ev": []}
        elif isinstance(f, UserStoppedSpeakingFrame):
            if self._in_turn and self._cur is not None:
                self._in_turn = False
                c = self._cur
                c["turn_end"] = t
                ok = self._last_stop is not None and c["start"] - 1.0 <= self._last_stop <= t
                c["speech_end"] = self._last_stop if ok else t
        elif self._cur is not None:
            kind = next((v for k, v in _STAGES if isinstance(f, k)), None)
            if kind:
                c = self._cur
                c["ev"].append((t, kind))
                # 用户已说完、回复首包到达：各字段都已确定，立即结算上报（不再等下一回合 / 挂断）
                if kind == "tts_first" and not self._in_turn and c.get("turn_end") is not None \
                        and t >= c["speech_end"]:
                    await self._finish()

    async def flush(self) -> None:
        await self._finish()


_SEEN_MAX = 4096
_TRACKED = (VADUserStoppedSpeakingFrame, TranscriptionFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
            LLMFullResponseStartFrame, LLMTextFrame, TTSStartedFrame, TTSAudioRawFrame, BotStartedSpeakingFrame)
_STAGES = ((TranscriptionFrame, "asr"), (LLMFullResponseStartFrame, "llm_start"), (LLMTextFrame, "llm_first"),
           (TTSStartedFrame, "tts_start"), (TTSAudioRawFrame, "tts_first"), (BotStartedSpeakingFrame, "bot"))
