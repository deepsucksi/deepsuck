#!/usr/bin/env python3
"""规则骗子模拟器的情报暴露率消融（LLM-free）：定位 644f2ee → 67b1baf 暴露率 88% → 98% 的来源。

  main                 ：当前实现；
  no_coop_swap         ：关掉 12ebf5a 的“连续两轮纯拖延时第二轮换成 coop_step”（Session.PURE_STALL = []）；
  sim_coop_as_stall    ：实现不变，让规则骗子把 coop_step 也当拖延（sim.STALL 加 coop_step）。

用法：python eval/sim_ablation.py [--seeds 30] [--lines legacy] [--json out.json]。Apache-2.0
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from deepsuck import engine, sim  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, default=30)
ap.add_argument("--lines", default="legacy", choices=("legacy", "corpus"))
ap.add_argument("--json")
A = ap.parse_args()
KEYS = ("elicitRate", "avgTurns", "avgEstMinutes", "suspiciousQuit")


def go():
    r = sim.run(A.seeds, ("rule",), None, "standard", A.lines)["byPolicy"]["rule"]
    return {k: r[k] for k in KEYS}


out = {"config": {"seeds": A.seeds, "lines": A.lines, "reveal": "standard"}, "runs": {}}
out["runs"]["main"] = go()
orig = engine.Session.PURE_STALL
engine.Session.PURE_STALL = []
out["runs"]["no_coop_swap"] = go()
engine.Session.PURE_STALL = orig
stall = sim.STALL
sim.STALL = set(stall) | {"coop_step"}
out["runs"]["sim_coop_as_stall"] = go()
sim.STALL = stall
for k, v in out["runs"].items():
    print(f"{k:18s} 暴露率 {v['elicitRate']:.1%}  拖延 {v['avgTurns']:.1f} 轮  估算 {v['avgEstMinutes']:.1f} 分")
if A.json:
    Path(A.json).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
