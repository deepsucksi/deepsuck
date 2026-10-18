"""回合判定：念数字多等、完整句不等 Smart Turn 3s 兜底。用假的 turn analyzer，全部离线。"""
import asyncio
import time

import pytest
from pipecat.audio.turn.base_turn_analyzer import BaseTurnAnalyzer, BaseTurnParams, EndOfTurnState
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from voice.interrupt import ChineseMinCharsUserTurnStartStrategy, digits_enabled, user_turn_strategies
from voice.turndigits import DigitAwareTurnStopStrategy, digit_state, looks_complete


# ---------------- 文本规则 ----------------

@pytest.mark.parametrize("text,want", [
    ("卡号是6222 0212。", "pending"),
    ("你记一下，卡号是六二二二零二一二", "pending"),
    ("卡号是6222021234567890123。", None),
    ("你记一下。 卡号是62220212。 345678。", "pending"),        # 跨停顿累计 14 位
    ("你记一下。 卡号是62220212。 345678。 90123。", None),   # 19 位念完
    ("我的手机号是一三八。", "pending"),
    ("手机号幺三八零零幺三八八八八。", None),
    ("验证码是四七", "pending"),
    ("验证码是472915。", None),
    ("保证金先转三", "pending"),
    ("金额是三万元。", None),
    ("6222 0212 3456", "pending"),
    ("号码13800138888", None),
    ("收款户名写张三就行，卡号我现在念给您。", "expect"),
    ("我把卡号发给您", "expect"),
    ("您用的是哪个银行的卡？", None),
    ("理赔款要打到您的银行卡上。", None),
    ("您先往我们的安全账户转一笔保证金，到账后马上退给您。", None),
    ("我今年六十五。", None),
    ("我有两张卡", None),
    ("", None),
])
def test_digit_state(text, want):
    assert digit_state(text) == want


@pytest.mark.parametrize("text,want", [
    ("喂，您好，我是淘宝客服。", True),
    ("收款户名写张三就行。", True),
    ("然后那个。", False),
    ("我们这边就是", False),
    ("卡号是6222 0212。", False),
    ("好的。", False),           # 太短
    ("卡号我现在念给您。", False),  # 预告要念数字，另按 digit_hold 处理
])
def test_looks_complete(text, want):
    assert looks_complete(text) is want


# ---------------- 策略（假 analyzer）----------------

class FakeAnalyzer(BaseTurnAnalyzer):
    def __init__(self, state=EndOfTurnState.COMPLETE):
        super().__init__()
        self.state = state

    @property
    def speech_triggered(self) -> bool:
        return False

    @property
    def params(self):
        return BaseTurnParams()

    def append_audio(self, buffer, is_speech):
        return EndOfTurnState.INCOMPLETE  # 不模拟 3s 兜底：测试窗口内永远不会因静音结束

    async def analyze_end_of_turn(self):
        return self.state, None

    def clear(self):
        pass


class Rec(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.ev = []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, (UserStartedSpeakingFrame, UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            self.ev.append((time.monotonic(), type(frame).__name__))
        await self.push_frame(frame, direction)


def _final(t):
    return TranscriptionFrame(t, "u", "t", finalized=True)


def _speak(final, *, interim=None):
    return [VADUserStartedSpeakingFrame(start_secs=0.0), InterimTranscriptionFrame(interim or final, "u", "t"),
            SleepFrame(0.02), _final(final), SleepFrame(0.02), VADUserStoppedSpeakingFrame(stop_secs=0.0)]


def _run(frames, state=EndOfTurnState.COMPLETE, hold=0.4, early=0.25):
    stop = DigitAwareTurnStopStrategy(turn_analyzer=FakeAnalyzer(state), digit_hold_secs=hold,
                                      text_complete_secs=early)
    p = UserTurnProcessor(user_turn_strategies=UserTurnStrategies(
        start=[ChineseMinCharsUserTurnStartStrategy(min_chars=2)], stop=[stop]))
    rec = Rec()
    asyncio.run(run_test(Pipeline([p, rec]), frames_to_send=frames))
    vad_stops = [t for t, k in rec.ev if k == "VADUserStoppedSpeakingFrame"]
    stops = [t for t, k in rec.ev if k == "UserStoppedSpeakingFrame"]
    return stop, vad_stops, stops


def test_normal_complete_sentence_not_delayed():
    _, vad, stops = _run(_speak("喂，您好，我是淘宝客服。") + [SleepFrame(0.6)])
    assert len(stops) == 1 and stops[0] - vad[-1] < 0.12


def test_digits_pending_holds_turn_then_ends():
    st, vad, stops = _run(_speak("卡号是6222 0212。") + [SleepFrame(0.8)])
    assert len(stops) == 1 and 0.33 <= stops[0] - vad[-1] < 0.6 and st.held == 1


def test_digits_resume_within_hold_stays_one_turn():
    frames = (_speak("卡号是6222 0212。") + [SleepFrame(0.2)]
              + _speak("3456 7890 1234 5678。") + [SleepFrame(0.7)])
    st, vad, stops = _run(frames)
    assert len(stops) == 1 and stops[0] > vad[-1]
    assert stops[0] - vad[-1] < 0.12  # 念完 24 位，不再多等


def test_without_strategy_digits_get_split():
    """对照：Pipecat 默认策略（同一个假 analyzer）在念卡号中途停顿时就结束回合。"""
    from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
    p = UserTurnProcessor(user_turn_strategies=UserTurnStrategies(
        start=[ChineseMinCharsUserTurnStartStrategy(min_chars=2)],
        stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=FakeAnalyzer())]))
    rec = Rec()
    frames = (_speak("卡号是6222 0212。") + [SleepFrame(0.2)] + _speak("3456 7890 1234 5678。") + [SleepFrame(0.3)])
    asyncio.run(run_test(Pipeline([p, rec]), frames_to_send=frames))
    assert sum(1 for _, k in rec.ev if k == "UserStoppedSpeakingFrame") == 2


def test_incomplete_but_complete_text_ends_early():
    st, vad, stops = _run(_speak("收款户名写张三就行。") + [SleepFrame(0.6)], state=EndOfTurnState.INCOMPLETE)
    assert len(stops) == 1 and 0.2 <= stops[0] - vad[-1] < 0.4 and st.early == 1


def test_incomplete_announce_digits_waits_hold():
    _, vad, stops = _run(_speak("收款户名写张三就行，卡号我现在念给您。") + [SleepFrame(0.8)],
                         state=EndOfTurnState.INCOMPLETE)
    assert len(stops) == 1 and 0.35 <= stops[0] - vad[-1] < 0.6


def test_incomplete_pending_digits_and_hesitation_keep_waiting():
    for text in ("卡号是6222 0212。", "然后那个。"):
        _, _, stops = _run(_speak(text) + [SleepFrame(0.9)], state=EndOfTurnState.INCOMPLETE)
        assert stops == []  # 交给 Smart Turn 原来的 3s 兜底（假 analyzer 不模拟）


def test_late_final_transcript_after_early_timer():
    frames = [VADUserStartedSpeakingFrame(start_secs=0.0), InterimTranscriptionFrame("收款户名写张三", "u", "t"),
              SleepFrame(0.02), VADUserStoppedSpeakingFrame(stop_secs=0.0), SleepFrame(0.45),
              _final("收款户名写张三就行。"), SleepFrame(0.3)]
    _, vad, stops = _run(frames, state=EndOfTurnState.INCOMPLETE)
    assert len(stops) == 1 and 0.45 <= stops[0] - vad[-1] < 0.6


def test_resume_cancels_early_and_hold():
    frames = (_speak("收款户名写张三就行。") + [SleepFrame(0.1)]
              + [VADUserStartedSpeakingFrame(start_secs=0.0), SleepFrame(0.5)])
    _, _, stops = _run(frames, state=EndOfTurnState.INCOMPLETE)
    assert stops == []  # 又开口了，还没停：不结束


def test_early_disabled_keeps_default():
    _, _, stops = _run(_speak("收款户名写张三就行。") + [SleepFrame(0.6)], state=EndOfTurnState.INCOMPLETE,
                       early=0.0, hold=0.0)
    assert stops == []


# ---------------- 接线 ----------------

def test_user_turn_strategies_switch(monkeypatch):
    monkeypatch.delenv("DEEPSUCK_TURN_DIGITS", raising=False)
    st = user_turn_strategies(2, digit_hold_ms=1400, text_complete_ms=900)
    assert isinstance(st.stop[0], DigitAwareTurnStopStrategy)
    assert (st.stop[0].digit_hold_secs, st.stop[0].text_complete_secs) == (1.4, 0.9)
    monkeypatch.setenv("DEEPSUCK_TURN_DIGITS", "0")
    st = user_turn_strategies(2)
    assert not any(isinstance(s, DigitAwareTurnStopStrategy) for s in st.stop)
    assert digits_enabled({}) and not digits_enabled({"DEEPSUCK_TURN_DIGITS": "off"})


@pytest.mark.parametrize("profile", ["web", "phone"])
def test_build_pipeline_uses_digit_strategy_both_profiles(monkeypatch, profile):
    from voice.app import build_pipeline
    from voice.tests.test_latency import _FakeLLM, _session, _Transport
    from voice.tuning import get_profile
    monkeypatch.delenv("DEEPSUCK_TURN_DIGITS", raising=False)

    async def go():
        return build_pipeline(_Transport(), _session(), None, engine="llm", fillers={}, llm=_FakeLLM(),
                              profile=profile)
    pl, _, _ = asyncio.run(go())
    agg = next(p for p in pl.processors if type(p).__name__ == "LLMUserAggregator")
    stop = agg._params.user_turn_strategies.stop[0]
    assert isinstance(stop, DigitAwareTurnStopStrategy)
    assert stop.digit_hold_secs == get_profile(profile).turn_digit_hold_ms / 1000


def test_profile_turn_env():
    from voice.tuning import get_profile
    p = get_profile("web", {"DEEPSUCK_LAT_TURN_DIGIT_HOLD_MS": "1300", "DEEPSUCK_LAT_TURN_TEXT_COMPLETE_MS": "0"})
    assert (p.turn_digit_hold_ms, p.turn_text_complete_ms) == (1300, 0)


def test_backchannel_skips_while_reading_digits():
    from voice.backchannel import skip_reason
    assert skip_reason("你记一下，卡号是六二二二零二一二") == "digits"
    assert skip_reason("收款户名写张三就行，卡号我现在念给您。") == "digits"
    assert skip_reason("卡号是6222021234567890123。") is None
