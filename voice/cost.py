"""按天汇总语音演示的调用成本（GitHub #20）。只用标准库，单价复用 voice/guard.py。

    python -m voice.cost --day 2026-10-19 [--json] [--traces DIR] [--data DIR] [--usage FILE]
                         [--chat-budget FILE] [--baseline FILE] [--eval-spend FILE]

数据源（文件不存在就跳过，并在输出的 sources 里注明）：
  1. 通话追踪 TRACE_DIR/*.jsonl 的 end 行（usage、模型、音色、kind），按 end 时间的 +08:00 日期分桶。
  2. DATA_DIR/voice/voice-usage.jsonl：不同意存储的通话也写一行（不含内容，跨天保留）。
     同一 call_id 同时出现在 trace 和这里时只算一次（trace 为准，缺的字段从这里补）。
  3. DATA_DIR/voice-budget.json：guard 的当日账本，只有当天一份。作为全量计数参考：
     账本里某项计数比逐通记录之和大时，差额单列为「账本差额（未逐通记录）」计入当日合计。
  4. 文字代理的 chat-budget.json（PROXY_DATA_DIR 或 DATA_DIR）：当天的 inTokens/outTokens。
  5. 评测花费 CSV（表头 date,role,pr,cny,note），按 date 汇总。

金额一律用「计数 × 单价」重算，不用账本里的 spent_cny / spentCny。
TTS 按百炼规则一个汉字算 2 个字符：记录里有 tts_billed_chars（旧名 tts_billable_chars）就用它；
否则用 tts_chars × 2 估算（中文为主时接近上限），输出里标「估算」。
ASR（Paraformer 实时识别）另给扣每月 10 小时免费额度后的金额；估算余额和本月占比用扣额度后的数。

单价覆盖（环境变量）：LLM 同 guard.Prices.from_env（VOICE_PRICE_LLM_IN/OUT_PER_M、PRICE_LLM_TABLE 等）；
PRICE_ASR_PER_SEC；PRICE_TTS_PER_10K_CHARS（设了就覆盖所有 TTS 模型）；
COST_ASR_FREE_SEC_PER_MONTH（默认 36000）；COST_ALERT_PCT（默认 50）。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from . import guard as G

TZ = timezone(timedelta(hours=8))
ID_RE = re.compile(r"^[A-Z2-7]{8}$")
DEFAULT_EVAL_SPEND = "/workspace/deepsuck-costs/eval-spend.csv"
ASR_FREE_SEC_PER_MONTH = 36000  # paraformer-realtime-v2 每月 10 小时（每月 1 日发放）
DEFAULT_ASR_MODEL = "paraformer-realtime-v2"
# CosyVoice 单价（元 / 万字符，北京原价，2026-10-19 查询 https://help.aliyun.com/zh/model-studio/model-pricing）
TTS_PRICES_PER_10K: Dict[str, float] = {
    "cosyvoice-v3.5-plus": 1.5,
    "cosyvoice-v3.5-flash": 0.8,
    "cosyvoice-v3-plus": 2.0,
    "cosyvoice-v3-flash": 1.0,
    "cosyvoice-v2": 2.0,
}
UNKNOWN_TTS_PER_10K = 1.0  # 记录没写模型时按系统音色 cosyvoice-v3-flash 算（宁高勿低）
COUNTERS = ("asr_sec", "tts_chars", "llm_in", "llm_out")


# ---------------------------------------------------------------- 工具
def _env(env):
    return os.environ if env is None else env


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _fenv(env, key: str, default: float) -> float:
    return _f(_env(env).get(key), default) if _env(env).get(key) not in (None, "") else default


def cn_date(t) -> Optional[str]:
    """ISO 时间（带或不带时区，Z 也认）→ +08:00 的日期字符串；不带时区的按 +08:00。"""
    if not t:
        return None
    s = str(t).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ).strftime("%Y-%m-%d")


def _lines(path: Path) -> List[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def _read_json(path: Optional[Path]):
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def designed_model(voice: str) -> Optional[str]:
    """与 voice/dashscope_ws.designed_model 一致（这里不 import 它，免得拉进 websockets）。"""
    for mark in ("-vd-", "-vc-"):
        if voice and voice.startswith("cosyvoice-") and mark in voice:
            return voice.split(mark, 1)[0]
    return None


# ---------------------------------------------------------------- 记录
def _pick(row: Mapping, *keys):
    """按顺序在 row、row['usage']、row['models'] 里找第一个非空值。"""
    for src in (row, row.get("usage") or {}, row.get("models") or {}):
        if not isinstance(src, Mapping):
            continue
        for k in keys:
            v = src.get(k)
            if v not in (None, ""):
                return v
    return None


def make_record(row: Mapping, *, source: str, call_id: Optional[str] = None, start: Optional[Mapping] = None,
                fallback_day: Optional[str] = None) -> Optional[dict]:
    """一行 end（trace）或 voice-usage 记录 → 统一结构。缺字段降级为 None / 0。"""
    start = start or {}
    usage = row.get("usage") if isinstance(row.get("usage"), Mapping) else row
    day = cn_date(row.get("t") or row.get("ended") or row.get("end")) or fallback_day
    if not day:
        return None
    billed = _pick(row, "tts_billed_chars", "tts_billable_chars")
    rec = {
        "call_id": str(call_id or row.get("call_id") or row.get("id") or row.get("trace_id") or "") or None,
        "day": day,
        "source": source,
        "schema_version": row.get("schema_version", start.get("schema_version")),
        "kind": row.get("kind") or start.get("kind"),
        "channel": row.get("channel") or start.get("channel"),
        "llm_model": _pick(row, "llm_model", "model") or start.get("model"),
        "asr_model": _pick(row, "asr_model") or start.get("asr_model"),
        "tts_model": _pick(row, "tts_model") or start.get("tts_model"),
        "tts_voice": _pick(row, "tts_voice", "voice") or start.get("tts_voice"),
        "asr_sec": _f(usage.get("asr_sec")),
        "tts_chars": int(_f(usage.get("tts_chars"))),
        "tts_billed_chars": int(_f(billed)) if billed is not None else None,
        "llm_in": int(_f(usage.get("llm_in"))),
        "llm_out": int(_f(usage.get("llm_out"))),
    }
    if rec["llm_model"] == "rule":  # 规则引擎不调大模型
        rec["llm_model"] = None
    return rec


def read_traces(trace_dir: Optional[Path]) -> Tuple[List[dict], dict]:
    """TRACE_DIR/*.jsonl：每通取最后一个 end 行。"""
    info = {"path": str(trace_dir) if trace_dir else None, "found": False, "files": 0, "calls": 0}
    if trace_dir is None or not trace_dir.is_dir():
        return [], info
    info["found"] = True
    out = []
    for p in sorted(trace_dir.glob("*.jsonl")):
        if not ID_RE.match(p.stem):
            continue  # voice-usage.jsonl 等不是单通 trace
        info["files"] += 1
        rows = _lines(p)
        start = next((r for r in rows if r.get("type") == "start"), {})
        end = next((r for r in reversed(rows) if r.get("type") == "end"), None)
        if end is None:
            continue
        rec = make_record(end, source="trace", call_id=start.get("id") or p.stem, start=start,
                          fallback_day=cn_date(start.get("t")))
        if rec:
            out.append(rec)
    info["calls"] = len(out)
    return out, info


def read_usage(path: Optional[Path]) -> Tuple[List[dict], dict]:
    info = {"path": str(path) if path else None, "found": False, "rows": 0}
    if path is None or not path.is_file():
        return [], info
    info["found"] = True
    out = []
    for row in _lines(path):
        if row.get("type") not in (None, "usage", "end", "call"):
            continue
        rec = make_record(row, source="usage")
        if rec:
            out.append(rec)
    info["rows"] = len(out)
    return out, info


def merge_records(trace_recs: Iterable[dict], usage_recs: Iterable[dict]) -> List[dict]:
    """按 call_id 去重：trace 为准，trace 缺的字段（模型、音色、kind、tts_billed_chars）用 voice-usage 补。"""
    out: List[dict] = []
    by_id: Dict[str, dict] = {}
    for r in list(trace_recs) + list(usage_recs):
        cid = r.get("call_id")
        if cid and cid in by_id:
            base = by_id[cid]
            for k, v in r.items():
                if base.get(k) in (None, "") and v not in (None, ""):
                    base[k] = v
            base["source"] = "trace+usage" if base["source"] != r["source"] else base["source"]
            continue
        r = dict(r)
        out.append(r)
        if cid:
            by_id[cid] = r
    return out


# ---------------------------------------------------------------- 单价
def tts_price_per_char(model: Optional[str], voice: Optional[str] = None, env=None) -> float:
    e = _env(env)
    if e.get("PRICE_TTS_PER_10K_CHARS") not in (None, ""):
        return _f(e.get("PRICE_TTS_PER_10K_CHARS"), UNKNOWN_TTS_PER_10K) / 10000
    m = model or designed_model(voice or "")
    if m and m in TTS_PRICES_PER_10K:
        return TTS_PRICES_PER_10K[m] / 10000
    if m:
        hits = [k for k in TTS_PRICES_PER_10K if m.startswith(k)]
        if hits:
            return TTS_PRICES_PER_10K[max(hits, key=len)] / 10000
    return UNKNOWN_TTS_PER_10K / 10000


def llm_prices(model: Optional[str], env=None) -> Tuple[float, float]:
    p = G.Prices.from_env(model=model or None, env=_env(env))
    return p.llm_in_per_m, p.llm_out_per_m


def asr_price_per_sec(env=None) -> float:
    return _fenv(env, "PRICE_ASR_PER_SEC", G.Prices().asr_per_sec)


def proxy_prices(env=None) -> Tuple[str, float, float]:
    """文字代理：server/index.js 用 LLM_MODEL + PRICE_LLM_IN/OUT_PER_M（默认 qwen-plus 0.8 / 2）。"""
    e = _env(env)
    model = e.get("LLM_MODEL") or G.PROXY_LLM_MODEL
    p_in, p_out = G.llm_price(model, e)
    return model, _fenv(e, "PRICE_LLM_IN_PER_M", p_in), _fenv(e, "PRICE_LLM_OUT_PER_M", p_out)


# ---------------------------------------------------------------- 计算
def _r(x: float, n: int = 6) -> float:
    return round(x + 0.0, n)


def billed_chars(rec: Mapping) -> Tuple[int, bool]:
    """(计费字符数, 是否估算)。"""
    if rec.get("tts_billed_chars") is not None:
        return int(rec["tts_billed_chars"]), False
    return int(rec.get("tts_chars") or 0) * 2, True


def price_record(rec: Mapping, env=None) -> dict:
    p_in, p_out = llm_prices(rec.get("llm_model"), env) if (rec.get("llm_in") or rec.get("llm_out")) else (0.0, 0.0)
    chars, est = billed_chars(rec)
    return {
        "llm_in": rec.get("llm_in", 0) * p_in / 1e6,
        "llm_out": rec.get("llm_out", 0) * p_out / 1e6,
        "asr": rec.get("asr_sec", 0.0) * asr_price_per_sec(env),
        "tts": chars * tts_price_per_char(rec.get("tts_model"), rec.get("tts_voice"), env),
        "tts_chars_billed": chars,
        "tts_estimated": est and chars > 0,
    }


def _is_paraformer_realtime(model: Optional[str]) -> bool:
    return (model or DEFAULT_ASR_MODEL).startswith("paraformer-realtime")


def asr_free_seconds(env=None) -> float:
    return _fenv(env, "COST_ASR_FREE_SEC_PER_MONTH", ASR_FREE_SEC_PER_MONTH)


def _ledger_for(data_dir: Optional[Path], day: str) -> Tuple[Optional[dict], dict]:
    p = data_dir / "voice-budget.json" if data_dir else None
    info = {"path": str(p) if p else None, "found": bool(p and p.is_file()), "day": None, "used": False}
    j = _read_json(p)
    if not isinstance(j, dict):
        return None, info
    info["day"] = j.get("day")
    if j.get("day") != day:
        return None, info
    info["used"] = True
    return j, info


def _chat_for(path: Optional[Path], day: str) -> Tuple[Optional[dict], dict]:
    info = {"path": str(path) if path else None, "found": bool(path and path.is_file()), "day": None, "used": False}
    j = _read_json(path)
    if not isinstance(j, dict):
        return None, info
    info["day"] = j.get("day")
    if j.get("day") != day:
        return None, info
    info["used"] = True
    return j, info


def read_eval_spend(path: Optional[Path]) -> Tuple[List[dict], dict]:
    info = {"path": str(path) if path else None, "found": bool(path and path.is_file()), "rows": 0}
    if not info["found"]:
        return [], info
    rows = []
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                d = (r.get("date") or "").strip()
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    continue
                rows.append({"date": d, "role": (r.get("role") or "").strip(), "pr": (r.get("pr") or "").strip(),
                             "cny": _f(r.get("cny")), "note": (r.get("note") or "").strip()})
    except OSError:
        info["found"] = False
    info["rows"] = len(rows)
    return rows, info


class Sources:
    """一次加载所有文件，之后可以对任意日期计算（估算余额要逐日累加）。"""

    def __init__(self, *, traces: Optional[Path], data: Optional[Path], usage: Optional[Path],
                 chat_budget: Optional[Path], eval_spend: Optional[Path], env=None):
        self.env = env
        t_recs, self.trace_info = read_traces(traces)
        u_recs, self.usage_info = read_usage(usage)
        self.records = merge_records(t_recs, u_recs)
        self.data = data
        self.chat_path = chat_budget
        self.eval_rows, self.eval_info = read_eval_spend(eval_spend)

    def records_on(self, day: str) -> List[dict]:
        return [r for r in self.records if r["day"] == day]

    def asr_sec_before(self, day: str) -> float:
        """本月 1 日到 day 前一天的 ASR 秒数（只算 Paraformer 实时）。"""
        first = day[:8] + "01"
        return sum(r["asr_sec"] for r in self.records
                   if first <= r["day"] < day and _is_paraformer_realtime(r.get("asr_model")))


def compute_day(src: Sources, day: str) -> dict:
    env = src.env
    recs = src.records_on(day)
    items = {k: 0.0 for k in ("llm_in", "llm_out", "asr", "tts", "proxy", "eval")}
    counts = {"calls": len(recs), "asr_sec": 0.0, "tts_chars": 0, "tts_chars_billed": 0, "llm_in": 0, "llm_out": 0}
    tts_est = False
    kinds: Dict[str, dict] = {}
    asr_free_eligible = 0.0
    for r in recs:
        c = price_record(r, env)
        for k in ("llm_in", "llm_out", "asr", "tts"):
            items[k] += c[k]
        for k in ("asr_sec", "tts_chars", "llm_in", "llm_out"):
            counts[k] += r[k]
        counts["tts_chars_billed"] += c["tts_chars_billed"]
        tts_est = tts_est or c["tts_estimated"]
        if _is_paraformer_realtime(r.get("asr_model")):
            asr_free_eligible += r["asr_sec"]
        kname = r.get("kind") or r.get("channel") or "unknown"
        g = kinds.setdefault(kname, {"calls": 0, "cny": 0.0})
        g["calls"] += 1
        g["cny"] += c["llm_in"] + c["llm_out"] + c["asr"] + c["tts"]

    # 账本差额：不同意存储、又没有 voice-usage.jsonl 时，逐通记录少算的部分
    ledger, ledger_info = _ledger_for(src.data, day)
    gap = None
    if ledger is not None:
        diff = {k: max(0.0, _f(ledger.get(k)) - counts[k]) for k in COUNTERS}
        ledger_info["sessions"] = ledger.get("sessions")
        ledger_info["counts"] = {k: ledger.get(k) for k in COUNTERS}
        if any(v > 1e-6 for v in diff.values()):
            p_in, p_out = llm_prices(None, env)  # 账本不分模型：按当前 DEEPSUCK_LLM_MODEL
            chars = int(round(diff["tts_chars"])) * 2
            gc = {"llm_in": diff["llm_in"] * p_in / 1e6, "llm_out": diff["llm_out"] * p_out / 1e6,
                  "asr": diff["asr_sec"] * asr_price_per_sec(env),
                  "tts": chars * tts_price_per_char(None, None, env)}
            for k, v in gc.items():
                items[k] += v
            counts["asr_sec"] += diff["asr_sec"]
            counts["tts_chars"] += int(round(diff["tts_chars"]))
            counts["tts_chars_billed"] += chars
            counts["llm_in"] += int(diff["llm_in"])
            counts["llm_out"] += int(diff["llm_out"])
            asr_free_eligible += diff["asr_sec"]
            tts_est = tts_est or chars > 0
            gap = {"counts": {k: _r(v, 3) for k, v in diff.items()}, "cny": _r(sum(gc.values()))}
            kinds["账本差额（未逐通记录）"] = {"calls": None, "cny": gap["cny"]}

    # 文字代理
    chat_path = src.chat_path
    chat, chat_info = _chat_for(chat_path, day)
    if chat is not None:
        model, p_in, p_out = proxy_prices(env)
        tin, tout = int(_f(chat.get("inTokens"))), int(_f(chat.get("outTokens")))
        items["proxy"] = tin * p_in / 1e6 + tout * p_out / 1e6
        chat_info.update({"model": model, "calls": chat.get("calls"), "in_tokens": tin, "out_tokens": tout})

    # 评测
    ev = [r for r in src.eval_rows if r["date"] == day]
    items["eval"] = sum(r["cny"] for r in ev)

    # ASR 免费额度
    free_total = asr_free_seconds(env)
    used_before = src.asr_sec_before(day)
    free_left = max(0.0, free_total - used_before)
    covered = min(free_left, asr_free_eligible)
    asr_after = max(0.0, items["asr"] - covered * asr_price_per_sec(env))

    total_list = sum(items.values())
    total_after = total_list - items["asr"] + asr_after
    return {
        "day": day,
        "items": {k: _r(v) for k, v in items.items()},
        "asr_after_free": _r(asr_after),
        "asr_free": {"monthly_sec": free_total, "used_before_sec": _r(used_before, 1),
                     "left_before_sec": _r(free_left, 1), "covered_today_sec": _r(covered, 1)},
        "total_list": _r(total_list),
        "total_after_free": _r(total_after),
        "tts_estimated": tts_est,
        "counts": {k: (_r(v, 1) if isinstance(v, float) else v) for k, v in counts.items()},
        "by_kind": {k: {"calls": v["calls"], "cny": _r(v["cny"])} for k, v in sorted(kinds.items())},
        "ledger_gap": gap,
        "eval_rows": ev,
        "_ledger_info": ledger_info,
        "_chat_info": chat_info,
    }


def _month_days(day: str) -> List[str]:
    d = date.fromisoformat(day)
    first = d.replace(day=1)
    return [(first + timedelta(days=i)).isoformat() for i in range((d - first).days + 1)]


def compute_baseline(src: Sources, day: str, baseline: Optional[dict], today: dict, env=None) -> dict:
    alert_pct = _fenv(env, "COST_ALERT_PCT", 50.0)
    if not isinstance(baseline, dict):
        return {"found": False}
    out: dict = {"found": True, "as_of": baseline.get("as_of"), "expires": baseline.get("expires"),
                 "coupon_balance": baseline.get("coupon_balance"), "monthly_budget": baseline.get("monthly_budget")}

    def day_total(d: str) -> float:
        return today["total_after_free"] if d == day else compute_day(src, d)["total_after_free"]

    as_of = baseline.get("as_of")
    bal = baseline.get("coupon_balance")
    if as_of and bal is not None:
        try:
            a = date.fromisoformat(str(as_of))
            d = date.fromisoformat(day)
            spent = sum(day_total((a + timedelta(days=i)).isoformat()) for i in range(1, (d - a).days + 1))
            out["spent_since_as_of"] = _r(spent)
            out["balance_est"] = _r(_f(bal) - spent, 2)
        except ValueError:
            out["error"] = "as_of 不是 YYYY-MM-DD"
    mtd = sum(day_total(d) for d in _month_days(day))
    out["month_to_date"] = _r(mtd)
    budget = _f(baseline.get("monthly_budget"))
    if budget > 0:
        pct = mtd / budget * 100
        out["month_pct"] = round(pct, 1)
        out["alert_pct"] = alert_pct
        out["alert"] = pct >= alert_pct
    exp = baseline.get("expires")
    if exp:
        out["expired"] = str(day) > str(exp)
    return out


def build_report(day: str, *, traces: Optional[Path], data: Optional[Path], usage: Optional[Path] = None,
                 chat_budget: Optional[Path] = None, baseline: Optional[Path] = None,
                 eval_spend: Optional[Path] = None, env=None) -> dict:
    src = Sources(traces=traces, data=data, usage=usage, chat_budget=chat_budget, eval_spend=eval_spend, env=env)
    today = compute_day(src, day)
    base_info = {"path": str(baseline) if baseline else None, "found": bool(baseline and baseline.is_file())}
    b = compute_baseline(src, day, _read_json(baseline), today, env)
    sources = {"traces": src.trace_info, "voice_usage": src.usage_info, "voice_budget": today.pop("_ledger_info"),
               "chat_budget": today.pop("_chat_info"), "eval_spend": src.eval_info, "baseline": base_info}
    return {**today, "baseline": b, "sources": sources,
            "prices": {"asr_per_sec": asr_price_per_sec(env),
                       "llm_default": dict(zip(("in_per_m", "out_per_m"), llm_prices(None, env))),
                       "llm_default_model": _env(env).get("DEEPSUCK_LLM_MODEL") or G.DEFAULT_LLM_MODEL}}


# ---------------------------------------------------------------- 输出
ITEM_NAMES = [("llm_in", "大模型输入"), ("llm_out", "大模型输出"), ("asr", "语音识别 ASR"), ("tts", "语音合成 TTS"),
              ("proxy", "文字代理"), ("eval", "评测")]


def format_text(rep: dict) -> str:
    c = rep["counts"]
    lines = [f"DeepSuck 当日成本 {rep['day']}（+08:00，原价，单位：元）"]
    for k, name in ITEM_NAMES:
        v = rep["items"][k]
        extra = ""
        if k in ("llm_in", "llm_out"):
            extra = f"（{c[k]} token）"
        elif k == "asr":
            extra = f"（{c['asr_sec']} 秒；扣 Paraformer 每月 10 小时免费额度后 {rep['asr_after_free']:.4f}）"
        elif k == "tts":
            extra = f"（{c['tts_chars_billed']} 计费字符" + ("，估算：tts_chars×2）" if rep["tts_estimated"] else "）")
        lines.append(f"  {name}: {v:.4f}{extra}")
    lines.append(f"  合计（原价）: {rep['total_list']:.4f}")
    lines.append(f"  合计（扣免费额度）: {rep['total_after_free']:.4f}")
    lines.append(f"逐通记录 {c['calls']} 通，按 kind：")
    for k, v in rep["by_kind"].items():
        n = "" if v["calls"] is None else f"{v['calls']} 通，"
        lines.append(f"  - {k}: {n}{v['cny']:.4f}")
    b = rep["baseline"]
    if b.get("found"):
        if "balance_est" in b:
            lines.append(f"优惠券估算余额 {b['balance_est']:.2f}（{b['as_of']} 基准 {b['coupon_balance']}，"
                         f"之后累计 {b['spent_since_as_of']:.4f}），有效期至 {b.get('expires')}"
                         + ("（已过期）" if b.get("expired") else ""))
        if "month_pct" in b:
            flag = "  ⚠ 提醒：已达阈值" if b.get("alert") else ""
            lines.append(f"本月累计（扣免费额度）{b['month_to_date']:.4f} / 券额 {b['monthly_budget']}，"
                         f"占 {b['month_pct']}%（阈值 {b['alert_pct']:g}%）{flag}")
    else:
        lines.append("未找到 cost-baseline.json：不计算优惠券余额")
    s = rep["sources"]
    miss = []
    if not s["traces"]["found"]:
        miss.append(f"通话追踪目录 {s['traces']['path']}")
    if not s["voice_usage"]["found"]:
        miss.append(f"voice-usage.jsonl {s['voice_usage']['path']}")
    vb = s["voice_budget"]
    if not vb["found"]:
        miss.append(f"voice-budget.json {vb['path']}")
    elif not vb["used"]:
        lines.append(f"注：voice-budget.json 是 {vb['day']} 的，不是当天，未用作全量参考")
    cb = s["chat_budget"]
    if not cb["found"]:
        miss.append(f"chat-budget.json {cb['path']}")
    elif not cb["used"]:
        lines.append(f"注：chat-budget.json 是 {cb['day']} 的，文字代理按 0 计")
    if not s["eval_spend"]["found"]:
        miss.append(f"评测花费 {s['eval_spend']['path']}")
    if rep.get("ledger_gap"):
        lines.append(f"注：账本比逐通记录多出 {rep['ledger_gap']['counts']}，按差额计入（不同意存储的通话）")
    if miss:
        lines.append("跳过（文件不存在）：" + "；".join(miss))
    return "\n".join(lines)


def _path(v) -> Optional[Path]:
    return Path(v).expanduser() if v else None


def default_paths(args, env=None) -> dict:
    e = _env(env)
    data = _path(args.data or e.get("DATA_DIR")) or (Path.home() / ".local" / "share" / "deepsuck")
    traces = _path(args.traces or e.get("TRACE_DIR")) or (data / "voice" / "traces")
    usage = _path(args.usage or e.get("VOICE_USAGE_FILE"))
    if usage is None:
        cands = [data / "voice" / "voice-usage.jsonl", data / "voice-usage.jsonl", traces / "voice-usage.jsonl"]
        usage = next((p for p in cands if p.is_file()), cands[0])
    chat = _path(args.chat_budget or e.get("CHAT_BUDGET_FILE"))
    if chat is None:
        chat = (_path(e.get("PROXY_DATA_DIR")) or data) / "chat-budget.json"
    baseline = _path(args.baseline or e.get("COST_BASELINE")) or (data / "cost-baseline.json")
    ev = _path(args.eval_spend or e.get("COST_EVAL_SPEND") or DEFAULT_EVAL_SPEND)
    return {"data": data, "traces": traces, "usage": usage, "chat_budget": chat, "baseline": baseline,
            "eval_spend": ev}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.cost", description="按天汇总语音演示的调用成本（GitHub #20）")
    ap.add_argument("--day", help="YYYY-MM-DD（+08:00），默认今天")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--traces", help="通话追踪目录（默认 TRACE_DIR 或 DATA_DIR/voice/traces）")
    ap.add_argument("--data", help="数据目录（默认 DATA_DIR）")
    ap.add_argument("--usage", help="voice-usage.jsonl（默认 VOICE_USAGE_FILE 或 DATA_DIR/voice/voice-usage.jsonl）")
    ap.add_argument("--chat-budget", help="文字代理 chat-budget.json（默认 PROXY_DATA_DIR 或 DATA_DIR 下）")
    ap.add_argument("--baseline", help="优惠券基准 JSON（默认 COST_BASELINE 或 DATA_DIR/cost-baseline.json）")
    ap.add_argument("--eval-spend", help=f"评测花费 CSV（默认 COST_EVAL_SPEND 或 {DEFAULT_EVAL_SPEND}）")
    args = ap.parse_args(argv)
    day = args.day or datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        date.fromisoformat(day)
    except ValueError:
        ap.error("--day 要求 YYYY-MM-DD")
    p = default_paths(args)
    rep = build_report(day, **p)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(format_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
