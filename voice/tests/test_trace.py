"""通话追踪：脱敏文字每通都存，录音只在同意时存；SIP 不录音且主叫打码；脱敏；token 保护；
30 天清理（录音目录/天数可单独配）；磁盘上限停录；“这通有问题”只认当前通话、写进同一份记录；
每轮 schema 字段（docs/TRACE_SCHEMA.md）；trace_cli 列出有问题的通话、按天汇总用量。全部离线。"""
import asyncio
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from voice import trace as TR

CARD = "6222020200112233445"
PHONE = "13800138000"


def _env(tmp_path, **kw):
    e = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0"}
    e.update({k: str(v) for k, v in kw.items()})
    return e


def _talk(t: TR.CallTrace):
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    t.observe({"type": "scammer", "text": f"我是客服，卡号{CARD}，电话{PHONE}", "turn": 1, "intent": "confirm_intel",
               "tactics": [{"id": "cs_impersonation", "label": "冒充客服"}],
               "newIntel": [{"type": "bank_card", "label": "银行卡号", "masked": "6222 **** 3445"}]})
    t.observe({"type": "filler", "text": "嗯…"})
    t.observe({"type": "latency", "turn": 1, "asr": 300, "first_audible": 500, "e2e_reply": 1500})
    t.observe({"type": "bot", "text": f"卡号是{CARD}吗", "intent": "confirm_intel"})
    t.observe({"type": "scammer", "text": "对，快点", "turn": 2, "intent": "urgency_stall", "tactics": [], "newIntel": []})
    t.observe({"type": "bot", "text": "别催，我在找", "intent": "urgency_stall"})


def _lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_ids():
    ids = {TR.new_id() for _ in range(200)}
    assert len(ids) == 200 and all(TR.valid_id(i) for i in ids)
    assert not TR.valid_id("../etc/pa") and not TR.valid_id("abcdefgh") and not TR.valid_id("ABCDEFG1")


def test_consent_writes_redacted_turns_and_end(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="qwen-plus", env=env,
                     prompt_sha=lambda: "abcd1234")
    _talk(t)
    t.end("client_hangup", stats={"turns": 2}, latency={"first_audible": {"p50": 500}})
    rows = _lines(t.path)
    assert [r["type"] for r in rows] == ["start", "bot", "turn", "turn", "end"]
    st, op, t1, t2, end = rows
    assert st["consent"] is True and st["id"] == t.id and st["model"] == "qwen-plus" and st["code"]
    assert op["kind"] == "opening"
    assert t1["n"] == 1 and t1["intent"] == "confirm_intel" and t1["filler"] == "嗯…"
    assert t1["latency"]["first_audible"] == 500 and t1["prompt"] == "abcd1234" and t1["promptVersion"]
    assert t1["persona"] == "lin" and t1["scenario"] == "pig" and t1["consent"] is True and t1["code"]
    assert t1["intel"][0]["masked"] == "6222 **** 3445" and t1["tactics"] == ["cs_impersonation"]
    raw = t.path.read_text(encoding="utf-8")
    assert CARD not in raw and PHONE not in raw  # 文字入库前再脱敏一次（看板消息里的原文也挡住）
    assert t2["asr"] == "对，快点" and t2["reply"] == "别催，我在找"
    assert end["reason"] == "client_hangup" and end["turns"] == 2
    assert oct(os.stat(t.path).st_mode & 0o777) == "0o600"


def test_no_consent_stores_redacted_text_but_no_audio(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=False, persona="wang", scenario="refund", model="qwen-plus", env=env)
    assert t.store and t.audio_processor() is None and t.audio is None
    _talk(t)
    t.end("client_hangup")
    files = sorted(p.name for p in (tmp_path / "traces").iterdir())
    assert files == sorted(["stats.json", f"{t.id}.jsonl"])  # 没有 .ogg
    rows = _lines(t.path)
    assert rows[0]["consent"] is False and rows[-1]["type"] == "end" and rows[-1]["consent"] is False
    assert rows[-1]["audio"] is False and sum(1 for r in rows if r["type"] == "turn") == 2
    raw = t.path.read_text(encoding="utf-8")
    assert CARD not in raw and PHONE not in raw
    stats = json.loads((tmp_path / "traces" / "stats.json").read_text())
    day = next(iter(stats.values()))
    assert day["calls"] == 1 and day["noConsent"] == 1 and "consent" not in day
    assert set(json.dumps(stats)) .isdisjoint(set("客服")) and t.id not in json.dumps(stats)
    # 字符串 "true" 不算同意：照样只存文字、不录音
    t2 = TR.CallTrace(channel="web", consent="true", persona="wang", scenario="refund", model="m", env=env)
    assert t2.consent is False and t2.audio_processor() is None
    # VOICE_TRACE=0：什么都不存
    t3 = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m",
                      env=_env(tmp_path, VOICE_TRACE=0))
    _talk(t3)
    t3.end("x")
    assert not t3.store and not t3.path.exists()


def test_sip_text_only_masks_caller_and_never_records(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="phone", consent=True, persona="wang", scenario="refund", model="qwen-plus",
                     caller="+86" + PHONE, env=env)
    assert t.consent == TR.SIP_CONSENT and t.store
    assert t.audio_processor() is None
    _talk(t)
    t.end("caller_hangup")
    rows = _lines(t.path)
    assert rows[0]["consent"] == "sip-text-only" and rows[0]["caller"] == "138****8000"
    assert PHONE not in t.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "traces").glob("*.ogg"))
    assert TR.feedback(t.id, "x", env=env) is None  # 电话线路没有反馈按钮


def _pcm(secs, amp=3000):
    import numpy as np
    n = int(16000 * secs)
    return (np.sin(np.arange(n) / 7.0) * amp).astype("int16").tobytes()


def test_consent_records_two_opus_tracks(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="qwen-plus", env=env)
    buf = t.audio_processor()
    assert buf is not None and t.audio is not None
    for _ in range(3):
        t.audio.feed(_pcm(2), _pcm(2, 1000), 16000)
    t.end("client_hangup")
    for e in t.audio.enc.values():
        e.join(10)
    import av
    for k in TR.TRACKS:
        p = t.audio_path(k)
        assert p.exists() and 1000 < p.stat().st_size < 60000, (k, p.stat().st_size)
        with av.open(str(p)) as c:
            assert c.streams.audio[0].codec_context.name == "opus"
            n = sum(f.samples for f in c.decode(audio=0))
            assert abs(n / 48000 - 6.0) < 0.2
    deadline = time.time() + 5
    while time.time() < deadline and _lines(t.path)[-1]["type"] != "audio":
        time.sleep(0.05)
    last = _lines(t.path)[-1]
    assert last["type"] == "audio" and last["scammer"]["seconds"] == 6.0 and last["persona"]["bytes"] > 0


def test_audio_buffer_processor_feeds_tracks(tmp_path):
    """真正的 Pipecat AudioBufferProcessor：输入帧进对方轨、输出帧进人设轨。"""
    from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
    from pipecat.tests.utils import run_test

    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env)
    buf = t.audio_processor()
    frames = []
    for _ in range(50):
        frames.append(InputAudioRawFrame(audio=_pcm(0.02), sample_rate=16000, num_channels=1))
        frames.append(OutputAudioRawFrame(audio=_pcm(0.02), sample_rate=16000, num_channels=1))
    asyncio.run(run_test(buf, frames_to_send=frames, expected_down_frames=None))
    t.end("pipeline_end")
    for e in t.audio.enc.values():
        e.join(10)
    assert all(t.audio.enc[k].samples > 0 for k in TR.TRACKS)
    assert all(t.audio_path(k).stat().st_size > 0 for k in TR.TRACKS)


def test_disk_cap_stops_audio_but_keeps_text(tmp_path):
    env = _env(tmp_path, TRACE_MAX_MB=0)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env)
    assert t.audio_processor() is None
    _talk(t)
    t.end("client_hangup")
    rows = _lines(t.path)
    assert any(r["type"] == "audio_stopped" and "上限" in r["reason"] for r in rows)
    assert any(r["type"] == "turn" for r in rows) and not list((tmp_path / "traces").glob("*.ogg"))
    # 通话中磁盘剩余掉到阈值以下：停录，文字照存
    free = {"v": 10 << 30}
    env2 = _env(tmp_path, TRACE_MIN_FREE_MB=1024)
    t2 = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env2,
                      free_fn=lambda _p: free["v"])
    assert t2.audio_processor() is not None
    t2.audio.feed(_pcm(1), _pcm(1), 16000)
    free["v"] = 100 << 20
    t2.audio.feed(_pcm(1), _pcm(1), 16000)
    assert t2.audio.stopped and t2.audio.enc["scammer"].closed
    _talk(t2)
    t2.end("x")
    assert any(r["type"] == "audio_stopped" for r in _lines(t2.path)) and any(r["type"] == "turn" for r in _lines(t2.path))


def test_cleanup_30_days(tmp_path):
    env = _env(tmp_path)
    d = tmp_path / "traces"
    d.mkdir()
    old, new = d / "AAAAAAAA.jsonl", d / "BBBBBBBB.jsonl"
    for p in (old, new, d / "AAAAAAAA-scammer.ogg", d / "stats.json"):
        p.write_text("{}")
    past = time.time() - 31 * 86400
    for p in (old, d / "AAAAAAAA-scammer.ogg", d / "stats.json"):
        os.utime(p, (past, past))
    assert TR.cleanup(env) == 2
    assert sorted(p.name for p in d.iterdir()) == ["BBBBBBBB.jsonl", "stats.json"]
    os.utime(new, (time.time() - 10 * 86400,) * 2)
    assert TR.cleanup(_env(tmp_path, TRACE_DAYS=7)) == 1


def test_feedback_and_list_load(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env,
                     feedback_key="k-this-page")
    _talk(t)
    t.end("client_hangup")
    assert "k-this-page" not in t.path.read_text(encoding="utf-8")  # 口令只存哈希
    assert TR.feedback(t.id, f"第二轮不对，我电话{PHONE}", 2, env=env, key="k-this-page") == {"ok": True}
    assert TR.feedback(t.id, "", "abc", env=env, key="k-this-page") == {"ok": True}
    assert TR.feedback("ZZZZZZZZ", "x", env=env) is None and TR.feedback("../x", "x", env=env) is None
    rows = [r for r in _lines(t.path) if r["type"] == "feedback"]
    assert rows[0]["turn"] == 2 and PHONE not in rows[0]["note"] and rows[1]["turn"] is None
    assert rows[0]["flagged"] is True and rows[0]["call_id"] == t.id and rows[0]["schema_version"] == TR.SCHEMA_VERSION
    for _ in range(30):
        TR.feedback(t.id, "x", env=env, key="k-this-page")
    assert sum(1 for r in _lines(t.path) if r["type"] == "feedback") == TR.MAX_FEEDBACK
    assert TR.feedback(t.id, "x", env=env, key="k-this-page") == {"ok": False, "error": "too many"}
    lst = TR.list_traces(env=env)
    assert lst[0]["id"] == t.id and lst[0]["turns"] == 2 and lst[0]["feedback"] == TR.MAX_FEEDBACK
    assert lst[0]["flagged"] is True
    from voice import trace_cli
    out = trace_cli.render(TR.load(t.id, env=env), audio=True)
    assert "意图=confirm_intel" in out and "首声=500ms" in out and "这通有问题（第 2 轮）" in out and "录音: 无" in out


def test_feedback_only_for_current_call(tmp_path):
    """只认当前通话：要带本页的口令；不同意录音的通话也能标记；超过 TRACE_FEEDBACK_HOURS 不收。"""
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=False, persona="lin", scenario="pig", model="m", env=env,
                     feedback_key="right")
    t.end("client_hangup")
    assert TR.feedback(t.id, "x", env=env) == {"ok": False, "error": "forbidden"}
    assert TR.feedback(t.id, "x", env=env, key="wrong") == {"ok": False, "error": "forbidden"}
    assert TR.feedback(t.id, "答非所问", env=env, key="right") == {"ok": True}
    late = time.time() + 7 * 3600
    assert TR.feedback(t.id, "x", env=env, key="right", now=late) == {"ok": False, "error": "expired"}
    assert TR.feedback(t.id, "x", env=_env(tmp_path, TRACE_FEEDBACK_HOURS=24), key="right", now=late) == {"ok": True}
    # 别的通话的口令不能用在这一通
    other = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", env=env,
                         feedback_key="other")
    assert TR.feedback(t.id, "x", env=env, key="other")["error"] == "forbidden"
    assert TR.feedback(other.id, "x", env=env, key="other") == {"ok": True}


def test_mask_caller():
    assert TR.mask_caller("13800138000") == "138****8000"
    assert TR.mask_caller("sipuser") == "***" and TR.mask_caller("") == ""


def _app(monkeypatch, tmp_path):
    from voice import app as A
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("TRACE_MIN_FREE_MB", "0")
    monkeypatch.delenv("VOICE_ALLOWED_ORIGINS", raising=False)
    return A.create_app("rule")


def test_trace_api_requires_token(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    c = TestClient(app)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m")
    _talk(t)
    t.end("client_hangup")
    # 没配 token：一律 404
    assert c.get("/api/traces").status_code == 404
    assert c.get(f"/api/traces/{t.id}", headers={"Authorization": "Bearer x"}).status_code == 404
    monkeypatch.setenv("TRACE_ADMIN_TOKEN", "s3cret-token-for-test")
    assert c.get("/api/traces").status_code == 403
    assert c.get("/api/traces", headers={"Authorization": "Bearer wrong"}).status_code == 403
    H = {"Authorization": "Bearer s3cret-token-for-test"}
    assert c.get("/api/traces", headers={**H, "X-Forwarded-For": "1.2.3.4"}).status_code == 404  # 经代理来的
    r = c.get("/api/traces?limit=5", headers=H)
    assert r.status_code == 200 and r.json()["traces"][0]["id"] == t.id
    r = c.get(f"/api/traces/{t.id}", headers=H)
    assert r.status_code == 200 and r.json()["lines"][0]["type"] == "start"
    assert c.get(f"/api/traces/{t.id}/audio/scammer", headers=H).status_code == 404
    assert c.get(f"/api/traces/{t.id}/audio/..%2f..", headers=H).status_code == 404
    assert c.get("/api/traces/nothere1", headers=H).status_code == 404


def test_feedback_endpoint(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    c = TestClient(app)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", feedback_key="kk")
    t.end("client_hangup")
    assert c.post(f"/api/feedback/{t.id}", json={"key": "kk", "note": "第3轮答非所问", "turn": 3}).json() == {"ok": True}
    assert c.post(f"/api/feedback/{t.id}", json={"note": "没带口令"}).status_code == 403
    assert c.post(f"/api/feedback/{t.id}", json={"key": 123}).status_code == 403
    assert c.post("/api/feedback/AAAAAAAA", json={}).status_code == 404
    off = TR.CallTrace(channel="web", consent=False, persona="lin", scenario="pig", model="m", feedback_key="k2")
    assert c.post(f"/api/feedback/{off.id}", json={"key": "k2", "note": "x"}).status_code == 200
    sip = TR.CallTrace(channel="phone", consent=None, persona="lin", scenario="pig", model="m")
    assert c.post(f"/api/feedback/{sip.id}", json={"key": "x"}).status_code == 404
    cfg = c.get("/api/config").json()["trace"]
    assert cfg["days"] == 30 and cfg["audioDays"] == 30
    rows = [r for r in _lines(TR.trace_dir() / f"{t.id}.jsonl") if r["type"] == "feedback"]
    assert len(rows) == 1 and rows[0]["note"] == "第3轮答非所问" and rows[0]["turn"] == 3


def test_feedback_endpoint_rate_limited(monkeypatch, tmp_path):
    c = TestClient(_app(monkeypatch, tmp_path))
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="pig", model="m", feedback_key="kk")
    codes = [c.post(f"/api/feedback/{t.id}", json={"key": "kk"}).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[5] == 429  # 每通最多 5 条
    assert codes[6:] == [429, 429]                       # 同一 IP 每分钟 6 次
    assert c.post("/api/feedback/AAAAAAAA", json={}).status_code == 429


def test_offer_passes_consent_and_returns_trace_id(monkeypatch, tmp_path):
    import pipecat.transports.smallwebrtc.request_handler as RH
    from voice import app as A

    seen = []

    class FakeHandler:
        def __init__(self, *a, **k):
            pass

        async def handle_web_request(self, req, cb):
            class Conn:
                pc_id = "pc-1"
            await cb(Conn())
            return {"sdp": "v=0", "type": "answer", "pc_id": "pc-1"}

    async def fake_run_bot(conn, persona, scenario, engine, **kw):
        seen.append(kw)
        kw["on_done"]()

    monkeypatch.setattr(RH, "SmallWebRTCRequestHandler", FakeHandler)
    monkeypatch.setattr(A, "run_bot", fake_run_bot)
    c = TestClient(_app(monkeypatch, tmp_path))
    r = c.post("/api/offer", json={"sdp": "v=0", "type": "offer", "consent": True})
    tid = r.json()["trace_id"]
    assert TR.valid_id(tid) and seen[-1]["consent"] is True and seen[-1]["trace_id"] == tid
    key = r.json()["feedback_key"]
    assert len(key) >= 20 and seen[-1]["feedback_key"] == key
    r = c.post("/api/offer", json={"sdp": "v=0", "type": "offer"})
    # 不同意录音也有编号（页面显示、报问题时引用），口令每通不同
    assert TR.valid_id(r.json()["trace_id"]) and r.json()["trace_id"] != tid and seen[-1]["consent"] is False
    assert r.json()["feedback_key"] != key


def test_pipeline_places_audiobuf_after_output():
    from pipecat.processors.frame_processor import FrameProcessor
    from voice import app as A
    from deepsuck.engine import Session

    class T:
        def __init__(self):
            self.i, self.o = FrameProcessor(name="in"), FrameProcessor(name="out")

        def input(self):
            return self.i

        def output(self):
            return self.o

    tr = T()
    buf = FrameProcessor(name="audiobuf")

    async def notify(_m):
        return None
    pipe, _intel, _ctx = A.build_pipeline(tr, Session("refund", "wang"), notify, engine="llm",
                                          stt=FrameProcessor(name="stt"), tts=FrameProcessor(name="tts"),
                                          llm=FrameProcessor(name="llm"), vad_analyzer=object(), audiobuf=buf)
    names = [p.name for p in pipe.processors]
    assert names.index("audiobuf") == names.index("out") + 1


def test_cross_turn_card_digits_are_redacted_via_session(tmp_path):
    """卡号分三句报：单句时各段不像卡号，拼接后 Session 回头给前几句补打码；追踪落盘以会话最终文本为准。"""
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32

    env = _env(tmp_path)
    s = Session(scenario="refund", persona="lin", rng=mulberry32(1), now=lambda: 0)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="refund", model="m", env=env)
    t.session = s
    for i, line in enumerate(["卡号是62220212。", "345678。", "90123。", "好了吗", "快点"]):
        a = s.ingest(line)
        t.observe({"type": "scammer", "text": a["redacted"], "turn": a["turn"], "intent": "generic",
                   "tactics": [], "newIntel": a["newIntel"]})
        if i in (0, 3, 4):
            t.observe({"type": "bot", "text": "嗯", "intent": "generic"})
    t.end("client_hangup")
    raw = t.path.read_text(encoding="utf-8")
    assert s.intel, "拼接应识别出卡号"
    assert "62220212" not in raw and "345678" not in raw, raw
    assert [r["n"] for r in _lines(t.path) if r["type"] == "turn"] == [1, 2, 3]


def test_split_otp_across_asr_segments_is_redacted_on_disk(tmp_path):
    """#92：验证码被 ASR 切成「验证码是 38」「27 15」两段，落盘时同一说话方相邻分段连起来判断，两段都打码。"""
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32

    env = _env(tmp_path)
    s = Session(scenario="refund", persona="lin", rng=mulberry32(1), now=lambda: 0)
    t = TR.CallTrace(channel="web", consent=True, persona="lin", scenario="refund", model="m", env=env)
    t.session = s
    for line in ["验证码是 38", "27 15", "那你先转 3000 元", "快点"]:
        a = s.ingest(line)
        t.observe({"type": "scammer", "text": a["redacted"], "turn": a["turn"], "intent": "generic",
                   "tactics": [], "newIntel": a["newIntel"]})
        t.observe({"type": "bot", "text": "嗯", "intent": "generic"})
    t.end("client_hangup")
    turns = [r for r in _lines(t.path) if r["type"] == "turn"]
    assert [r["asr"] for r in turns] == ["验证码是 **", "** **", "那你先转 3000 元", "快点"]


def test_split_otp_without_session_uses_trace_history(tmp_path):
    """没有会话对象时，用本通已记下的同一说话方分段判断；人设回复单独按人设自己的分段判断。"""
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=False, persona="lin", scenario="refund", model="m", env=env)
    for n, (sc, bot) in enumerate([("你的校验码是三八", "验证码是"), ("二七", "我看看"), ("一五", "好")], 1):
        t.observe({"type": "scammer", "text": sc, "turn": n, "intent": "generic", "tactics": [], "newIntel": []})
        t.observe({"type": "bot", "text": bot, "intent": "generic"})
    t.end("client_hangup")
    turns = [r for r in _lines(t.path) if r["type"] == "turn"]
    assert [r["asr"] for r in turns] == ["你的校验码是**", "**", "**"]
    assert [r["reply"] for r in turns] == ["验证码是", "我看看", "好"]   # 不跨说话方拼接


def test_seg_redact_slice_matches_whole_call():
    segs = ["验证码是", "38", "嗯", "27", "15", "好的", "金额 5000", "下午 3 点"]
    from deepsuck.redact import redact_otp_segments
    whole = redact_otp_segments(segs)
    for i in range(len(segs)):
        assert TR.seg_redact(segs, [i]) == [whole[i]]
