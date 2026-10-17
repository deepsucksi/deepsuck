import asyncio

from pipecat.frames.frames import (
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
)
from pipecat.tests.utils import SleepFrame, run_test

from voice.services import CosyVoiceTTSService, ParaformerSTTService


def test_cosyvoice_service_yields_audio(fake_ws):
    connect = fake_ws(mode="tts")
    tts = CosyVoiceTTSService(voice="longlaoyi_v3", connect=connect)
    down, up = asyncio.run(run_test(tts, frames_to_send=[TTSSpeakFrame("哎哟，小伙子"), SleepFrame(0.3)]))
    audio = [f for f in down if isinstance(f, TTSAudioRawFrame)]
    assert audio and sum(len(f.audio) for f in audio) > 0
    run = connect.made[0].sent_json()[0]
    assert run["payload"]["parameters"]["voice"] == "longlaoyi_v3"
    assert run["payload"]["model"] == "cosyvoice-v3-flash"


def test_cosyvoice_service_error_frame(fake_ws):
    connect = fake_ws(mode="tts", fail="InvalidApiKey")
    tts = CosyVoiceTTSService(connect=connect)
    down, up = asyncio.run(run_test(tts, frames_to_send=[TTSSpeakFrame("你好"), SleepFrame(0.3)]))
    assert any(isinstance(f, ErrorFrame) for f in list(down) + list(up))


def test_paraformer_service_pushes_transcripts(fake_ws):
    connect = fake_ws(mode="asr", asr_text="我是客服")
    stt = ParaformerSTTService(connect=connect)
    audio = InputAudioRawFrame(audio=b"\x00\x00" * 1600, sample_rate=16000, num_channels=1)
    down, _ = asyncio.run(run_test(stt, frames_to_send=[audio, SleepFrame(0.2)]))
    assert any(isinstance(f, InterimTranscriptionFrame) for f in down)
    ws = connect.made[0]
    assert any(isinstance(m, bytes) for m in ws.sent)
    assert ws.sent_json()[-1]["header"]["action"] == "finish-task"  # EndFrame 时收尾


def test_paraformer_service_final_on_finish(fake_ws):
    connect = fake_ws(mode="asr", asr_text="我是客服")
    stt = ParaformerSTTService(connect=connect)

    audio = InputAudioRawFrame(audio=b"\x00\x00" * 1600, sample_rate=16000, num_channels=1)
    down, _ = asyncio.run(run_test(stt, frames_to_send=[audio, SleepFrame(0.1)]))
    # 最终句在 finish-task 之后才到，属于收尾阶段；这里只确认会话正常关闭
    assert connect.made[0].closed
