"""voice/cost.py：按天汇总成本（GitHub #20）。全部是合成数据，不读真实 trace。"""
import json
from pathlib import Path

import pytest

from voice import cost as C

ASR = 0.00024          # paraformer-realtime-v2 元/秒
FLASH = (0.2, 0.8)     # qwen3.7-flash 元/百万 token
PLUS = (0.8, 2.0)      # qwen-plus（旧 trace 记账）
F38 = (0.8, 2.7)       # qwen3.8-flash，文字代理默认（#148）


def trace(d: Path, tid: str, end_t: str, usage: dict, start_t: str = None, model="qwen3.7-flash",
          channel="web", **end_extra):
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "start", "t": start_t or end_t, "id": tid, "channel": channel, "consent": True, "model": model},
            {"type": "turn", "n": 1, "asr": "（脱敏文本）", "reply": "喂？"},
            {"type": "end", "t": end_t, "reason": "client_hangup", "turns": 1, "usage": usage, **end_extra}]
    (d / f"{tid}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def usage_rows(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def U(asr=0.0, tts=0, li=0, lo=0):
    return {"asr_sec": asr, "tts_chars": tts, "llm_in": li, "llm_out": lo}


def report(tmp_path, day="2026-10-19", env=None, **kw):
    paths = {"traces": tmp_path / "traces", "data": tmp_path / "data", "usage": tmp_path / "data" / "voice" / "voice-usage.jsonl",
             "chat_budget": tmp_path / "data" / "chat-budget.json", "baseline": tmp_path / "data" / "cost-baseline.json",
             "eval_spend": tmp_path / "eval-spend.csv"}
    paths.update(kw)
    return C.build_report(day, env={} if env is None else env, **paths)


def test_bucket_by_end_time_in_plus8(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-18T23:59:30.000+08:00", U(asr=10))
    # 跨零点：开始在 18 日，结束在 19 日 → 记 19 日
    trace(t, "BBBBBBBB", "2026-10-19T00:00:10.000+08:00", U(asr=20), start_t="2026-10-18T23:58:00+08:00")
    trace(t, "CCCCCCCC", "2026-10-18T16:30:00Z", U(asr=40))  # UTC 16:30 = +08:00 次日 00:30
    trace(t, "DDDDDDDD", "2026-10-19T12:00:00+08:00", U(asr=0))
    (t / "notatrace.jsonl").write_text('{"type":"end","t":"2026-10-19T01:00:00+08:00","usage":{"asr_sec":999}}\n')
    r18, r19 = report(tmp_path, "2026-10-18"), report(tmp_path)
    assert r18["counts"]["calls"] == 1 and r18["counts"]["asr_sec"] == 10
    assert r19["counts"]["calls"] == 3 and r19["counts"]["asr_sec"] == 60
    assert r19["items"]["asr"] == pytest.approx(60 * ASR, abs=1e-4)


def test_missing_files_are_skipped_and_reported(tmp_path):
    r = report(tmp_path)
    assert r["total_list"] == 0 and r["counts"]["calls"] == 0
    s = r["sources"]
    assert not any(s[k]["found"] for k in ("traces", "voice_usage", "voice_budget", "chat_budget", "eval_spend", "baseline"))
    assert r["baseline"] == {"found": False}
    text = C.format_text(r)
    assert "跳过（文件不存在）" in text and "voice-usage.jsonl" in text and "cost-baseline.json" in text


def test_tts_estimate_vs_billed_chars(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-19T10:00:00+08:00", U(tts=100))  # 无计费字段 → ×2 估算，未知模型按 1 元/万字
    r = report(tmp_path)
    assert r["tts_estimated"] is True and r["counts"]["tts_chars_billed"] == 200
    assert r["items"]["tts"] == pytest.approx(200 * 1.0 / 10000)
    assert "估算" in C.format_text(r)
    # 新字段 tts_billed_chars 优先；旧名 tts_billable_chars 也认；设计音色按 v3.5-flash 0.8 元/万字
    trace(t, "AAAAAAAA", "2026-10-19T10:00:00+08:00", {**U(tts=100), "tts_billed_chars": 150},
          tts_model="cosyvoice-v3.5-flash")
    trace(t, "BBBBBBBB", "2026-10-19T10:05:00+08:00", {**U(tts=10), "tts_billable_chars": 18},
          tts_voice="cosyvoice-v3.5-flash-vd-abc123")
    r = report(tmp_path)
    assert r["tts_estimated"] is False and r["counts"]["tts_chars_billed"] == 168
    assert r["items"]["tts"] == pytest.approx(168 * 0.8 / 10000)
    # 环境变量覆盖全部 TTS 单价
    r = report(tmp_path, env={"PRICE_TTS_PER_10K_CHARS": "2"})
    assert r["items"]["tts"] == pytest.approx(168 * 2 / 10000)


def test_llm_priced_per_model_and_env_override(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-19T10:00:00+08:00", U(li=1_000_000, lo=100_000), model="qwen3.7-flash")
    trace(t, "BBBBBBBB", "2026-10-19T11:00:00+08:00", U(li=1_000_000, lo=100_000), model="qwen-plus")
    r = report(tmp_path)
    assert r["items"]["llm_in"] == pytest.approx(FLASH[0] + PLUS[0])
    assert r["items"]["llm_out"] == pytest.approx(0.1 * (FLASH[1] + PLUS[1]))
    r = report(tmp_path, env={"VOICE_PRICE_LLM_IN_PER_M": "1"})
    assert r["items"]["llm_in"] == pytest.approx(2.0)


def test_dedup_trace_and_voice_usage_and_group_by_kind(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-19T10:00:00+08:00", U(asr=30, tts=10), kind="web")
    usage_rows(tmp_path / "data" / "voice" / "voice-usage.jsonl", [
        # 同一通：只算一次，trace 缺的 tts_billed_chars 从这里补
        {"schema_version": 1, "call_id": "AAAAAAAA", "t": "2026-10-19T10:00:01+08:00", "kind": "web",
         "usage": {**U(asr=30, tts=10), "tts_billed_chars": 20}},
        # 不同意存储的通话：只在 voice-usage 里
        {"schema_version": 1, "call_id": "ZZZZZZZZ", "t": "2026-10-19T11:00:00+08:00", "kind": "web-noconsent",
         "asr_sec": 50, "tts_chars": 5, "tts_billed_chars": 9, "llm_in": 0, "llm_out": 0,
         "asr_model": "paraformer-realtime-v2", "tts_model": "cosyvoice-v3-flash"},
        {"call_id": "YYYYYYYY", "t": "2026-10-18T11:00:00+08:00", "kind": "phone", "asr_sec": 999},  # 别的日期
    ])
    r = report(tmp_path)
    assert r["counts"]["calls"] == 2 and r["counts"]["asr_sec"] == 80
    assert r["counts"]["tts_chars_billed"] == 29 and r["tts_estimated"] is False
    assert set(r["by_kind"]) == {"web", "web-noconsent"}
    assert r["by_kind"]["web-noconsent"]["calls"] == 1


def test_ledger_gap_counts_uncovered_calls(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-19T10:00:00+08:00", U(asr=100, tts=10, li=1000, lo=10))
    d = tmp_path / "data"
    d.mkdir()
    (d / "voice-budget.json").write_text(json.dumps({"day": "2026-10-19", "spent_cny": 999, "sessions": 3,
                                                     "asr_sec": 250, "tts_chars": 30, "llm_in": 3000, "llm_out": 30}))
    r = report(tmp_path)
    assert r["ledger_gap"]["counts"]["asr_sec"] == 150
    assert r["counts"]["asr_sec"] == 250 and r["counts"]["tts_chars_billed"] == 60
    assert "账本差额（未逐通记录）" in r["by_kind"]
    assert r["total_list"] < 1  # spent_cny=999 不参与计算
    # 账本是别的日期：不用
    r = report(tmp_path, "2026-10-20")
    assert r["ledger_gap"] is None and r["sources"]["voice_budget"]["used"] is False


def test_chat_budget_and_eval_spend(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "chat-budget.json").write_text(json.dumps({"day": "2026-10-19", "spentCny": 123, "calls": 4,
                                                    "inTokens": 1_000_000, "outTokens": 500_000, "refused": 0}))
    (tmp_path / "eval-spend.csv").write_text("date,role,pr,cny,note\n2026-10-19,voice,46,0.2,对比\n"
                                             "2026-10-19,corpus,68,0.25,复测\n2026-10-18,voice,40,9,昨天\n", encoding="utf-8")
    r = report(tmp_path)
    assert r["items"]["proxy"] == pytest.approx(F38[0] + 0.5 * F38[1])
    assert r["items"]["eval"] == pytest.approx(0.45)
    assert len(r["eval_rows"]) == 2


def test_asr_free_quota_monthly(tmp_path):
    t = tmp_path / "traces"
    trace(t, "AAAAAAAA", "2026-10-05T10:00:00+08:00", U(asr=35_990))
    trace(t, "BBBBBBBB", "2026-10-19T10:00:00+08:00", U(asr=100))
    trace(t, "CCCCCCCC", "2026-11-01T10:00:00+08:00", U(asr=100))
    trace(t, "DDDDDDDD", "2026-09-30T10:00:00+08:00", U(asr=50_000))  # 上个月，不占本月额度
    r = report(tmp_path)
    assert r["asr_free"]["covered_today_sec"] == 10
    assert r["asr_after_free"] == pytest.approx(90 * ASR, abs=1e-4)
    assert r["total_after_free"] == pytest.approx(r["total_list"] - 10 * ASR, abs=1e-4)
    r = report(tmp_path, "2026-11-01")  # 新的月份重新给 10 小时
    assert r["asr_after_free"] == 0 and r["items"]["asr"] > 0
    r = report(tmp_path, env={"COST_ASR_FREE_SEC_PER_MONTH": "0"})
    assert r["asr_after_free"] == r["items"]["asr"]


def _baseline(tmp_path, **kw):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    b = {"coupon_balance": 291.71, "as_of": "2026-10-18", "expires": "2026-12-02", "monthly_budget": 300, **kw}
    (d / "cost-baseline.json").write_text(json.dumps(b))


@pytest.mark.parametrize("spend,alert", [(146.0, False), (147.0, True)])  # 加上 18、19 日共 3 元：149 / 150
def test_baseline_balance_and_50pct_alert(tmp_path, spend, alert):
    _baseline(tmp_path)
    (tmp_path / "eval-spend.csv").write_text(f"date,role,pr,cny,note\n2026-10-02,x,1,{spend},月初\n"
                                             "2026-10-18,x,2,1,基准当天不扣\n2026-10-19,x,3,2,今天\n")
    r = report(tmp_path)
    b = r["baseline"]
    assert b["spent_since_as_of"] == pytest.approx(2)
    assert b["balance_est"] == pytest.approx(289.71)
    assert b["month_to_date"] == pytest.approx(spend + 3)
    assert b["month_pct"] == pytest.approx((spend + 3) / 3, abs=0.05) and b["alert"] is alert
    assert ("⚠" in C.format_text(r)) is b["alert"]


def test_alert_threshold_env_and_expiry(tmp_path):
    _baseline(tmp_path, expires="2026-10-18")
    (tmp_path / "eval-spend.csv").write_text("date,role,pr,cny,note\n2026-10-19,x,3,31,今天\n")
    r = report(tmp_path, env={"COST_ALERT_PCT": "10"})
    assert r["baseline"]["alert"] is True and r["baseline"]["expired"] is True
    r = report(tmp_path)
    assert r["baseline"]["alert"] is False


def test_example_baseline_file_shape():
    p = Path(C.__file__).resolve().parents[1] / "deploy" / "cost-baseline.example.json"
    b = json.loads(p.read_text(encoding="utf-8"))
    assert b == {"coupon_balance": 291.71, "as_of": "2026-10-18", "expires": "2026-12-02", "monthly_budget": 300}


def test_cli_json_and_text(tmp_path, capsys, monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith(("PRICE_", "VOICE_PRICE", "COST_", "DEEPSUCK_", "LLM_MODEL", "DATA_DIR", "TRACE_DIR")):
            monkeypatch.delenv(k, raising=False)
    trace(tmp_path / "traces", "AAAAAAAA", "2026-10-19T10:00:00+08:00", U(asr=60, tts=20, li=3000, lo=40))
    args = ["--day", "2026-10-19", "--traces", str(tmp_path / "traces"), "--data", str(tmp_path / "data"),
            "--eval-spend", str(tmp_path / "none.csv")]
    assert C.main(args + ["--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["counts"]["calls"] == 1 and j["sources"]["eval_spend"]["found"] is False
    assert C.main(args) == 0
    out = capsys.readouterr().out
    assert "当日成本 2026-10-19" in out and "语音识别 ASR" in out
    with pytest.raises(SystemExit):
        C.main(["--day", "19/10/2026"])
