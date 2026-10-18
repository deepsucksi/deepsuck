"""延迟优化相关测试：参数、ASR 断句静音、流式 CosyVoice、按延迟触发的填充音、中文打断策略、延迟观测。全部离线。"""
import asyncio
import json

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.types import ProcessFrameResult

from voice import dashscope_ws as ds
from voice.interrupt import ChineseMinCharsUserTurnStartStrategy, meaningful_chars, user_turn_strategies
from voice.latency import LatencyObserver, percentile, summarize
from voice.processors import FillerProcessor
from voice.services import CosyVoiceStreamTTSService, ParaformerSTTService
from voice.textagg import ClauseTextAggregator
from voice.tuning import PHONE, WEB, get_profile, vad_params


# ---------------- 参数 ----------------

def test_profiles_defaults_and_env_override():
    w, p = get_profile("web", env={}), get_profile("phone", env={})
    assert (w.vad_start_secs, w.vad_confidence) == (0.3, 0.75)
    assert 400 <= w.asr_max_silence_ms <= 500 and 600 <= w.filler_delay_ms <= 700
    assert p != w and p.interrupt_min_chars >= w.interrupt_min_chars and p.vad_confidence >= w.vad_confidence
    env = {"DEEPSUCK_LAT_FILLER_DELAY_MS": "700", "DEEPSUCK_LAT_VAD_CONFIDENCE": "0.8",
           "DEEPSUCK_PHONE_LAT_ASR_MAX_SILENCE_MS": "550", "DEEPSUCK_LAT_INTERRUPT_MIN_CHARS": "bad"}
    w2, p2 = get_profile("web", env=env), get_profile("phone", env=env)
    assert w2.filler_delay_ms == 700 and w2.vad_confidence == 0.8
    assert w2.interrupt_min_chars == WEB.interrupt_min_chars  # 无法解析的值忽略
    assert p2.asr_max_silence_ms == 550 and p2.filler_delay_ms == PHONE.filler_delay_ms
    with pytest.raises(ValueError):
        get_profile("pstn")
    vp = vad_params(w)
    assert (vp.confidence, vp.start_secs, vp.stop_secs) == (0.75, 0.3, 0.2)


# ---------------- ASR 断句静音 ----------------

def test_run_task_asr_sentence_silence():
    p = ds.run_task_asr("t", "paraformer-realtime-v2", 16000)["payload"]["parameters"]
    assert "max_sentence_silence" not in p
    p = ds.run_task_asr("t", "paraformer-realtime-v2", 16000, max_sentence_silence=450)["payload"]["parameters"]
    assert p["max_sentence_silence"] == 450
    assert ds.clamp_sentence_silence(50) == 200 and ds.clamp_sentence_silence(99999) == 6000


def test_paraformer_service_sends_sentence_silence(fake_ws):
    connect = fake_ws(mode="asr", asr_text="我是客服")
    stt = ParaformerSTTService(connect=connect, max_sentence_silence=450)
    audio = InputAudioRawFrame(audio=b"\x00\x00" * 1600, sample_rate=16000, num_channels=1)
    asyncio.run(run_test(stt, frames_to_send=[audio, SleepFrame(0.1)]))
    run = connect.made[0].sent_json()[0]
    assert run["header"]["action"] == "run-task"
    assert run["payload"]["parameters"]["max_sentence_silence"] == 450


# ---------------- 分句器 ----------------

def _agg(text_chunks, n=6):
    a = ClauseTextAggregator(min_clause_chars=n)

    async def go():
        out = []
        for c in text_chunks:
            async for x in a.aggregate(c):
                out.append(x.text)
        tail = await a.flush()
        return out, tail.text if tail else None
    return asyncio.run(go())


def test_clause_aggregator_splits_early():
    out, tail = _agg(["哎哟", "，小伙子你", "是哪个单位的啊，", "我耳朵不好。你", "再说一遍"])
    # “哎哟，”太短不切；第二个逗号处够字数就切；句号立即切
    assert out == ["哎哟，小伙子你是哪个单位的啊，", "我耳朵不好。"]
    assert tail == "你再说一遍"


def test_clause_aggregator_keeps_brackets_whole():
    out, tail = _agg(["（咳嗽一声，", "慢慢地说，好半天）你说啥，我没听清楚呢，再说"])
    assert out[0].startswith("（咳嗽一声，慢慢地说，好半天）")
    assert all("（" not in o or "）" in o for o in out)
    assert tail == "再说"


def test_clause_aggregator_interruption_clears():
    a = ClauseTextAggregator()

    async def go():
        async for _ in a.aggregate("半句话没说完"):
            pass
        await a.handle_interruption()
        return await a.flush()
    assert asyncio.run(go()) is None


# ---------------- 流式 CosyVoice ----------------

class StreamWS:
    """双向流式的假 CosyVoice：continue-task 立刻回一包 PCM；finish-task 后 task-finished。
    hold=True 时不回 task-finished（模拟仍在合成）。一条连接上可以先后跑多个任务。"""

    def __init__(self, hold=False, fail=False):
        self.hold, self.fail = hold, fail
        self.sent, self.closed = [], False
        self.q: asyncio.Queue = asyncio.Queue()
        self.task_id = None

    def _ev(self, event):
        return json.dumps({"header": {"event": event, "task_id": self.task_id, "error_message": "boom"}, "payload": {}})

    async def send(self, msg):
        self.sent.append(msg)
        d = json.loads(msg)
        action = d["header"]["action"]
        self.task_id = d["header"]["task_id"]
        if action == "run-task":
            await self.q.put(self._ev("task-failed" if self.fail else "task-started"))
        elif action == "continue-task":
            await self.q.put(b"\x05\x00" * 2400)  # 50ms @24k
        elif action == "finish-task" and not self.hold:
            await self.q.put(self._ev("task-finished"))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        m = await self.q.get()
        if m is None:
            raise StopAsyncIteration
        return m

    async def close(self):
        self.closed = True
        await self.q.put(None)

    def actions(self):
        return [json.loads(m)["header"]["action"] for m in self.sent]


def _stream_connect(**kw):
    made = []

    async def connect(key, url=None):
        ws = StreamWS(**kw)
        made.append(ws)
        return ws
    connect.made = made
    return connect


def test_stream_tts_reuses_one_connection():
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    down, _ = asyncio.run(run_test(tts, frames_to_send=[TTSSpeakFrame("哎哟，小伙子。"), SleepFrame(0.2),
                                                        TTSSpeakFrame("你再说一遍。"), SleepFrame(0.3)]))
    assert tts.connects == 1 and len(connect.made) == 1
    assert connect.made[0].actions().count("run-task") == 2  # 每回合一个任务，复用同一连接
    assert sum(isinstance(f, TTSAudioRawFrame) for f in down) >= 2
    assert sum(isinstance(f, TTSStoppedFrame) for f in down) >= 2


def test_stream_tts_streams_llm_clauses_into_one_task():
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000, clause_min_chars=4)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("哎哟小伙子啊，"), LLMTextFrame("你是哪个单位的"),
              LLMTextFrame("？我耳朵不好。"), LLMFullResponseEndFrame(), SleepFrame(0.3)]
    down, _ = asyncio.run(run_test(tts, frames_to_send=frames))
    acts = connect.made[0].actions()
    assert acts[0] == "run-task"  # 回合开始就开任务，不等首个分句
    assert acts.count("run-task") == 1 and acts.count("continue-task") >= 2 and acts[-1] == "finish-task"
    texts = [json.loads(m)["payload"]["input"]["text"] for m in connect.made[0].sent
             if json.loads(m)["header"]["action"] == "continue-task"]
    assert texts[0] == "哎哟小伙子啊，"
    assert any(isinstance(f, TTSAudioRawFrame) for f in down)


def test_stream_tts_interruption_cancels_and_reconnects():
    connect = _stream_connect(hold=True)
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("这句话很长很长很长。"), SleepFrame(0.2),
              InterruptionFrame(), SleepFrame(0.2)]
    asyncio.run(run_test(tts, frames_to_send=frames))
    assert connect.made[0].closed            # 还在合成的连接被断开（取消服务端合成）
    assert len(connect.made) >= 2 and tts.connects >= 2


def test_stream_tts_interruption_after_synthesis_keeps_connection():
    connect = _stream_connect()
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    frames = [TTSSpeakFrame("说完了。"), SleepFrame(0.3), InterruptionFrame(), SleepFrame(0.1)]
    asyncio.run(run_test(tts, frames_to_send=frames))
    # 已合成完、只剩本地播放：不必断连
    assert tts.connects == 1 and connect.made[0].actions().count("run-task") == 1


def test_stream_tts_task_failure_reports_error():
    connect = _stream_connect(fail=True)
    tts = CosyVoiceStreamTTSService(connect=connect, sample_rate=24000)
    down, up = asyncio.run(run_test(tts, frames_to_send=[TTSSpeakFrame("你好。"), SleepFrame(0.3)]))
    assert any(isinstance(f, ErrorFrame) for f in list(down) + list(up))


# ---------------- 按延迟触发的填充音 ----------------

FILL = {"嗯……": b"\x01\x00" * 800, "哎，等等啊": b"\x02\x00" * 800}


def _fillers_out(frames, delay_ms=80, fillers=FILL):
    fp = FillerProcessor(dict(fillers), sample_rate=24000, delay_ms=delay_ms)
    down, _ = asyncio.run(run_test(fp, frames_to_send=frames))
    return fp, [f for f in down if type(f) is OutputAudioRawFrame]


def test_filler_plays_when_llm_is_slow():
    fp, out = _fillers_out([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.02),
                            UserStoppedSpeakingFrame(), SleepFrame(0.2)])
    assert len(out) == 1 and fp.played == 1 and out[0].sample_rate == 24000


def test_filler_cancelled_by_first_token():
    fp, out = _fillers_out([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0),
                            SleepFrame(0.02), LLMTextFrame("哎"), SleepFrame(0.2)], delay_ms=150)
    assert out == [] and fp.played == 0 and fp.cancelled == 1


def test_filler_cancelled_when_user_resumes_and_once_per_turn():
    fp, out = _fillers_out([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0),
                            SleepFrame(0.02), VADUserStartedSpeakingFrame(), SleepFrame(0.2)], delay_ms=100)
    assert out == []
    fp, out = _fillers_out([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0),
                            UserStoppedSpeakingFrame(), SleepFrame(0.15),
                            VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame(), SleepFrame(0.15)],
                           delay_ms=50)
    assert len(out) == 1  # 一个用户回合最多一次


def test_filler_waits_for_turn_end_on_mid_sentence_pause():
    # 句中停顿：计时到了但回合没结束，不插嘴；对方接着说就作废
    _, out = _fillers_out([UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0), SleepFrame(0.12),
                           VADUserStartedSpeakingFrame(), SleepFrame(0.1)], delay_ms=50)
    assert out == []
    # 计时到了先挂起，回合判定结束时立刻播（不再额外等待）
    fp = FillerProcessor(dict(FILL), delay_ms=50)

    async def go():
        down, _ = await run_test(fp, frames_to_send=[UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.0),
                                                     SleepFrame(0.12), UserStoppedSpeakingFrame(), SleepFrame(0.01)])
        return [f for f in down if type(f) is OutputAudioRawFrame]
    assert len(asyncio.run(go())) == 1 and fp.played == 1


def test_filler_needs_user_turn_and_respects_disable_and_bot_speaking():
    end = [VADUserStoppedSpeakingFrame(stop_secs=0.0), UserStoppedSpeakingFrame(), SleepFrame(0.15)]
    _, out = _fillers_out(list(end), delay_ms=50)
    assert out == []  # 没有开启用户回合（噪声），不插
    _, out = _fillers_out([UserStartedSpeakingFrame()] + end, delay_ms=0)
    assert out == []
    _, out = _fillers_out([BotStartedSpeakingFrame(), UserStartedSpeakingFrame()] + end, delay_ms=50)
    assert out == []
    _, out = _fillers_out([UserStartedSpeakingFrame()] + end, delay_ms=30, fillers={})
    assert out == []


def test_filler_delay_counts_from_real_speech_end():
    # stop_secs=0.2 已经过去，delay=150ms 应在回合结束时立即触发（不再等 150ms）
    fp = FillerProcessor(dict(FILL), delay_ms=150)

    async def go():
        down, _ = await run_test(fp, frames_to_send=[UserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(stop_secs=0.2),
                                                     UserStoppedSpeakingFrame(), SleepFrame(0.05)])
        return [f for f in down if type(f) is OutputAudioRawFrame]
    assert len(asyncio.run(go())) == 1


def test_filler_rotates():
    fp = FillerProcessor(dict(FILL))
    assert fp._pick() != fp._pick()


# ---------------- 中文打断策略 ----------------

def test_meaningful_chars():
    assert meaningful_chars("嗯") == 0 and meaningful_chars("对对对，好的") == 0 and meaningful_chars("喂？") == 0
    assert meaningful_chars("等一下") == 3 and meaningful_chars("不是") == 2 and meaningful_chars("OK") == 1


def _strategy_run(frames, min_chars=2):
    s = ChineseMinCharsUserTurnStartStrategy(min_chars=min_chars)
    fired = []

    async def go():
        async def on_started(_s, params):
            fired.append(params)
        s.add_event_handler("on_user_turn_started", on_started)
        res = []
        for f in frames:
            res.append(await s.process_frame(f))
        await asyncio.sleep(0.05)
        return res
    return asyncio.run(go()), fired


def test_strategy_backchannel_does_not_interrupt_bot():
    res, fired = _strategy_run([BotStartedSpeakingFrame(), InterimTranscriptionFrame("嗯", "u", "t"),
                                TranscriptionFrame("对对。", "u", "t")])
    assert res[1:] == [ProcessFrameResult.CONTINUE, ProcessFrameResult.CONTINUE] and not fired
    res, fired = _strategy_run([BotStartedSpeakingFrame(), InterimTranscriptionFrame("你等一下", "u", "t")])
    assert res[-1] == ProcessFrameResult.STOP and fired


def test_strategy_any_text_when_bot_silent():
    res, fired = _strategy_run([BotStartedSpeakingFrame(), BotStoppedSpeakingFrame(),
                                TranscriptionFrame("嗯。", "u", "t")])
    assert res[-1] == ProcessFrameResult.STOP and fired
    res, fired = _strategy_run([TranscriptionFrame("。", "u", "t")])
    assert res[-1] == ProcessFrameResult.CONTINUE and not fired


def test_user_turn_strategies_uses_only_chinese_start():
    st = user_turn_strategies(3)
    assert len(st.start) == 1 and isinstance(st.start[0], ChineseMinCharsUserTurnStartStrategy)
    assert st.stop


def test_rule_mode_turn_processor_interrupts_only_on_real_words():
    from pipecat.turns.user_turn_processor import UserTurnProcessor

    def run(text):
        p = UserTurnProcessor(user_turn_strategies=user_turn_strategies(2))
        frames = [BotStartedSpeakingFrame(), InterimTranscriptionFrame(text, "u", "t"), SleepFrame(0.1)]
        down, up = asyncio.run(run_test(p, frames_to_send=frames))
        return [f for f in list(down) + list(up) if isinstance(f, InterruptionFrame)]
    assert run("嗯嗯") == []
    assert run("你等一下") != []


# ---------------- build_pipeline 接线 ----------------

class _Transport:
    def __init__(self):
        self._i, self._o = FrameProcessor(name="in"), FrameProcessor(name="out")

    def input(self):
        return self._i

    def output(self):
        return self._o


def _session():
    from deepsuck.engine import Session
    return Session("grandpa_wang", "police")


def _names(pipeline):
    return [type(p).__name__ for p in pipeline.processors]


class _FakeLLM(FrameProcessor):
    pass


def test_build_pipeline_llm_mode_profiles():
    from voice.app import build_pipeline

    async def go(profile):
        pl, intel, ctx = build_pipeline(_Transport(), _session(), None, engine="llm", fillers={}, llm=_FakeLLM(),
                                        profile=profile)
        return pl, intel
    pl, intel = asyncio.run(go("web"))
    names = _names(pl)
    assert names.index("_FakeLLM") < names.index("FillerProcessor") < names.index("CosyVoiceStreamTTSService")
    assert intel.filler_prob == 0.0
    stt = next(p for p in pl.processors if type(p).__name__ == "ParaformerSTTService")
    assert stt._max_silence == WEB.asr_max_silence_ms
    filler = next(p for p in pl.processors if isinstance(p, FillerProcessor))
    assert filler.delay_ms == WEB.filler_delay_ms
    pl, _ = asyncio.run(go("phone"))
    stt = next(p for p in pl.processors if type(p).__name__ == "ParaformerSTTService")
    assert stt._max_silence == PHONE.asr_max_silence_ms
    user_agg = next(p for p in pl.processors if type(p).__name__ == "LLMUserAggregator")
    vp = user_agg._params.vad_analyzer.params
    assert (vp.confidence, vp.stop_secs) == (PHONE.vad_confidence, PHONE.vad_stop_secs)


def test_build_pipeline_rule_mode_supports_interruption():
    from voice.app import build_pipeline

    async def go():
        return build_pipeline(_Transport(), _session(), None, engine="rule", fillers={})
    pl, intel, ctx = asyncio.run(go())
    names = _names(pl)
    assert names.index("VADProcessor") < names.index("ParaformerSTTService") < names.index("UserTurnProcessor") \
        < names.index("IntelProcessor")
    vad = next(p for p in pl.processors if type(p).__name__ == "VADProcessor")
    params = vad._vad_controller._vad_analyzer.params
    assert (params.start_secs, params.confidence, params.stop_secs) == (0.3, 0.75, 0.2)


def test_build_pipeline_legacy_tts_fallback(monkeypatch):
    from voice.app import build_pipeline
    monkeypatch.setenv("DEEPSUCK_TTS_STREAM", "0")

    async def go():
        return build_pipeline(_Transport(), _session(), None, engine="rule", fillers={})
    pl, _, _ = asyncio.run(go())
    assert "CosyVoiceTTSService" in _names(pl)


# ---------------- 延迟观测 ----------------

class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _push(obs, frame):
    asyncio.run(obs.on_push_frame(FramePushed(source=None, destination=None, frame=frame,
                                              direction=FrameDirection.DOWNSTREAM, timestamp=0)))


def _feed(obs, clk, seq):
    for t, f in seq:
        clk.t = 100 + t
        _push(obs, f)


AUDIO = lambda: TTSAudioRawFrame(b"\x00\x00", 24000, 1)  # noqa: E731


def test_latency_observer_turn_breakdown():
    clk = _Clock()
    obs = LatencyObserver(vad_stop_secs=0.2, clock=clk)
    _feed(obs, clk, [(1.5, UserStartedSpeakingFrame()), (3.2, VADUserStoppedSpeakingFrame(stop_secs=0.2)),
                     (3.6, TranscriptionFrame("你好", "u", "t")), (3.7, UserStoppedSpeakingFrame()),
                     (3.75, LLMFullResponseStartFrame()), (4.0, LLMTextFrame("哎")), (4.1, TTSStartedFrame()),
                     (4.5, BotStartedSpeakingFrame()), (4.6, AUDIO()), (8.0, UserStartedSpeakingFrame())])
    assert obs.turns == [{"asr": 600, "turn_ms": 700, "llm_ttft": 250, "agg": 100, "tts_ttfb": 500,
                          "e2e_reply": 1600, "e2e_any": 1500, "first_audible": 1500, "filler": 0}]


def test_latency_observer_mid_turn_pause_and_filler():
    clk = _Clock()
    obs = LatencyObserver(clock=clk)
    _feed(obs, clk, [(0.5, UserStartedSpeakingFrame()), (1.0, VADUserStoppedSpeakingFrame(stop_secs=0.2)),
                     (1.5, TranscriptionFrame("前半句", "u", "t")),
                     (1.6, BotStartedSpeakingFrame()),               # 句中停顿时的声音不算（后面还在说）
                     (2.0, VADUserStoppedSpeakingFrame(stop_secs=0.2)), (2.6, TranscriptionFrame("后半句", "u", "t")),
                     (2.65, BotStartedSpeakingFrame()),              # 填充音：停说之后、回合结束之前
                     (2.8, UserStoppedSpeakingFrame()), (3.0, LLMTextFrame("哎")), (4.0, AUDIO()),
                     (4.1, AUDIO())])
    asyncio.run(obs.flush())
    t = obs.turns[0]
    assert (t["asr"], t["turn_ms"], t["e2e_reply"], t["e2e_any"]) == (800, 1000, 2200, 850)


def test_latency_observer_ignores_audio_outside_turns_and_duplicate_broadcasts():
    clk = _Clock()
    obs = LatencyObserver(clock=clk)
    _feed(obs, clk, [(0.1, AUDIO()), (0.2, BotStartedSpeakingFrame()),           # 开场白
                     (1.0, UserStartedSpeakingFrame()), (1.01, UserStartedSpeakingFrame()),
                     (2.0, VADUserStoppedSpeakingFrame(stop_secs=0.2)), (2.5, UserStoppedSpeakingFrame()),
                     (2.51, UserStoppedSpeakingFrame()), (3.0, AUDIO())])
    asyncio.run(obs.flush())
    assert len(obs.turns) == 1 and obs.turns[0]["e2e_reply"] == 1200 and obs.turns[0]["asr"] is None


def test_latency_observer_llm_start_before_turn_end_frame_and_notify_keys():
    # LLM 请求可能比观察到的 UserStoppedSpeakingFrame 更早；以停说时刻为界仍能算到
    clk = _Clock()
    got = []

    async def notify(m):
        got.append(m)
    obs = LatencyObserver(clock=clk, notify=notify)
    _feed(obs, clk, [(1.0, UserStartedSpeakingFrame()), (2.0, VADUserStoppedSpeakingFrame(stop_secs=0.2)),
                     (2.5, TranscriptionFrame("好", "u", "t")), (2.6, LLMFullResponseStartFrame()),
                     (2.62, UserStoppedSpeakingFrame()), (3.0, LLMTextFrame("哎")), (3.1, TTSStartedFrame()),
                     (3.9, AUDIO())])
    asyncio.run(obs.flush())
    t = obs.turns[0]
    assert (t["llm_ttft"], t["tts_ttfb"], t["e2e_reply"]) == (400, 800, 2100)
    assert got[0]["turn"] == 1 and got[0]["turn_ms"] == 820


def test_percentile_and_summarize():
    assert percentile([1, 2, 3, 4], 50) == 2.5 and percentile([], 50) is None
    s = summarize([{"e2e_reply": 100}, {"e2e_reply": 300}, {"e2e_reply": None}])
    assert s["e2e_reply"] == {"n": 2, "p50": 200.0, "p90": 280.0}


# ---------------- 探针辅助函数 ----------------

def test_probe_speech_segments_and_client_e2e():
    import numpy as np

    from voice.probe import client_e2e, speech_segments
    rate = 16000
    loud = (np.ones(rate // 2) * 3000).astype("int16").tobytes()   # 0.5s 有声
    quiet = np.zeros(rate, dtype="int16").tobytes()                  # 1s 静音
    segs = speech_segments(quiet + loud + quiet + quiet + loud + quiet, rate=rate)
    assert [round(a, 1) for a, _ in segs] == [1.0, 3.5] and [round(b, 1) for _, b in segs] == [1.5, 4.0]
    # t0=10：第一段 11.5 结束，机器人 12.3 出声；第二段 14.0 结束后没有回复
    assert client_e2e(segs, 10.0, [11.0, 12.3, 12.4]) == [800, None]
    from voice.probe import window_flags
    assert window_flags(segs, 10.0, [12.0]) == [True, False]


def test_latency_observer_real_pipeline_counts_every_turn_and_notifies_before_hangup():
    """回归：线上 n=0。原实现按 Python id(frame) 去重，帧释放后地址被新帧复用，
    第二个起的 UserStartedSpeakingFrame 被当成重复帧丢掉；且结算要等下一回合/挂断，客户端收不到。
    这里用真实 PipelineTask + 多个处理器、帧用完即释放，断言每个回合都在挂断前上报。"""
    import gc

    from pipecat.frames.frames import (LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
                                       TranscriptionFrame, TTSAudioRawFrame, TTSStartedFrame,
                                       UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
                                       VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.frame_processor import FrameProcessor

    from voice.latency import LatencyObserver

    class Pass(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)

    got = []

    async def notify(msg):
        got.append(msg)

    async def go():
        lat = LatencyObserver(notify=notify)
        task = PipelineTask(Pipeline([Pass(), Pass(), Pass()]), params=PipelineParams(), observers=[lat])
        before_flush = {}

        async def feed():
            await asyncio.sleep(0.2)
            for i in range(4):
                await task.queue_frames([VADUserStartedSpeakingFrame(), UserStartedSpeakingFrame()])
                await asyncio.sleep(0.05)
                await task.queue_frames([TranscriptionFrame(f"第{i}句", "u", ""), VADUserStoppedSpeakingFrame(),
                                         UserStoppedSpeakingFrame()])
                await asyncio.sleep(0.05)
                await task.queue_frames([LLMFullResponseStartFrame(), LLMTextFrame("好"), TTSStartedFrame()]
                                        + [TTSAudioRawFrame(b"\0" * 320, 16000, 1) for _ in range(30)]
                                        + [LLMFullResponseEndFrame()])
                await asyncio.sleep(0.1)
                gc.collect()  # 释放本回合的帧，让下一回合的新帧有机会复用同一地址
            before_flush["turns"], before_flush["notified"] = len(lat.turns), len(got)
            await lat.flush()
            await task.cancel()

        feeder = asyncio.create_task(feed())
        await PipelineRunner(handle_sigint=False).run(task)
        await feeder
        return lat, before_flush

    lat, before = asyncio.run(go())
    assert before == {"turns": 4, "notified": 4}
    assert len(lat.turns) == 4
    assert [m["turn"] for m in got] == [1, 2, 3, 4]
    assert all(m["e2e_reply"] is not None and m["e2e_reply"] >= 0 for m in got)
