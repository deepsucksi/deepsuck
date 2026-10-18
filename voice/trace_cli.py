"""读通话追踪（服务器上用，不经网络）：

    python -m voice.trace_cli <编号>            打印完整对话：每轮时间、意图、双方文本、延迟
    python -m voice.trace_cli <编号> --audio    另外列出录音文件路径和大小
    python -m voice.trace_cli --list [-n 20]    最近的通话
    python -m voice.trace_cli <编号> --json     原始 JSONL（每行一个对象）

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
            out.append(f"[{ts}] 人设({r.get('kind')}): {r.get('text')}")
        elif typ == "turn":
            out.append(f"[{ts}] #{r.get('n')} 意图={r.get('intent')}" + (f"（{'/'.join(r['intents'])}）" if r.get("intents") else "")
                       + (f"  提示词={r.get('prompt')}" if r.get("prompt") else ""))
            out.append(f"    对方: {r.get('asr')}")
            if r.get("filler"):
                out.append(f"    口头语: {r['filler']}")
            out.append(f"    人设: {r.get('reply')}")
            if r.get("intel"):
                out.append("    情报: " + "、".join(f"{i.get('label')} {i.get('masked')}" for i in r["intel"]))
            if r.get("latency"):
                out.append(f"    延迟: {_lat(r['latency'])}")
        elif typ == "feedback":
            out.append(f"[{ts}] 反馈" + (f"（第 {r['turn']} 轮）" if r.get("turn") is not None else "") + f": {r.get('note') or '（无说明）'}")
        elif typ == "end":
            hl = r.get("latency") or {}
            fa = (hl.get("first_audible") or {}).get("p50")
            out.append(f"[{ts}] 结束：原因={r.get('reason')} 轮数={r.get('turns')}"
                       + (f" 首声p50={fa}ms" if fa is not None else ""))
        elif typ == "audio":
            parts = [f"{k} {v.get('seconds')}s {v.get('bytes')}B" for k, v in r.items() if isinstance(v, dict)]
            out.append(f"[{ts}] 录音: " + "，".join(parts) + (f"（停止：{r['stopped']}）" if r.get("stopped") else ""))
        elif typ == "audio_stopped":
            out.append(f"[{ts}] 录音停止: {r.get('reason')}")
        elif typ == "client_error":
            out.append(f"[{ts}] 前端上报: {r.get('stage')} {r.get('reason')} {r.get('detail') or ''}".rstrip())
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
    a = ap.parse_args(argv)
    if a.list or not a.id:
        rows = TR.list_traces(limit=a.n)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        for r in rows if not a.json else []:
            print(f"{r['id']}  {r['t']}  {r['channel']:5s}  {str(r['consent']):13s}  {r['persona']}/{r['scenario']}  "
                  f"轮数={r['turns']}  原因={r['reason']}  反馈={r['feedback']}  录音={'有' if r['audio'] else '无'}")
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
