"""回合判定：念数字时多等一会，完整句不必等 Smart Turn 的 3 秒兜底。

现状（Pipecat 1.12 默认的 TurnAnalyzerUserTurnStopStrategy + LocalSmartTurnAnalyzerV3）：
  Silero VAD 静音 stop_secs（网页 0.2s / 电话 0.3s）→ VADUserStoppedSpeakingFrame → Smart Turn v3 对这段音频打分：
  - COMPLETE：等到最终转写（我们的 Paraformer 输出 finalized=True，句末静音 450/500ms 后出）就结束回合；
  - INCOMPLETE：继续听，静音累计到 SmartTurnParams.stop_secs（默认 3s）才强制结束 —— 这就是
    "卡号我现在念给您。" 每次约 3.2s 的来源（Smart Turn 判它没说完，3s 兜底 + VAD 0.2s）。
  于是念卡号时 "6222 0212……（停 0.8s）3456" 中间一停，Smart Turn 判 COMPLETE、Paraformer 出了最终结果，回合就被切开。

DigitAwareTurnStopStrategy（继承上面的默认策略，只加两条基于本回合转写的规则）：
  1. 正在念数字（digit_state 为 pending / expect）：即使 Smart Turn 判 COMPLETE，也要等真实停说后
     digit_hold_secs（默认 1.8s）仍没再开口才结束回合；对方接着念（VAD 再次开口）就继续同一回合。
     Smart Turn 判 INCOMPLETE 时：pending 保持原来的 3s 兜底；expect（"卡号我现在念给您"，还没开始念）
     等 digit_hold_secs 就结束。
  2. Smart Turn 判 INCOMPLETE、但最终转写已是完整句（句末标点、不以"那个/然后/就是"等收尾、不在念数字）：
     停说后 text_complete_secs（默认 1.2s）结束回合，不再等 3s。设 0 关闭这条。
  其余情况与 Pipecat 默认完全一样，平时（COMPLETE、不在念数字）的阈值不变。
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Optional

# ---------------- 文本规则 ----------------

_DIG = "0-9０-９零〇一二三四五六七八九幺两"
# 数字之间允许的分隔：空格、横线、逗号顿号，以及 Paraformer 在念数字停顿处加的句号（"62220212。 345678"）
_RUN = re.compile(rf"[{_DIG}](?:[\s\-—,，、.·。]{{0,3}}[{_DIG}])*")
_TAIL_PUNCT = r"[\s。，,.!！？?…~～]*$"
_TAIL_RUN = re.compile(rf"({_RUN.pattern}){_TAIL_PUNCT}")
_DIGIT_CHAR = re.compile(rf"[{_DIG}]")

# 引导词 → 完整时至少多少位；None 表示金额（看有没有单位）
LEADS = (
    (re.compile(r"卡号|银行卡|账号|帐号|账户|帐户|户号"), 16),
    (re.compile(r"手机号?|电话|号码|联系方式"), 11),
    (re.compile(r"验证码|校验码|动态码|密码"), 6),
    (re.compile(r"金额|转账|汇款|打款|保证金|转|汇|打"), None),
)
_ANNOUNCE = re.compile(r"念|报|读|说给|告诉|发给|记一下|记下|记好")
_HESITATE = re.compile(r"(那个|这个|就是|然后|还有|而且|但是|所以|因为|如果|的话|嗯|呃|额|啊)[。，,.!！？?…\s]*$")
_SENT_END = re.compile(r"[。！？!?][\s]*$")
_CONTENT = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
LOOKBACK = 14  # 引导词须在数字串前这么多字以内


def _ndigits(s: str) -> int:
    return len(_DIGIT_CHAR.findall(s))


def digit_state(text: str) -> Optional[str]:
    """看本回合（目前为止）的转写，判断对方是不是在念数字：
    - "pending"：结尾是一串没念完的数字（卡号不足 16 位、手机号不足 11 位、验证码不足 6 位、金额还没说单位；
       无引导词时 3–10 位或 12–15 位的数字串）；
    - "expect"：提到卡号/手机号/验证码并说要念/报给你，但还没开始念；
    - None：不在念数字。"""
    t = (text or "").strip()
    if not t:
        return None
    m = _TAIL_RUN.search(t)
    if m:
        run = m.group(1)
        n = _ndigits(run)
        before = t[max(0, m.start(1) - LOOKBACK):m.start(1)]
        for pat, need in LEADS:
            hit = None
            for h in pat.finditer(before):
                hit = h
            if hit is None:
                continue
            if need is None:  # 金额：数字后面还没跟单位
                return "pending"
            return "pending" if n < need else None
        if n >= 3 and n != 11 and n < 16:
            return "pending"
        return None
    # 还没开始念："卡号我现在念给您。"
    last = re.split(r"[。！？!?]", t.rstrip("。！？!? \n"))[-1]
    for pat, need in LEADS[:3]:
        h = None
        for h in pat.finditer(last):
            pass
        if h is not None and _ANNOUNCE.search(last[h.start():]) and not _DIGIT_CHAR.search(last[h.end():]):
            return "expect"
    return None


def looks_complete(text: str) -> bool:
    """最终转写看起来是完整的一句话：句末标点、最后一句至少 4 个有效字、不以犹豫词收尾、不在念数字。"""
    t = (text or "").strip()
    if not t or not _SENT_END.search(t) or _HESITATE.search(t) or digit_state(t):
        return False
    last = re.split(r"[。！？!?]", t.rstrip("。！？!? \n"))[-1]
    return len(_CONTENT.findall(last)) >= 4


# ---------------- 回合结束策略 ----------------

def _base():
    from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
    return TurnAnalyzerUserTurnStopStrategy


class DigitAwareTurnStopStrategy(_base()):
    """见模块说明。clock 可注入（测试用），须与 VAD 帧 timestamp 同一时基（time.time）。"""

    def __init__(self, *, turn_analyzer, digit_hold_secs: float = 1.8, text_complete_secs: float = 1.2,
                 clock=time.time, **kwargs):
        super().__init__(turn_analyzer=turn_analyzer, **kwargs)
        self.digit_hold_secs = max(0.0, float(digit_hold_secs))
        self.text_complete_secs = max(0.0, float(text_complete_secs))
        self.clock = clock
        self._finals: list = []
        self._interim = ""
        self._speech_end: Optional[float] = None
        self._hold_task: Optional[asyncio.Task] = None
        self._early_task: Optional[asyncio.Task] = None
        self._early_due = False
        self.held = 0          # 因念数字推迟结束的次数
        self.early = 0         # 因完整句提前结束（不等 3s）的次数

    # ---- 本回合文本 ----
    @property
    def turn_text(self) -> str:
        return "".join(self._finals) + self._interim

    def digit_state(self) -> Optional[str]:
        return digit_state(self.turn_text)

    async def process_frame(self, frame):
        from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame

        if isinstance(frame, TranscriptionFrame):
            self._finals.append(frame.text or "")
            self._interim = ""
        elif isinstance(frame, InterimTranscriptionFrame):
            self._interim = frame.text or ""
        result = await super().process_frame(frame)
        if isinstance(frame, TranscriptionFrame) and self._early_due:
            await self._try_early()
        return result

    # ---- 状态 ----
    async def _cancel(self, name: str):
        t = getattr(self, name)
        if t is not None:
            setattr(self, name, None)
            if t is not asyncio.current_task():
                await self.task_manager.cancel_task(t)

    async def _reset(self):
        self._finals, self._interim, self._speech_end = [], "", None
        await super()._reset()

    async def _discard_pending_end_of_turn(self):
        self._early_due = False
        await self._cancel("_hold_task")
        await self._cancel("_early_task")
        await super()._discard_pending_end_of_turn()

    def _since_speech_end(self) -> float:
        return 0.0 if self._speech_end is None else max(0.0, self.clock() - self._speech_end)

    async def _handle_vad_user_stopped_speaking(self, frame):
        self._speech_end = self.clock() - (frame.stop_secs or 0.0)
        await super()._handle_vad_user_stopped_speaking(frame)
        # Smart Turn 判没说完：安排一次"按文本判断"的检查（完整句 / 预告要念数字时不等 3s 兜底）
        if not self._turn_complete:
            wait = self._early_wait()
            if wait is not None:
                await self._cancel("_early_task")
                self._early_task = self.task_manager.create_task(
                    self._early_after(max(0.0, wait - self._since_speech_end())), f"{self}::_early")

    def _early_wait(self) -> Optional[float]:
        cands = [x for x in (self.text_complete_secs, self.digit_hold_secs) if x > 0]
        return min(cands) if cands else None

    async def _early_after(self, wait: float):
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        self._early_task = None
        self._early_due = True
        await self._try_early()

    async def _try_early(self):
        """到点了（或到点后最终转写才来）：按文本决定是否不等 3s 兜底。"""
        if self._turn_complete or self._vad_user_speaking or not self._early_due:
            return
        text = self.turn_text
        st = digit_state(text)
        if st == "pending":
            return  # 正在念数字：保持 Smart Turn 原来的兜底
        need = self.digit_hold_secs if st == "expect" else self.text_complete_secs
        if st is None and not (self.text_complete_secs > 0 and looks_complete(text)):
            return
        if st == "expect" and self.digit_hold_secs <= 0:
            return
        left = need - self._since_speech_end()
        if left > 0.005:
            await self._cancel("_early_task")
            self._early_due = False
            self._early_task = self.task_manager.create_task(self._early_after(left), f"{self}::_early")
            return
        self._early_due = False
        self.early += 1
        self._turn_complete = True
        await self._maybe_trigger_user_turn_stopped()

    async def _maybe_trigger_user_turn_stopped(self):
        if self._turn_complete and self.digit_hold_secs > 0 and not self._vad_user_speaking \
                and self._speech_end is not None and self.digit_state():
            left = self.digit_hold_secs - self._since_speech_end()
            if left > 0.005:
                if self._hold_task is None:
                    self.held += 1
                    self._hold_task = self.task_manager.create_task(self._hold_after(left), f"{self}::_hold")
                return
        await super()._maybe_trigger_user_turn_stopped()

    async def _hold_after(self, wait: float):
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        self._hold_task = None
        await self._maybe_trigger_user_turn_stopped()

    async def cleanup(self):
        await self._cancel("_hold_task")
        await self._cancel("_early_task")
        await super().cleanup()
