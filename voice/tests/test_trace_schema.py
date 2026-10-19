"""通话追踪 schema（#5，供 #18 磁盘监控、#20 成本监控共用）：每轮字段、每通汇总、用量增量、打断、
脱敏（银行卡/姓名/身份证/QQ/微信/支付宝）、录音目录与保留天数、trace_cli --flagged / --usage。全部离线。"""
import json
import os
import re
import time
from pathlib import Path

from voice import trace as TR

ROOT = Path(__file__).resolve().parents[2]
CARD = "6222020200112233445"
IDCARD = "110101199003071234"
QQ = "123456789"
WX = "wx_scam8899"
ALIPAY = "scam_pay@163.com"
NAME = "张伟"


def _env(tmp_path, **kw):
    e = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0"}
    e.update({k: str(v) for k, v in kw.items()})
    return e


def _lines(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def _call(env, consent=True, clock=None):
    usage = {"asr_sec": 0.0, "tts_chars": 0, "llm_in": 0, "llm_out": 0}
    clock = clock or Clock()
    t = TR.CallTrace(channel="web", consent=consent, persona="wang", scenario="refund", model="qwen-flash",
                     env=env, clock=clock, tts_voice="v-wang", asr_model="asr-x", tts_model="tts-x",
                     usage_fn=lambda: dict(usage), feedback_key="key")
    usage.update(tts_chars=4)  # 开场白
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    t.observe({"type": "scammer", "text": f"我叫{NAME}，是客服，卡号{CARD}", "turn": 1, "intent": "confirm_intel",
               "tactics": [], "newIntel": []})
    t.observe({"type": "latency", "turn": 1, "asr": 300, "llm_ttft": 420, "first_audible": 500, "e2e_reply": 1500})
    t.observe({"type": "llm_done", "full_ms": 900})
    usage.update(asr_sec=6.5, tts_chars=14, llm_in=800, llm_out=30)
    t.observe({"type": "bot", "text": "啊？卡号你再说一遍", "intent": "confirm_intel"})
    t.observe({"type": "interrupt"})  # 人设还在说，对方开口
    clock.t += 20
    t.observe({"type": "scammer", "text": f"身份证{IDCARD}，加我QQ {QQ}，微信 {WX}，支付宝 {ALIPAY}", "turn": 2,
               "intent": "urgency_stall", "tactics": [], "newIntel": []})
    usage.update(asr_sec=11.0, tts_chars=30, llm_in=1700, llm_out=55)
    t.observe({"type": "bot", "text": "别催，我找纸笔", "intent": "urgency_stall"})
    clock.t += 10
    usage.update(asr_sec=12.0, tts_chars=40)  # 告别语
    t.end("client_hangup", usage=dict(usage), cost_cny=0.0123)
    return t


TURN_FIELDS = ("schema_version", "call_id", "turn", "ts", "persona_id", "model", "llm_in_tokens", "llm_out_tokens",
               "llm_first_token_ms", "llm_full_ms", "asr_audio_sec", "tts_chars", "tts_voice", "interrupted")
END_FIELDS = ("schema_version", "call_id", "started_at", "ended_at", "duration_sec", "exit_reason", "consent",
              "turns", "interrupted_turns", "usage_total", "cost_cny")


def test_turn_and_end_schema_fields(tmp_path):
    t = _call(_env(tmp_path))
    rows = _lines(t.path)
    assert all(r["schema_version"] == TR.SCHEMA_VERSION == 2 and r["call_id"] == t.id for r in rows)
    st = rows[0]
    assert st["type"] == "start" and st["persona_id"] == "wang" and st["tts_voice"] == "v-wang"
    assert st["asr_model"] == "asr-x" and st["tts_model"] == "tts-x" and st["fk"] and "key" not in json.dumps(st)
    t1, t2 = [r for r in rows if r["type"] == "turn"]
    for f in TURN_FIELDS:
        assert f in t1 and f in t2, f
    assert (t1["turn"], t2["turn"]) == (1, 2) and t1["ts"] == t1["t"]
    assert t1["model"] == "qwen-flash" and t1["persona_id"] == "wang" and t1["tts_voice"] == "v-wang"
    assert (t1["llm_first_token_ms"], t1["llm_full_ms"]) == (420, 900)
    # 每轮用量 = 上一轮收尾到本轮收尾之间的增量
    assert (t1["llm_in_tokens"], t1["llm_out_tokens"], t1["asr_audio_sec"], t1["tts_chars"]) == (800, 30, 6.5, 14)
    # 最后一轮在挂断时收尾，含挂断前的告别语
    assert (t2["llm_in_tokens"], t2["llm_out_tokens"], t2["asr_audio_sec"], t2["tts_chars"]) == (900, 25, 5.5, 26)
    assert t1["interrupted"] is True and t2["interrupted"] is False
    end = rows[-1]
    for f in END_FIELDS:
        assert f in end, f
    assert end["exit_reason"] == "client_hangup" and end["duration_sec"] == 30.0 and end["consent"] is True
    assert end["usage_total"] == {"llm_in_tokens": 1700, "llm_out_tokens": 55, "asr_audio_sec": 12.0, "tts_chars": 40}
    assert end["interrupted_turns"] == 1 and end["turns"] == 2 and end["cost_cny"] == 0.0123
    assert end["started_at"] == st["started_at"] and end["ended_at"] > end["started_at"]


def test_text_redacted_on_disk_card_name_id_qq_wechat_alipay(tmp_path):
    t = _call(_env(tmp_path), consent=False)
    raw = t.path.read_text(encoding="utf-8")
    for secret in (CARD, IDCARD, QQ, WX, ALIPAY, NAME):
        assert secret not in raw, secret
    t1, t2 = [r for r in _lines(t.path) if r["type"] == "turn"]
    assert "张*" in t1["asr"] and "622202" in t1["asr"] and "3445" in t1["asr"]
    assert "110101********1234" in t2["asr"] and "@163.com" in t2["asr"]
    # 页面提交的说明也脱敏
    assert TR.feedback(t.id, f"他说他叫{NAME}，QQ {QQ}", env=_env(tmp_path), key="key", now=t.t0 + 60) == {"ok": True}
    assert NAME not in t.path.read_text(encoding="utf-8") and QQ not in t.path.read_text(encoding="utf-8")


def test_redact_self_names_keeps_titles():
    assert TR.redact("我是李明警官") == "我是李*警官"
    assert TR.redact("我是王经理") == "我是王经理"   # 称呼不是姓名
    assert TR.redact("姓名是王小红") == "姓名是王**"
    assert TR.redact("我是工商银行客服") == "我是工商银行客服"
    assert TR.redact("收款人王小红") == "收款人王**"  # 共享规则照常生效


def test_interrupt_without_reply_writes_event(tmp_path):
    t = TR.CallTrace(channel="web", consent=False, persona="wang", scenario="refund", model="m", env=_env(tmp_path))
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    t.observe({"type": "interrupt"})
    t.end("x")
    ev = [r for r in _lines(t.path) if r["type"] == "interrupt"]
    assert ev and ev[0]["during"] == "opening"


def test_no_usage_fn_gives_zero_usage(tmp_path):
    t = TR.CallTrace(channel="web", consent=False, persona="wang", scenario="refund", model="rule", env=_env(tmp_path))
    t.observe({"type": "scammer", "text": "你好", "turn": 1, "tactics": [], "newIntel": []})
    t.observe({"type": "bot", "text": "谁啊", "intent": "x"})
    t.end("x")
    turn = next(r for r in _lines(t.path) if r["type"] == "turn")
    assert (turn["llm_in_tokens"], turn["asr_audio_sec"], turn["tts_chars"]) == (0, 0.0, 0)
    assert turn["llm_full_ms"] is None and turn["interrupted"] is False


def test_audio_dir_and_days_configurable(tmp_path):
    env = _env(tmp_path, TRACE_AUDIO_DIR=tmp_path / "audio", TRACE_AUDIO_DAYS=7, TRACE_DAYS=30)
    assert TR.audio_dir(env) == tmp_path / "audio" and TR.audio_days(env) == 7 and TR.days(env) == 30
    t = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=env)
    assert t.audio_path("scammer").parent == tmp_path / "audio"
    (tmp_path / "audio").mkdir()
    ogg = tmp_path / "audio" / f"{t.id}-scammer.ogg"
    ogg.write_bytes(b"x")
    t.end("x")
    assert TR.load(t.id, env=env)["audio"]["scammer"]["file"] == str(ogg)
    assert TR.audio_file(t.id, "scammer", env=env) == ogg and TR.audio_file(t.id, "../x", env=env) is None
    past = time.time() - 10 * 86400  # 录音 7 天到期，文字 30 天还留着
    for p in (ogg, t.path):
        os.utime(p, (past, past))
    assert TR.cleanup(env) == 1 and not ogg.exists() and t.path.exists()
    # 默认：录音和文字同目录、同天数
    assert TR.audio_dir(_env(tmp_path)) == TR.trace_dir(_env(tmp_path)) and TR.audio_days(_env(tmp_path)) == 30
    d = TR.describe(env)
    assert d["audioDir"] == str(tmp_path / "audio") and d["audioDays"] == 7 and d["schema"] == 2


def test_usage_by_day_and_flagged(tmp_path, capsys):
    env = _env(tmp_path)
    day1 = Clock(1_790_000_000.0)  # 2026-09-21（UTC+8）
    a = _call(env, consent=True, clock=day1)
    b = _call(env, consent=False, clock=Clock(1_790_000_000.0 + 86400))
    assert TR.feedback(b.id, "第二轮答非所问", 2, env=env, key="key", now=1_790_000_000.0 + 86400 + 60) == {"ok": True}
    rep = TR.usage_by_day(env=env)
    assert rep["schema_version"] == 2 and [d["date"] for d in rep["days"]] == ["2026-09-21", "2026-09-22"]
    d1, d2 = rep["days"]
    assert d1["calls"] == 1 and d1["consent_calls"] == 1 and d2["consent_calls"] == 0 and d2["flagged_calls"] == 1
    assert d1["llm_in_tokens"] == 1700 and d1["llm_out_tokens"] == 55 and d1["asr_audio_sec"] == 12.0
    assert d1["tts_chars"] == 40 and d1["turns"] == 2 and d1["interrupted_turns"] == 1 and d1["duration_sec"] == 30.0
    assert d1["cost_cny"] == 0.0123 and d1["by_model"]["qwen-flash"]["llm_in_tokens"] == 1700
    assert d1["by_persona"] == {"wang": 1} and d1["exit_reasons"] == {"client_hangup": 1}
    assert TR.usage_by_day("2026-09-22", env=env)["days"] == [d2]
    assert TR.usage_by_day(until="2026-09-21", env=env)["days"] == [d1]
    fl = TR.list_traces(env=env, flagged=True)
    assert [r["id"] for r in fl] == [b.id] and fl[0]["notes"][0]["note"] == "第二轮答非所问"
    assert fl[0]["notes"][0]["turn"] == 2 and a.id not in json.dumps(fl)

    from voice import trace_cli
    os.environ["TRACE_DIR"] = env["TRACE_DIR"]
    try:
        assert trace_cli.main(["--usage", "--since", "2026-09-01"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out == {**rep, "generated_at": out["generated_at"]}
        assert trace_cli.main(["--flagged", "--json"]) == 0
        assert [r["id"] for r in json.loads(capsys.readouterr().out)] == [b.id]
        assert trace_cli.main(["--flagged"]) == 0
        text = capsys.readouterr().out
        assert b.id in text and "第 2 轮 第二轮答非所问" in text
        assert trace_cli.main([a.id]) == 0
        text = capsys.readouterr().out
        assert "用量: llm 800/30 tokens" in text and "被打断" in text and "llm整句=900ms" in text and "约 0.0123 元" in text
    finally:
        os.environ.pop("TRACE_DIR", None)


def test_usage_by_day_v1_and_unfinished_calls(tmp_path):
    """旧格式（v1，end.usage 为 Ticket.usage 原样）和没写 end 的通话也能汇总。"""
    env = _env(tmp_path)
    d = tmp_path / "traces"
    d.mkdir()
    (d / "AAAAAAAA.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "start", "t": "2026-10-18T10:00:00.000+08:00", "consent": True, "channel": "web", "persona": "lin",
         "model": "m"},
        {"type": "end", "t": "2026-10-18T10:01:00.000+08:00", "reason": "x", "turns": 3,
         "usage": {"asr_sec": 5.0, "tts_chars": 10, "llm_in": 100, "llm_out": 5}}]) + "\n")
    (d / "BBBBBBBB.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"type": "start", "t": "2026-10-18T11:00:00.000+08:00", "consent": False, "channel": "web", "persona": "lin"},
        {"type": "turn", "n": 1, "llm_in_tokens": 7, "llm_out_tokens": 1, "asr_audio_sec": 1.5, "tts_chars": 2}]) + "\n")
    day = TR.usage_by_day(env=env)["days"][0]
    assert day["calls"] == 2 and day["llm_in_tokens"] == 107 and day["asr_audio_sec"] == 6.5 and day["turns"] == 4
    assert day["exit_reasons"] == {"x": 1, "unfinished": 1}


def test_schema_doc_lists_every_field():
    doc = (ROOT / "docs" / "TRACE_SCHEMA.md").read_text(encoding="utf-8")
    assert f"schema_version = {TR.SCHEMA_VERSION}" in doc or f"`schema_version` | 整数 | {TR.SCHEMA_VERSION}" in doc
    for f in TURN_FIELDS + END_FIELDS + ("TRACE_DIR", "TRACE_DAYS", "TRACE_AUDIO_DIR", "TRACE_AUDIO_DAYS",
                                         "TRACE_FEEDBACK_HOURS", "flagged", "--usage", "--flagged"):
        assert f"`{f}`" in doc, f
    assert not re.search(r"deepseek", doc, re.I)
