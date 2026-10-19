"""通话追踪 schema v3（#94）：type="call" 调用行（每轮每种 kind 一行，合计对得上）、tts_billed_chars（CosyVoice
汉字算 2）、end 行的 persona / channel / asr_model / tts_model、cost.py 优先读 v3 且 v2 / v3 都能读。全部离线。"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from voice import cost as C
from voice import guard as G
from voice import trace as TR

CN = timezone(timedelta(hours=8))
T0 = datetime(2026, 10, 19, 10, 0, tzinfo=CN).timestamp()
FAREWELL = "好了，今天就到这儿。我先挂了啊。"
V3 = ("prompt_tokens", "completion_tokens", "asr_seconds", "tts_chars", "tts_billed_chars")


def _env(tmp_path):
    return {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0"}


def _lines(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def test_billed_chars_rule():
    assert G.tts_billed_chars("喂？哪位") == 7                 # 3 个汉字 ×2 + 全角问号 1
    assert G.tts_billed_chars("OK，3点 a") == 1 + 1 + 1 + 1 + 2 + 1 + 1
    assert G.tts_billed_chars("說明") == 4 and G.tts_billed_chars("かな한") == 3  # 繁体算汉字；假名、谚文算 1
    assert G.tts_billed_chars("") == 0 and G.tts_billed_chars(None) == 0


def test_ticket_kinds_and_tags():
    tk = G.VoiceBudget().reserve(0.0)
    tk.tag(FAREWELL, "farewell")
    tk.tts(len("好了，今天就到这儿。"), text="好了，今天就到这儿。")  # TTS 分句合成，按子串认领
    tk.tts(len("我先挂了啊。"), text="我先挂了啊。")
    tk.tts(3, text="你说啥")
    tk.tts(2, kind="filler", text="嗯…")
    tk.llm(100, 10)
    tk.asr(1.5)
    k = tk.kinds()
    assert k["farewell"]["tts_chars"] == len(FAREWELL) and k["farewell"]["tts_billed_chars"] == G.tts_billed_chars(FAREWELL)
    assert k["reply"]["tts_chars"] == 3 and k["reply"]["llm_in"] == 100 and k["filler"]["tts_billed_chars"] == 3
    assert k["asr"]["asr_sec"] == 1.5 and not tk._tags
    for key in G.TICKET_KEYS:  # 各 kind 之和 = 整局合计
        assert abs(sum(v[key] for v in k.values()) - tk.usage[key]) < 1e-9, key


def _call(env, consent=True, channel="web"):
    """一通模拟通话：Ticket 由“服务”按真实调用顺序计量，CallTrace 从看板通知切轮。"""
    tk = G.VoiceBudget().reserve(0.0)
    clock = Clock()
    t = TR.CallTrace(channel=channel, consent=consent, persona="wang", scenario="refund", model="qwen-flash",
                     env=env, clock=clock, tts_voice="v-wang", asr_model="asr-x", tts_model="tts-x",
                     usage_fn=lambda: dict(tk.usage), calls_fn=tk.kinds, feedback_key="key")
    tk.tag("我先说明一下", "disclosure")
    tk.tag("喂？哪位", "opening")
    t.observe({"type": "bot", "text": "我先说明一下", "intent": "disclosure"})
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    tk.tts(6, text="我先说明一下")
    tk.tts(4, text="喂？哪位")
    # 第 1 轮：对方报姓名卡号；口头语 + 正式回复
    tk.asr(4.0)
    t.observe({"type": "scammer", "text": "我叫张伟，卡号6222020200112233445", "turn": 1, "intent": "confirm_intel",
               "tactics": [], "newIntel": []})
    tk.tts(2, kind="filler", text="嗯…")
    tk.llm(800, 30)
    tk.tts(9, text="啊？卡号你再说一遍")
    t.observe({"type": "bot", "text": "啊？卡号你再说一遍", "intent": "confirm_intel"})
    clock.t += 20
    # 第 2 轮
    tk.asr(3.5)
    t.observe({"type": "scammer", "text": "快点转账", "turn": 2, "intent": "urgency_stall", "tactics": [], "newIntel": []})
    tk.llm(900, 25)
    tk.tts(7, text="别催，我找纸笔")
    t.observe({"type": "bot", "text": "别催，我找纸笔", "intent": "urgency_stall"})
    clock.t += 5
    # 第 2 轮之后：尾音识别 + 告别语
    t.observe({"type": "scammer", "text": "喂", "turn": 3, "intent": "generic", "tactics": [], "newIntel": []})
    tk.asr(1.0)
    tk.tag(FAREWELL, "farewell")
    t.observe({"type": "bot", "text": FAREWELL, "intent": "hangup"})
    tk.tts(len(FAREWELL), text=FAREWELL)
    clock.t += 5
    t.end("time", usage=dict(tk.usage))
    return t, tk


def test_call_rows_per_turn_per_kind_and_sums(tmp_path):
    t, tk = _call(_env(tmp_path))
    rows = _lines(t.path)
    assert all(r["schema_version"] == 3 for r in rows)
    calls = [r for r in rows if r["type"] == "call"]
    turns = {r["turn"]: r for r in rows if r["type"] == "turn"}
    keyset = {(c["turn"], c["kind"], bool(c.get("tail"))) for c in calls}
    assert len(keyset) == len(calls)  # 同一轮同一 kind 只有一行
    assert {(1, "disclosure"), (1, "opening"), (1, "asr"), (1, "filler"), (1, "reply"), (2, "reply")} \
        <= {(c["turn"], c["kind"]) for c in calls}
    for c in calls:
        for f in ("turn", "kind", "llm_model", *V3, "tts_voice"):
            assert f in c, f
        assert c["kind"] in TR.CALL_KINDS
        assert (c["llm_model"] == "qwen-flash") == bool(c["prompt_tokens"] or c["completion_tokens"])
        assert (c["tts_voice"] == "v-wang") == bool(c["tts_chars"])
    r1 = next(c for c in calls if c["turn"] == 1 and c["kind"] == "reply")
    assert (r1["prompt_tokens"], r1["completion_tokens"], r1["tts_chars"]) == (800, 30, 9)
    op = next(c for c in calls if c["kind"] == "opening")
    assert op["tts_billed_chars"] == 7 and op["llm_model"] is None and op["prompt_tokens"] == 0
    fw = next(c for c in calls if c["kind"] == "farewell")
    assert fw["turn"] == 3 and "tail" not in fw and fw["tts_billed_chars"] == G.tts_billed_chars(FAREWELL)
    end = rows[-1]
    # 各 call 行之和 = usage_total
    for f in V3:
        tot = sum(c[f] for c in calls)
        assert abs(tot - end["usage_total"][f]) < 1e-6, f
    # 同一轮不带 tail 的 call 行之和 = 这一轮 turn 行的用量（v2 名字）
    for n, tr in turns.items():
        cs = [c for c in calls if c["turn"] == n and not c.get("tail")]
        assert sum(c["prompt_tokens"] for c in cs) == tr["llm_in_tokens"]
        assert sum(c["tts_chars"] for c in cs) == tr["tts_chars"]
        assert sum(c["tts_billed_chars"] for c in cs) == tr["tts_billed_chars"]
        assert abs(sum(c["asr_seconds"] for c in cs) - tr["asr_audio_sec"]) < 1e-6
    # end 行 v3 字段；v2 字段照旧
    assert (end["persona"], end["persona_id"], end["channel"]) == ("wang", "wang", "web")
    assert (end["asr_model"], end["tts_model"], end["tts_voice"]) == ("asr-x", "tts-x", "v-wang")
    u = end["usage_total"]
    assert (u["prompt_tokens"], u["llm_in_tokens"]) == (1700, 1700) and u["completion_tokens"] == u["llm_out_tokens"] == 55
    assert u["asr_seconds"] == u["asr_audio_sec"] == 8.5 and u["tts_billed_chars"] == tk.usage["tts_billed_chars"]
    assert end["usage"]["tts_billed_chars"] == tk.usage["tts_billed_chars"]


def test_billed_chars_counted_before_redaction(tmp_path):
    """计费字符按送去合成的原文算：原文里的姓名（汉字算 2）打码后变成 *（算 1），trace 里仍是原文的计费数。"""
    env = _env(tmp_path)
    tk = G.VoiceBudget().reserve(0.0)
    t = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=env,
                     usage_fn=lambda: dict(tk.usage), calls_fn=tk.kinds)
    t.observe({"type": "scammer", "text": "你是谁", "turn": 1, "tactics": [], "newIntel": []})
    said = "我叫王小红"
    tk.tts(len(said), text=said)
    t.observe({"type": "bot", "text": said, "intent": "x"})
    t.end("x")
    rows = _lines(t.path)
    turn = next(r for r in rows if r["type"] == "turn")
    assert "王小红" not in turn["reply"]
    c = next(r for r in rows if r["type"] == "call")
    assert c["tts_billed_chars"] == 10 and G.tts_billed_chars(turn["reply"]) < 10


def test_usage_with_no_turn_goes_to_tail_rows(tmp_path):
    """只有开场白、对方一句没说完就挂断：没有 turn 行，用量记成 tail 调用行（turn=0），合计照样对得上。"""
    tk = G.VoiceBudget().reserve(0.0)
    t = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=_env(tmp_path),
                     usage_fn=lambda: dict(tk.usage), calls_fn=tk.kinds)
    tk.tag("喂？哪位", "opening")
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    tk.tts(4, text="喂？哪位")
    tk.asr(2.0)
    t.end("client_hangup")
    rows = _lines(t.path)
    calls = [r for r in rows if r["type"] == "call"]
    assert {(c["turn"], c["kind"], c["tail"]) for c in calls} == {(0, "opening", True), (0, "asr", True)}
    assert sum(c["tts_billed_chars"] for c in calls) == rows[-1]["usage_total"]["tts_billed_chars"] == 7


def test_sip_end_row_channel_phone(tmp_path):
    t, _ = _call(_env(tmp_path), channel="phone")
    end = _lines(t.path)[-1]
    assert end["channel"] == "phone" and end["consent"] == TR.SIP_CONSENT
    assert any(r["type"] == "call" for r in _lines(t.path))


def test_no_meter_no_call_rows(tmp_path):
    t = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="rule", env=_env(tmp_path))
    t.observe({"type": "scammer", "text": "你好", "turn": 1, "tactics": [], "newIntel": []})
    t.observe({"type": "bot", "text": "谁啊", "intent": "x"})
    t.end("x")
    rows = _lines(t.path)
    assert not [r for r in rows if r["type"] == "call"] and rows[-1]["usage_total"]["tts_billed_chars"] == 0


def test_usage_by_day_by_kind_and_cli(tmp_path, capsys):
    env = _env(tmp_path)
    t, tk = _call(env)
    day = TR.usage_by_day(env=env)["days"][0]
    assert day["tts_billed_chars"] == tk.usage["tts_billed_chars"]
    bk = day["by_kind"]
    assert bk["reply"]["prompt_tokens"] == 1700 and bk["farewell"]["rows"] == 1
    assert sum(v["tts_chars"] for v in bk.values()) == day["tts_chars"]
    from voice import trace_cli
    os.environ["TRACE_DIR"] = env["TRACE_DIR"]
    try:
        assert trace_cli.main([t.id]) == 0
        out = capsys.readouterr().out
        assert "调用 #1 reply: llm 800/30 tokens（qwen-flash）" in out and "调用 #3 farewell" in out
        assert "（计费 " in out
    finally:
        os.environ.pop("TRACE_DIR", None)


# ---- cost.py：v3 优先，v2 照读 ----
def _v2_trace(d: Path, tid="AAAAAAAA"):
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"schema_version": 2, "call_id": tid, "type": "start", "t": "2026-10-19T09:00:00.000+08:00", "id": tid,
             "channel": "web", "consent": True, "model": "qwen3.7-flash", "asr_model": "paraformer-realtime-v2",
             "tts_model": "cosyvoice-v3-flash", "tts_voice": "longlaoyi_v3"},
            {"schema_version": 2, "call_id": tid, "type": "end", "t": "2026-10-19T09:01:00.000+08:00",
             "reason": "client_hangup", "model": "qwen3.7-flash", "tts_voice": "longlaoyi_v3",
             "usage_total": {"llm_in_tokens": 1000, "llm_out_tokens": 50, "asr_audio_sec": 10.0, "tts_chars": 20},
             "usage": {"asr_sec": 10.0, "tts_chars": 20, "llm_in": 1000, "llm_out": 50}}]
    (d / f"{tid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_cost_reads_v2_and_v3(tmp_path):
    env = _env(tmp_path)
    t, tk = _call(env)
    d = tmp_path / "traces"
    _v2_trace(d)
    recs, info = C.read_traces(d)
    assert info["calls"] == 2
    v2 = next(r for r in recs if r["call_id"] == "AAAAAAAA")
    v3 = next(r for r in recs if r["call_id"] == t.id)
    assert v2["schema_version"] == 2 and v2["tts_billed_chars"] is None and v2["llm_in"] == 1000 and "call_kinds" not in v2
    assert C.billed_chars(v2) == (40, True)  # v2 没有计费字符：按 tts_chars×2 估算
    assert v3["schema_version"] == 3 and v3["llm_in"] == 1700 and v3["llm_out"] == 55 and v3["asr_sec"] == 8.5
    assert v3["tts_billed_chars"] == tk.usage["tts_billed_chars"] and C.billed_chars(v3)[1] is False
    assert (v3["asr_model"], v3["tts_model"], v3["tts_voice"], v3["llm_model"]) == ("asr-x", "tts-x", "v-wang", "qwen-flash")
    ck = v3["call_kinds"]
    assert set(ck) == {"disclosure", "opening", "asr", "filler", "reply", "farewell"}
    assert sum(k["tts_billed_chars"] for k in ck.values()) == v3["tts_billed_chars"]
    assert sum(k["llm_in"] for k in ck.values()) == v3["llm_in"]

    rep = C.build_report("2026-10-19", traces=d, data=tmp_path / "data", env={})
    assert rep["counts"]["calls"] == 2 and rep["counts"]["llm_in"] == 2700
    assert rep["counts"]["tts_chars_billed"] == 40 + tk.usage["tts_billed_chars"] and rep["tts_estimated"] is True
    # v3 按用途拆开的金额之和 = 这通的金额（同样的单价）
    c3 = C.price_record(v3, {})
    whole = c3["llm_in"] + c3["llm_out"] + c3["asr"] + c3["tts"]
    assert abs(sum(v["cny"] for v in rep["by_call_kind"].values()) - whole) < 1e-5
    assert "v3 调用行按用途" in C.format_text(rep)


def test_probe_barge_clip_and_flag():
    import numpy as np
    from voice import probe as P

    rate = 16000
    tone = (np.sin(np.arange(rate) / 5) * 3000).astype("int16").tobytes()  # 1 秒有声
    pcm = b"\x00\x00" * rate + tone + b"\x00\x00" * rate + tone
    clip = P.barge_clip(pcm)
    assert 1.1 <= len(clip) / (2 * rate) <= 1.3 and P.barge_clip(b"\x00\x00" * rate) == b""
    import argparse  # noqa: F401  --barge-in 在帮助里
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            P.main(["--help"])
        except SystemExit:
            pass
    assert "--barge-in" in buf.getvalue()
