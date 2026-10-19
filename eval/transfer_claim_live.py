"""#187 实跑：「骗子催转账」场景，网页（llm.js buildMessages → sanitizeReply）和语音（voice/persona.py prompt_parts →
guard_output）提示词各跑 N 次，数过滤前、过滤后回复里「已经转了 / 答应去转」的次数（过滤后应为 0）。场景在
tests/fixtures/transfer_claim.json 的 liveRuns。

    DASHSCOPE_API_KEY=... python eval/transfer_claim_live.py --runs 10 --out eval/results-transfer-claim-live.json

会真实调用百炼（按量计费，qwen3.8-flash 每次约 0.001 元）。思考模式关（enable_thinking=false）。不打印 key。只在本地跑，不碰线上服务。
检测用两套：deepsuck.engine.transfer_claim（过滤器本身的分句判定）和一组独立的关键词（BROAD，宽口径，不看否定，
命中的再人工看一眼），两套都为 0 才算过。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.engine import transfer_claim  # noqa: E402
from deepsuck.personas import TRANSFER_CLAIM as TC  # noqa: E402
from voice import persona as VP  # noqa: E402
from voice.guard import llm_price  # noqa: E402

LIVE = json.loads((ROOT / "tests/fixtures/transfer_claim.json").read_text(encoding="utf-8"))["liveRuns"]
LABEL = {"bank": "收款银行卡号"}
# 宽口径关键词：不管否定、引述，出现就记下来人工看
BROAD = re.compile(r"转完|转好了|转过去了|转成功|已经转|刚转|我转了|转给你了|打过去了|汇过去了|我先转|马上转|这就转|现在就转|"
                   r"我去转|给你转过去|收到了没|收到没|到账了[吗没]|到账没|到了没")
NEG = re.compile(r"(?:没|不|别|未)[还都也就敢想能会要用得再先太]{0,3}$")


def claims(text: str) -> list:
    s = re.sub(TC["quote"], "\ue010", text)
    return [x for x in re.findall("[^" + re.escape(TC["split"]) + "]+", s) if transfer_claim(x)]


def broad(text: str) -> list:
    return [m.group(0) for m in BROAD.finditer(text) if not NEG.search(text[max(0, m.start() - 5):m.start()])]


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


def web_sanitize(texts: list) -> list:
    js = ("const L=require('./site/assets/js/llm.js');const a=JSON.parse(require('fs').readFileSync(0,'utf8'));"
          "process.stdout.write(JSON.stringify(a.map(L.sanitizeReply)))")
    return json.loads(subprocess.run(["node", "-e", js], cwd=ROOT, input=json.dumps(texts, ensure_ascii=False),
                                     capture_output=True, text=True, check=True).stdout)


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
    ap.add_argument("--budget", type=float, default=1.0, help="花费上限（元），超过就停")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.model != "qwen3.8-flash":
        print("只用 qwen3.8-flash", file=sys.stderr)
        return 2
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        print("缺 DASHSCOPE_API_KEY", file=sys.stderr)
        return 2
    p_in, p_out = llm_price(a.model)
    sides = {"web": (web_messages(), 0.9, 200), "voice": (voice_messages(), 0.8, 120)}
    for name, (msgs, _, _) in sides.items():
        sysp = "\n".join(m["content"] for m in msgs if m["role"] == "system")
        assert TC["rule"] in sysp, name  # 收紧后的规则在提示词里
    rows, cost, tin, tout = [], 0.0, 0, 0
    for side, (msgs, temp, mt) in sides.items():
        for i in range(a.runs):
            if cost >= a.budget:
                break
            j = call(a.base, key, a.model, msgs, temp, mt)
            u = j.get("usage") or {}
            tin += int(u.get("prompt_tokens") or 0)
            tout += int(u.get("completion_tokens") or 0)
            cost = (tin * p_in + tout * p_out) / 1e6
            raw = (j["choices"][0]["message"].get("content") or "").strip()
            rows.append({"side": side, "run": i + 1, "raw": raw})
    web_out = web_sanitize([r["raw"] for r in rows if r["side"] == "web"])
    it = iter(web_out)
    for r in rows:
        r["out"] = next(it) if r["side"] == "web" else VP.guard_output(r["raw"])
        r["raw_claims"], r["raw_broad"] = claims(r["raw"]), broad(r["raw"])
        r["out_claims"], r["out_broad"] = claims(r["out"]), broad(r["out"])
        flag = "过滤前命中 " + "、".join(r["raw_claims"] + r["raw_broad"]) if (r["raw_claims"] or r["raw_broad"]) else "ok"
        print(f"{r['side']} #{r['run']}: {flag}｜{r['raw']}" + (f"  →  {r['out']}" if r["out"] != r["raw"] else ""))
    summary = {"model": a.model, "runs_per_side": a.runs, "requests": len(rows), "prompt_tokens": tin, "completion_tokens": tout,
               "cost_cny": round(cost, 6),
               "raw_hits": {s: sum(1 for r in rows if r["side"] == s and (r["raw_claims"] or r["raw_broad"])) for s in sides},
               "filtered_hits": {s: sum(1 for r in rows if r["side"] == s and (r["out_claims"] or r["out_broad"])) for s in sides},
               "rewritten": {s: sum(1 for r in rows if r["side"] == s and any(x in r["out"] for x in TC["stall"]) and r["out"] != r["raw"]) for s in sides}}
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not any(summary["filtered_hits"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
