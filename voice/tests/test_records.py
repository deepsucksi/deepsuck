"""通话留存与开场告知语：默认只留脱敏文字、不留音频；KEEP_AUDIO 天数上限 7；过期清理。全部离线。"""
import asyncio
import json
import os
import time
import wave

from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.tests.utils import run_test

from voice import records as REC
from voice.disclosure import DEFAULT_TEXT, disclosure_text

CARD = "6222021234567890123"


def _session():
    from deepsuck.engine import Session
    s = Session("grandpa_wang", "police")
    s.ingest(f"我是公安局的，你把钱转到安全账户，卡号{CARD}，收款人张三")
    s.record_bot(f"好的，卡号是{CARD}对吧", "stall")
    return s


# ---------------- 告知语 ----------------

def test_disclosure_default_off_and_configurable():
    assert disclosure_text({}) == ""
    assert disclosure_text({"VOICE_AI_DISCLOSURE": "0", "VOICE_AI_DISCLOSURE_TEXT": "x"}) == ""
    assert disclosure_text({"VOICE_AI_DISCLOSURE": "1"}) == DEFAULT_TEXT
    assert disclosure_text({"VOICE_AI_DISCLOSURE": "1", "VOICE_AI_DISCLOSURE_TEXT": "  您好，这里是自动应答。 "}) == "您好，这里是自动应答。"
    # 旧变量不再生效（以前默认开、只管电话）
    assert disclosure_text({"VOICE_TELEPHONY_DISCLOSURE": "本通话由智能助理接听。"}) == ""


def test_telephony_uses_shared_disclosure(monkeypatch):
    from voice.telephony import server as S
    monkeypatch.setenv("VOICE_AI_DISCLOSURE", "1")
    monkeypatch.setenv("VOICE_AI_DISCLOSURE_TEXT", "测试告知")
    assert S.disclosure_text() == "测试告知"
    monkeypatch.delenv("VOICE_AI_DISCLOSURE")
    assert S.disclosure_text() == ""


# ---------------- 配置解析 ----------------

def test_audio_days_capped_at_7():
    assert REC.audio_days({}) == 7
    assert REC.audio_days({"KEEP_AUDIO_DAYS": "3"}) == 3
    assert REC.audio_days({"KEEP_AUDIO_DAYS": "30"}) == 7
    assert REC.audio_days({"KEEP_AUDIO_DAYS": "0"}) == 1
    assert REC.audio_days({"KEEP_AUDIO_DAYS": "abc"}) == 7
    assert not REC.keep_audio({}) and REC.keep_audio({"KEEP_AUDIO": "1"})
    assert REC.recorder_for("x", {}) is None
    assert REC.transcript_days({}) == 30 and REC.transcript_days({"VOICE_TRANSCRIPT_DAYS": "0"}) == 0
    assert REC.transcripts_enabled({}) and not REC.transcripts_enabled({"VOICE_TRANSCRIPTS": "0"})


# ---------------- 文字记录 ----------------

def test_transcript_is_redacted_by_shared_module(tmp_path):
    env = {"DATA_DIR": str(tmp_path)}
    p = REC.save_transcript(_session(), "abc/../x", "web", env=env)
    assert p is not None and p.parent == REC.transcript_dir(env) and ".." not in p.name
    raw = p.read_text(encoding="utf-8")
    assert CARD not in raw and "张三" not in raw
    d = json.loads(raw)
    assert d["channel"] == "web" and [m["role"] for m in d["transcript"]] == ["scammer", "bot"]
    # 与共享脱敏模块的结果一致（voice/ 不另写规则）
    from deepsuck import extract_sensitive, redact_text
    text = f"好的，卡号是{CARD}对吧"
    # #120：人设侧再过连续数字兜底，卡号打码值里留下的前 6 后 4 位也换成 *
    from deepsuck.redact import redact_persona
    assert d["transcript"][1]["text"] == redact_persona(redact_text(text, extract_sensitive(text)))
    assert d["transcript"][1]["text"] == "好的，卡号是" + "*" * 19 + "对吧"
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"


def test_transcript_disabled_or_empty(tmp_path):
    from deepsuck.engine import Session
    env = {"DATA_DIR": str(tmp_path), "VOICE_TRANSCRIPTS": "0"}
    assert REC.save_transcript(_session(), "a", "web", env=env) is None
    assert REC.save_transcript(Session("grandpa_wang", "police"), "a", "web", env={"DATA_DIR": str(tmp_path)}) is None
    assert not REC.transcript_dir({"DATA_DIR": str(tmp_path)}).exists()


# ---------------- 录音 ----------------

def test_audio_recorder_writes_two_tracks(tmp_path):
    env = {"DATA_DIR": str(tmp_path), "KEEP_AUDIO": "1"}
    rec = REC.recorder_for("call-1", env)
    tin, tout = REC.AudioTap(rec, "in"), REC.AudioTap(rec, "out")
    frames_in = [InputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=16000, num_channels=1)] * 3
    frames_out = [TTSAudioRawFrame(audio=b"\x02\x00" * 240, sample_rate=24000, num_channels=1),
                  OutputAudioRawFrame(audio=b"\x03\x00" * 240, sample_rate=24000, num_channels=1),
                  OutputAudioRawFrame(audio=b"\x04\x00" * 80, sample_rate=8000, num_channels=1)]  # 采样率不同，丢弃
    asyncio.run(run_test(tin, frames_to_send=frames_in))
    asyncio.run(run_test(tout, frames_to_send=frames_out))
    rec.close()
    with wave.open(str(rec.paths["in"])) as w:
        assert (w.getframerate(), w.getnframes()) == (16000, 480)
    with wave.open(str(rec.paths["out"])) as w:
        assert (w.getframerate(), w.getnframes()) == (24000, 480)
    assert oct(os.stat(rec.paths["in"]).st_mode & 0o777) == "0o600"


def _build(recorder):
    from voice.app import build_pipeline
    from deepsuck.engine import Session

    class T:
        def __init__(self):
            self.i, self.o = FrameProcessor(name="in"), FrameProcessor(name="out")

        def input(self):
            return self.i

        def output(self):
            return self.o

    async def go(engine):
        pl, _, _ = build_pipeline(T(), Session("grandpa_wang", "police"), None, engine=engine, fillers={},
                                  llm=FrameProcessor(name="llm"), recorder=recorder)
        return [getattr(p, "name", "") for p in pl.processors], [type(p).__name__ for p in pl.processors]
    return asyncio.run(go("llm")), asyncio.run(go("rule"))


def test_build_pipeline_no_taps_by_default():
    (_, llm_types), (_, rule_types) = _build(None)
    assert "AudioTap" not in llm_types and "AudioTap" not in rule_types


def test_build_pipeline_taps_around_transport(tmp_path):
    rec = REC.AudioRecorder("x", {"DATA_DIR": str(tmp_path)})
    for names, types in _build(rec):
        i, o = names.index("in"), names.index("out")
        assert types[i + 1] == "AudioTap" and types[o - 1] == "AudioTap"
        assert types.count("AudioTap") == 2


# ---------------- 过期清理 ----------------

def _touch(p, age_days, now):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    t = now - age_days * 86400
    os.utime(p, (t, t))


def test_cleanup_removes_expired(tmp_path):
    now = time.time()
    env = {"DATA_DIR": str(tmp_path), "KEEP_AUDIO_DAYS": "30"}  # 按 7 天处理
    a, t = REC.audio_dir(env), REC.transcript_dir(env)
    _touch(a / "old-in.wav", 8, now)
    _touch(a / "new-in.wav", 6, now)
    _touch(a / "note.txt", 100, now)          # 非 wav 不动
    _touch(t / "old.json", 31, now)
    _touch(t / "new.json", 29, now)
    assert REC.cleanup(env, now=now) == 2
    assert sorted(x.name for x in a.iterdir()) == ["new-in.wav", "note.txt"]
    assert sorted(x.name for x in t.iterdir()) == ["new.json"]


def test_cleanup_audio_even_when_keep_audio_off_and_transcripts_forever(tmp_path):
    now = time.time()
    env = {"DATA_DIR": str(tmp_path), "KEEP_AUDIO_DAYS": "2", "VOICE_TRANSCRIPT_DAYS": "0"}
    _touch(REC.audio_dir(env) / "a.wav", 3, now)
    _touch(REC.transcript_dir(env) / "t.json", 400, now)
    assert REC.cleanup(env, now=now) == 1
    assert (REC.transcript_dir(env) / "t.json").exists()
    assert REC.cleanup({"DATA_DIR": str(tmp_path / "none")}, now=now) == 0  # 目录不存在不报错


def test_cleanup_loop_runs_immediately(tmp_path):
    now = time.time()
    env = {"DATA_DIR": str(tmp_path)}
    _touch(REC.audio_dir(env) / "a.wav", 10, now)

    async def go():
        t = asyncio.create_task(REC.cleanup_loop(interval=3600, env=env))
        await asyncio.sleep(0.2)
        t.cancel()
    asyncio.run(go())
    assert not (REC.audio_dir(env) / "a.wav").exists()


def test_app_startup_runs_retention(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from voice.app import create_app
    now = time.time()
    env = {"DATA_DIR": os.environ["DATA_DIR"]}
    _touch(REC.audio_dir(env) / "old.wav", 9, now)
    with TestClient(create_app(engine="rule")) as c:
        assert c.get("/api/config").status_code == 200
        for _ in range(20):
            if not (REC.audio_dir(env) / "old.wav").exists():
                break
            time.sleep(0.05)
    assert not (REC.audio_dir(env) / "old.wav").exists()


def test_transcript_write_calls_redact_text_even_for_unredacted_messages(tmp_path):
    # 即使有文字绕过了 Session.ingest（例如以后新增的入口），落盘前也会经过 deepsuck.redact.redact_text
    from deepsuck.engine import Session
    s = Session("grandpa_wang", "police")
    s.messages.append({"role": "scammer", "text": "电话13912342233，卡号6222020200112233", "t": time.time()})
    p = REC.save_transcript(s, "raw", "phone", env={"DATA_DIR": str(tmp_path)})
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["transcript"][0]["text"] == "电话139****2233，卡号622202******2233"


def test_transcript_masks_otp_split_across_segments(tmp_path):
    """#92：同一说话方相邻分段连起来判断验证码；不跨说话方。"""
    from deepsuck.engine import Session
    s = Session("refund", "lin")
    s.ingest("验证码是 38")
    s.record_bot("你慢点", "generic")
    s.ingest("27 15")
    s.ingest("那你先转 3000 元")
    p = REC.save_transcript(s, "otp", "web", env={"DATA_DIR": str(tmp_path)})
    d = json.loads(p.read_text(encoding="utf-8"))
    scam = [m["text"] for m in d["transcript"] if m["role"] == "scammer"]
    assert scam == ["验证码是 **", "** **", "那你先转 3000 元"]
