"""#173 实跑：「骗子没报号」场景，网页（llm.js buildMessages）和语音（voice/persona.py prompt_parts）提示词各跑 N 次，
数回复里出现“那个号”“那个名字”的次数（应为 0）。场景在 tests/fixtures/unsaid_refs.json 的 liveRuns。

    DASHSCOPE_API_KEY=... python eval/unsaid_refs_live.py --runs 10 --out eval/results-unsaid-refs-live.json

会真实调用百炼（按量计费，qwen3.8-flash 每次约 0.0005 元）。思考模式关（enable_thinking=false）。不打印 key。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import Session  # noqa: E402
from deepsuck.refs import forbidden_in  # noqa: E402
from voice import persona as VP  # noqa: E402
from voice.guard import llm_price  # noqa: E402

LIVE = json.loads((ROOT / "tests/fixtures/unsaid_refs.json").read_text(encoding="utf-8"))["liveRuns"]
LABEL = {"bank": "收款银行卡号", "wallet": "加密钱包地址", "phone": "联系电话", "url": "网址/下载链接", "name": "收款人姓名"}


def web_messages() -> list:
    tr = []
    for i, t in enumerate(LIVE["heard"]):
        tr.append({"role": "scammer", "text": t})
        if i < len(LIVE["replies"]) and i < len(LIVE["heard"]) - 1:
            tr.append({"role": "bot", "text": LIVE["replies"][i]})
    js = ("const L=require('./site/assets/js/llm.js');process.stdout.write(JSON.stringify(L.buildMessages("
          + json.dumps({"persona": LIVE["persona"], "scenario": "police", "hint": LIVE["hint"], "missing": LIVE["goals"],
                        "transcript": tr}, ensure_ascii=False) + ")))")
    return json.loads(subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True).stdout)


def voice_messages() -> list:
    heard = LIVE["heard"]
    topics = set().union(*(VP.topics_in(t) for t in heard))
    scenes: list = []
    for t in heard:
        scenes += [x for x in VP.scenes_in(t) if x not in scenes]
    fixed, turn = VP.prompt_parts(LIVE["persona"], "police", LIVE["hint"], [LABEL[g] for g in LIVE["goals"]], topics=topics,
                                  scenes=scenes, opener_key="live", refs=VP.heard_refs(heard))
    hist = []
    for i, t in enumerate(heard[:-1]):
        hist += [{"role": "user", "content": t}, {"role": "assistant", "content": LIVE["replies"][i]}]
    return [{"role": "system", "content": fixed}] + hist + [{"role": "system", "content": turn}, {"role": "user", "content": heard[-1]}]


def call(base: str, key: str, model: str, messages: list, temperature: float, max_tokens: int) -> dict:
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "enable_thinking": False}
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=LIVE["runs"])
    ap.add_argument("--model", default=LIVE["model"])
    ap.add_argument("--base", default=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--budget", type=float, default=20.0, help="花费上限（元），超过就停")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        print("缺 DASHSCOPE_API_KEY", file=sys.stderr)
        return 2
    p_in, p_out = llm_price(a.model)
    sides = {"web": (web_messages(), 0.9, 200), "voice": (voice_messages(), 0.8, 120)}
    for name, (msgs, _, _) in sides.items():
        bad = forbidden_in("\n".join(m["content"] for m in msgs if m["role"] == "system"), set())
        assert not bad, (name, bad)  # 离线：提示词里本来就不该有
    rows, cost, tin, tout = [], 0.0, 0, 0
    for side, (msgs, temp, mt) in sides.items():
        for i in range(a.runs):
            if cost >= a.budget:
                break
            j = call(a.base, key, a.model, msgs, temp, mt)
            u = j.get("usage") or {}
            tin += int(u.get("prompt_tokens") or 0)
            tout += int(u.get("completion_tokens") or 0)
            cost = (tin * p_in + tout * p_out) / 1e6  # 单价是 元 / 百万 token（voice/guard.py LLM_PRICES）
            raw = (j["choices"][0]["message"].get("content") or "").strip()
            hits = forbidden_in(raw, set())
            rows.append({"side": side, "run": i + 1, "reply": raw, "hits": hits})
            print(f"{side} #{i + 1}: {'命中 ' + '、'.join(hits) if hits else 'ok'}｜{raw}")
    summary = {"model": a.model, "runs_per_side": a.runs, "requests": len(rows), "prompt_tokens": tin, "completion_tokens": tout,
               "cost_cny": round(cost, 6), "hits": {s: sum(1 for r in rows if r["side"] == s and r["hits"]) for s in sides}}
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not any(summary["hits"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
