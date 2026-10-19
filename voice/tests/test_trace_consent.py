"""#96：没勾选同意的网页通话，trace 只存编号、时间、人设、渠道和用量 / 延迟字段，不存任何文字；
「这通有问题」只记编号和标记；线上旧记录可用 scrub_no_consent 清掉文字（dry-run → apply）。全部离线。"""
import json
import os
import time
from pathlib import Path

from voice import trace as TR

# 没同意的通话里允许出现的字符串字段（编号、时间、人设、渠道、模型、音色、版本、枚举）；其余字符串一律算文字
ALLOWED_STR = {"type", "t", "ts", "started_at", "ended_at", "id", "call_id", "channel", "persona", "persona_id",
               "scenario", "model", "engine", "asr_model", "tts_model", "tts_voice", "code", "promptVersion", "fk",
               "reason", "exit_reason", "kind", "during", "stage", "ice", "conn", "gather", "path", "scrubbed_at"}
SECRET_WORDS = ("客服", "卡号", "6222", "3445", "张", "答非所问", "喂", "哪位", "别催", "嗯", "说明")


def _env(tmp_path, **kw):
    e = {"TRACE_DIR": str(tmp_path / "traces"), "TRACE_MIN_FREE_MB": "0"}
    e.update({k: str(v) for k, v in kw.items()})
    return e


def _lines(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


def _walk_strings(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def _assert_no_text(path):
    raw = Path(path).read_text(encoding="utf-8")
    for w in SECRET_WORDS:
        assert w not in raw, w
    for r in _lines(path):
        for k, v in _walk_strings(r):
            assert k in ALLOWED_STR, (r.get("type"), k, v)
        assert not set(TR.TEXT_FIELDS.get(r.get("type"), ())) & set(r), r


def _talk(t):
    t.observe({"type": "bot", "text": "我先说明一下", "intent": "disclosure"})
    t.observe({"type": "bot", "text": "喂？哪位", "intent": "opening"})
    t.observe({"type": "scammer", "text": "我是客服张伟，卡号6222020200112233445", "turn": 1, "intent": "confirm_intel",
               "tactics": [{"id": "cs_impersonation", "label": "冒充客服"}],
               "newIntel": [{"type": "bank_card", "label": "银行卡号", "masked": "6222 **** 3445"}]})
    t.observe({"type": "filler", "text": "嗯…"})
    t.observe({"type": "latency", "turn": 1, "asr": 300, "llm_ttft": 400, "first_audible": 500})
    t.observe({"type": "llm_done", "full_ms": 800})
    t.observe({"type": "bot", "text": "卡号再说一遍", "intent": "confirm_intel"})
    t.observe({"type": "interrupt"})
    t.observe({"type": "scammer", "text": "别催", "turn": 2, "intent": "urgency_stall", "tactics": [], "newIntel": []})
    t.observe({"type": "bot", "text": "别催我", "intent": "urgency_stall"})
    t.observe({"type": "bot", "text": "我先挂了", "intent": "hangup"})


def _call(env, consent):
    usage = {"asr_sec": 3.0, "tts_chars": 9, "llm_in": 500, "llm_out": 20}
    t = TR.CallTrace(channel="web", consent=consent, persona="wang", scenario="refund", model="qwen-flash", env=env,
                     tts_voice="v-wang", asr_model="asr-x", tts_model="tts-x", usage_fn=lambda: dict(usage),
                     feedback_key="k")
    _talk(t)
    t.end("client_hangup", usage=dict(usage), cost_cny=0.001)
    return t


def test_no_consent_trace_has_no_text_but_keeps_usage(tmp_path):
    env = _env(tmp_path)
    t = _call(env, consent=False)
    _assert_no_text(t.path)
    rows = _lines(t.path)
    st, end = rows[0], rows[-1]
    assert st["text_stored"] is False and st["persona"] == "wang" and st["channel"] == "web" and st["consent"] is False
    assert st["tts_voice"] == "v-wang" and st["model"] == "qwen-flash"
    turns = [r for r in rows if r["type"] == "turn"]
    assert len(turns) == 2 and turns[0]["interrupted"] is True and turns[0]["llm_full_ms"] == 800
    assert turns[0]["llm_in_tokens"] == 500 and turns[0]["latency"]["first_audible"] == 500
    assert [r["kind"] for r in rows if r["type"] == "bot"] == ["disclosure", "opening", "hangup"]
    assert end["usage_total"]["llm_in_tokens"] == 500 and end["exit_reason"] == "client_hangup"
    # 用量照样能汇总
    day = TR.usage_by_day(env=env)["days"][0]
    assert day["calls"] == 1 and day["llm_in_tokens"] == 500 and day["consent_calls"] == 0


def test_consent_trace_keeps_text(tmp_path):
    t = _call(_env(tmp_path), consent=True)
    rows = _lines(t.path)
    assert rows[0]["text_stored"] is True
    t1 = next(r for r in rows if r["type"] == "turn")
    assert "客服" in t1["asr"] and t1["reply"] and t1["intent"] == "confirm_intel" and t1["intel"]


def test_no_consent_feedback_only_id_and_flag(tmp_path):
    env = _env(tmp_path)
    off = _call(env, consent=False)
    assert TR.feedback(off.id, "第2轮答非所问，他说他叫张伟", 2, env=env, key="k") == {"ok": True}
    fb = [r for r in _lines(off.path) if r["type"] == "feedback"]
    assert fb == [{"schema_version": TR.SCHEMA_VERSION, "call_id": off.id, "type": "feedback", "t": fb[0]["t"],
                   "flagged": True}]
    _assert_no_text(off.path)
    fl = TR.list_traces(env=env, flagged=True)
    assert fl[0]["id"] == off.id and fl[0]["notes"][0]["note"] == "" and fl[0]["notes"][0]["turn"] is None
    # 同意的通话照旧带说明
    on = _call(env, consent=True)
    assert TR.feedback(on.id, "第2轮答非所问", 2, env=env, key="k") == {"ok": True}
    fb = [r for r in _lines(on.path) if r["type"] == "feedback"][0]
    assert fb["note"] == "第2轮答非所问" and fb["turn"] == 2


def test_no_consent_client_report_drops_strings(tmp_path):
    env = _env(tmp_path)
    off = _call(env, consent=False)
    TR.client_report(off.id, "ice_failed", "代理拦截了 1.2.3.4", {"browser": "Chrome", "error": "说明", "ice": "failed",
                                                             "elapsedMs": 5}, env=env)
    _assert_no_text(off.path)


def test_sip_still_text_only(tmp_path):
    t = TR.CallTrace(channel="phone", consent=None, persona="wang", scenario="refund", model="m", env=_env(tmp_path))
    _talk(t)
    t.end("caller_hangup")
    assert any(r.get("asr") for r in _lines(t.path) if r["type"] == "turn")  # 电话线路行为不变（只存脱敏文字）


def _legacy_no_consent(env):
    """模拟 b17b8da 写下的没同意通话：文字照存。"""
    t = _call(env, consent=True)
    rows = _lines(t.path)
    rows[0]["consent"] = False
    rows[0].pop("text_stored", None)
    for r in rows:
        if "consent" in r:
            r["consent"] = False
    rows.append({"schema_version": 2, "call_id": t.id, "type": "feedback", "t": TR.iso(), "flagged": True,
                 "note": "答非所问", "turn": 2})
    t.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return t


def test_scrub_dry_run_then_apply(tmp_path):
    env = _env(tmp_path)
    old = _legacy_no_consent(env)
    keep = _call(env, consent=True)              # 同意的不动
    clean = _call(env, consent=False)            # 已经不含文字的不动
    past = time.time() - 5 * 86400
    os.utime(old.path, (past, past))
    before_keep = keep.path.read_bytes()
    n_text = sum(1 for r in _lines(old.path) if set(TR.TEXT_FIELDS.get(r["type"], ())) & set(r))
    dry = TR.scrub_no_consent(env)
    assert dry["apply"] is False and dry["files"] == 1 and dry["rows"] == n_text and dry["paths"] == [str(old.path)]
    assert dry["skipped_consent"] == [keep.id] and dry["already_clean"] == 1 and dry["scanned"] == 3
    assert "客服" in old.path.read_text(encoding="utf-8")  # dry-run 不改
    done = TR.scrub_no_consent(env, apply=True)
    assert done["files"] == 1 and done["rows"] == n_text
    _assert_no_text(old.path)
    rows = _lines(old.path)
    assert rows[0]["text_stored"] is False and rows[0]["scrubbed_at"]
    assert rows[-2]["type"] == "end" and rows[-2]["usage_total"]["llm_in_tokens"] == 500   # 用量保留
    assert [r["type"] for r in rows if r["type"] == "turn"] == ["turn", "turn"]
    assert oct(os.stat(old.path).st_mode & 0o777) == "0o600" and abs(os.stat(old.path).st_mtime - past) < 1
    assert keep.path.read_bytes() == before_keep and "客服" in keep.path.read_text(encoding="utf-8")
    assert not list((tmp_path / "traces").glob("*.scrub"))
    assert TR.scrub_no_consent(env)["files"] == 0                # 再跑一次：没有要清的
    assert clean.id not in json.dumps(dry)


def test_scrub_never_touches_consented_or_recorded_calls(tmp_path):
    """负责人要求：已同意的一个都不能碰——任何一行 consent=true、end 行不是 consent=false、有录音的都跳过。"""
    env = _env(tmp_path)
    mixed = _legacy_no_consent(env)  # start 写成 false，但 end 改回 true
    rows = _lines(mixed.path)
    rows[-2]["consent"] = True
    mixed.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    rec = _legacy_no_consent(env)    # 没同意的记录，但有录音文件
    (tmp_path / "traces" / f"{rec.id}-scammer.ogg").write_bytes(b"x")
    before = {p.name: p.read_bytes() for p in (tmp_path / "traces").iterdir()}
    rep = TR.scrub_no_consent(env, apply=True)
    assert rep["files"] == 0 and sorted(rep["skipped_consent"]) == sorted([mixed.id, rec.id])
    assert {p.name: p.read_bytes() for p in (tmp_path / "traces").iterdir()} == before


def test_scrub_skips_calls_in_progress(tmp_path):
    env = _env(tmp_path)
    t = TR.CallTrace(channel="web", consent=True, persona="wang", scenario="refund", model="m", env=env)
    _talk(t)
    t._flush(); t._drain(all_=True)
    rows = _lines(t.path)
    for r in rows:
        if "consent" in r:
            r["consent"] = False
    t.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    rep = TR.scrub_no_consent(env, apply=True)
    assert rep["skipped_busy"] == [t.id] and rep["files"] == 0
    rep = TR.scrub_no_consent(env, apply=True, now=time.time() + 600)
    assert rep["files"] == 1


def test_scrub_cli(tmp_path, capsys):
    env = _env(tmp_path)
    _legacy_no_consent(env)
    from voice import trace_cli
    os.environ["TRACE_DIR"] = env["TRACE_DIR"]
    try:
        assert trace_cli.main(["--scrub-no-consent"]) == 0
        assert json.loads(capsys.readouterr().out)["apply"] is False
        assert trace_cli.main(["--scrub-no-consent", "--apply"]) == 0
        assert json.loads(capsys.readouterr().out)["files"] == 1
        assert trace_cli.main(["--scrub-no-consent"]) == 0
        assert json.loads(capsys.readouterr().out)["files"] == 0
    finally:
        os.environ.pop("TRACE_DIR", None)
