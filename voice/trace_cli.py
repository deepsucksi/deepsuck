"""读通话追踪（服务器上用，不经网络）：

    python -m voice.trace_cli <编号>            打印完整对话：每轮时间、意图、双方文本、延迟
    python -m voice.trace_cli <编号> --audio    另外列出录音文件路径和大小
    python -m voice.trace_cli --list [-n 20]    最近的通话
    python -m voice.trace_cli <编号> --json     原始 JSONL（每行一个对象）
    python -m voice.trace_cli --flagged [--since 2026-10-19] [--json]
                                                被点了“这通有问题”的通话和各条说明
    python -m voice.trace_cli --usage [--since 2026-10-01] [--until 2026-10-19] [--days 7]
                                                按天（UTC+8）汇总用量，输出 JSON（#20 成本监控直接用）
    python -m voice.trace_cli --scrub-no-consent [--apply]
                                                没同意的网页通话：删掉已写下的文字字段、用量照留（#96）；
                                                不带 --apply 只统计（dry-run），输出 JSON
字段表见 docs/TRACE_SCHEMA.md。

容器里：docker exec deepsuck-voice-1 python -m voice.trace_cli <编号>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PY = Path(__file__).resolve().parents[1] / "python"
if str(_PY) not in sys.path:
    sys.path.insert(0, str(_PY))

from . import trace as TR  # noqa: E402


def _lat(l) -> str:
    if not l:
        return ""
    keys = (("first_audible", "首声"), ("e2e_reply", "回复首包"), ("asr", "asr"), ("llm_ttft", "llm"),
            ("tts_ttfb", "tts"))
    return " ".join(f"{name}={l[k]}ms" for k, name in keys if l.get(k) is not None)


def _kv(d) -> str:
    if not isinstance(d, dict):
        return str(d or "")
    return " ".join(f"{k}={v}" for k, v in d.items())


def render(t: dict, audio: bool = False) -> str:
    out = []
    for r in t["lines"]:
        typ, ts = r.get("type"), str(r.get("t", ""))[11:23]
        if typ == "start":
            out.append(f"通话 {r.get('id')}  {r.get('t')}  {r.get('channel')}  consent={r.get('consent')}  "
                       f"人设={r.get('persona')} 场景={r.get('scenario')}  模型={r.get('model')}  "
                       f"代码={r.get('code')} 提示词={r.get('promptVersion')}"
                       + (f"  主叫={r['caller']}" if r.get("caller") else ""))
        elif typ == "bot":
            out.append(f"[{ts}] 人设({r.get('kind')})" + (f": {r['text']}" if "text" in r else ""))
        elif typ == "turn":
            out.append(f"[{ts}] #{r.get('n')} 意图={r.get('intent')}" + (f"（{'/'.join(r['intents'])}）" if r.get("intents") else "")
                       + (f"  提示词={r.get('prompt')}" if r.get("prompt") else "")
                       + ("  被打断" if r.get("interrupted") else ""))
            if "asr" not in r and "reply" not in r:
                out.append("    （没同意，未存文字）")
            else:
                out.append(f"    对方: {r.get('asr')}")
                if r.get("filler"):
                    out.append(f"    口头语: {r['filler']}")
                out.append(f"    人设: {r.get('reply')}")
            if r.get("intel"):
                out.append("    情报: " + "、".join(f"{i.get('label')} {i.get('masked')}" for i in r["intel"]))
            if r.get("latency"):
                out.append(f"    延迟: {_lat(r['latency'])}"
                           + (f" llm整句={r['llm_full_ms']}ms" if r.get("llm_full_ms") is not None else ""))
            if "llm_in_tokens" in r:
                out.append(f"    用量: llm {r.get('llm_in_tokens')}/{r.get('llm_out_tokens')} tokens  "
                           f"asr {r.get('asr_audio_sec')}s  tts {r.get('tts_chars')} 字（{r.get('tts_voice') or '-'}）")
        elif typ == "feedback":
            out.append(f"[{ts}] 这通有问题" + (f"（第 {r['turn']} 轮）" if r.get("turn") is not None else "") + f": {r.get('note') or '（无说明）'}")
        elif typ == "end":
            hl = r.get("latency") or {}
            fa = (hl.get("first_audible") or {}).get("p50")
            u = r.get("usage_total") or {}
            out.append(f"[{ts}] 结束：原因={r.get('reason')} 轮数={r.get('turns')}"
                       + (f" 时长={r['duration_sec']}s" if r.get("duration_sec") is not None else "")
                       + (f" 首声p50={fa}ms" if fa is not None else "")
                       + (f" 合计 llm {u.get('llm_in_tokens')}/{u.get('llm_out_tokens')} tokens asr {u.get('asr_audio_sec')}s"
                          f" tts {u.get('tts_chars')} 字" if u else "")
                       + (f" 约 {r['cost_cny']} 元" if r.get("cost_cny") is not None else ""))
        elif typ == "audio":
            parts = [f"{k} {v.get('seconds')}s {v.get('bytes')}B" for k, v in r.items() if isinstance(v, dict)]
            out.append(f"[{ts}] 录音: " + "，".join(parts) + (f"（停止：{r['stopped']}）" if r.get("stopped") else ""))
        elif typ == "audio_stopped":
            out.append(f"[{ts}] 录音停止: {r.get('reason')}")
        elif typ == "client_error":
            out.append(f"[{ts}] 前端上报失败: {r.get('stage')} {r.get('reason') or ''} {_kv(r.get('detail'))}".rstrip())
        elif typ == "client_connected":
            out.append(f"[{ts}] 前端已接通: {_kv(r.get('detail'))}".rstrip())
    if audio:
        if t["audio"]:
            for k, v in t["audio"].items():
                out.append(f"录音 {k}: {v['file']} ({v['bytes']} 字节)")
        else:
            out.append("录音: 无")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.trace_cli", description=__doc__.splitlines()[0])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--audio", action="store_true", help="列出录音文件路径")
    ap.add_argument("--list", action="store_true", help="列出最近的通话")
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--flagged", action="store_true", help="只列被标记“这通有问题”的通话")
    ap.add_argument("--usage", action="store_true", help="按天汇总用量（JSON）")
    ap.add_argument("--since", help="起始日期 YYYY-MM-DD（含）")
    ap.add_argument("--until", help="截止日期 YYYY-MM-DD（含，仅 --usage）")
    ap.add_argument("--days", type=int, help="最近几天（仅 --usage，等价于 --since 今天往前 N-1 天）")
    ap.add_argument("--scrub-no-consent", action="store_true", help="删掉没同意通话里的文字字段（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="配合 --scrub-no-consent 真正改写文件")
    a = ap.parse_args(argv)
    if a.scrub_no_consent:
        print(json.dumps(TR.scrub_no_consent(apply=a.apply), ensure_ascii=False, indent=1))
        return 0
    if a.usage:
        since = a.since
        if a.days and not since:
            from datetime import datetime, timedelta
            since = (datetime.now(TR.TZ) - timedelta(days=max(1, a.days) - 1)).strftime("%Y-%m-%d")
        print(json.dumps(TR.usage_by_day(since, a.until), ensure_ascii=False, indent=1))
        return 0
    if a.flagged:
        rows = TR.list_traces(since=a.since, limit=a.n if a.n != 20 else 500, flagged=True)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        for r in rows:
            print(f"{r['id']}  {r['t']}  {r['channel']:5s}  {r['persona']}/{r['scenario']}  轮数={r['turns']}  "
                  f"原因={r['reason']}  录音={'有' if r['audio'] else '无'}")
            for n in r.get("notes") or []:
                print(f"    [{str(n.get('t', ''))[:19]}]" + (f" 第 {n['turn']} 轮" if n.get("turn") is not None else "")
                      + f" {n.get('note') or '（无说明）'}")
        if not rows:
            print("（没有被标记有问题的通话）")
        return 0
    if a.list or not a.id:
        rows = TR.list_traces(since=a.since, limit=a.n)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        for r in rows if not a.json else []:
            print(f"{r['id']}  {r['t']}  {r['channel']:5s}  {str(r['consent']):13s}  {r['persona']}/{r['scenario']}  "
                  f"轮数={r['turns']}  原因={r['reason']}  有问题={r['feedback']}  录音={'有' if r['audio'] else '无'}")
        if not rows:
            print(f"（{TR.trace_dir()} 下没有通话记录）")
        return 0
    t = TR.load(a.id.strip().upper())
    if t is None:
        print(f"找不到通话 {a.id}（目录 {TR.trace_dir()}）", file=sys.stderr)
        return 1
    if a.json:
        for r in t["lines"]:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    print(render(t, audio=a.audio))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
