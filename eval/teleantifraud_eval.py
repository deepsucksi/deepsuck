#!/usr/bin/env python3
"""用 TeleAntiFraud（Apache-2.0）的文本对话评测 DeepSuck 话术分类器（二分类：诈骗 vs 正常来电）。

数据不入库：首次运行时从 GitHub 稀疏克隆 JimmyMa99/TeleAntiFraud 的两个对话目录（约 3 MB）：
  诈骗：multi-agents-tools/AntiFraudMatrix/results/full_dialogues_20250228_160338（795 通）
  正常：multi-agents-tools/AntiFraudMatrix-normal/results/normal-full_dialogues_20250303_015751（取前 795 通）
这些是论文作者用多智能体生成的合成对话（与 HF 上的 TeleAntiFraud-28k 同源；HF 版需登录并同意条款，本脚本不使用）。

方法：只看来电方（role=left）的话，逐句 classify() 累计话术命中，用 risk_score() 得到 0–100 分，按阈值判为诈骗。
用法：python eval/teleantifraud_eval.py [--dir 已有的克隆目录] [--json out.json] [--quiet]
划分：诈骗/正常各按文件序号奇偶分成 dev（偶数，允许看样本调规则）与 test（奇数，只看汇总）；
另用正常目录中前 795 通之外的对话（调规则时从未看过）单独测误报率。
Apache-2.0
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from deepsuck import classify, risk_score  # noqa: E402

REPO = "https://github.com/JimmyMa99/TeleAntiFraud.git"
FRAUD = "multi-agents-tools/AntiFraudMatrix/results/full_dialogues_20250228_160338"
NORMAL = "multi-agents-tools/AntiFraudMatrix-normal/results/normal-full_dialogues_20250303_015751"


def ensure(dirpath: Path) -> Path:
    if not (dirpath / FRAUD).is_dir():
        dirpath.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", REPO, str(dirpath)], check=True)
        subprocess.run(["git", "-C", str(dirpath), "sparse-checkout", "set", FRAUD, NORMAL], check=True)
    return dirpath


def load(d: Path, n: int):
    out = []
    for f in sorted(glob.glob(str(d / "*.json")))[:n]:
        with open(f, encoding="utf-8") as fh:
            j = json.load(fh)
        out.append([m["content"] for m in j.get("dialogue_history", []) if m.get("role") == "left"])
    return out


def score(lines):
    counts = collections.Counter()
    for l in lines:
        for t in classify(l):
            counts[t["id"]] += 1
    return risk_score(counts), counts


THRESHOLDS = (10, 15, 20, 25, 30, 40, 50, 60, 70)


def metrics(fs, ns):
    out = []
    for th in THRESHOLDS:
        tp = sum(s >= th for s, _ in fs)
        fp = sum(s >= th for s, _ in ns)
        fn = len(fs) - tp
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / len(fs) if fs else 0
        f1 = 2 * p * r / (p + r) if p + r else 0
        out.append({"threshold": th, "precision": p, "recall": r, "f1": f1, "fpr": fp / len(ns) if ns else 0, "tp": tp, "fp": fp, "fn": fn})
    return out


def table(rows):
    lines = ["| 阈值 | 精确率 | 召回率 | F1 | 误报率 |", "|---|---|---|---|---|"]
    for t in rows:
        lines.append(f"| ≥{t['threshold']} | {t['precision']:.1%} | {t['recall']:.1%} | {t['f1']:.3f} | {t['fpr']:.1%} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/.cache/deepsuck/TeleAntiFraud"))
    ap.add_argument("--json", default=None)
    ap.add_argument("--quiet", action="store_true", help="只打印 dev/test 摘要")
    a = ap.parse_args()
    base = ensure(Path(a.dir))
    fraud = load(base / FRAUD, 10 ** 6)
    normal_all = load(base / NORMAL, 10 ** 6)
    normal = normal_all[:len(fraud)]
    extra = normal_all[len(fraud):]  # 前 795 通之外的正常对话：调规则时从未看过，只用来测误报率
    fs = [score(x) for x in fraud]
    ns = [score(x) for x in normal]
    xs = [score(x) for x in extra]
    # 划分：偶数下标 = dev（允许查看漏报/误报来改规则），奇数下标 = test（只看汇总数字）
    split = {
        "dev": ([s for i, s in enumerate(fs) if i % 2 == 0], [s for i, s in enumerate(ns) if i % 2 == 0]),
        "test": ([s for i, s in enumerate(fs) if i % 2 == 1], [s for i, s in enumerate(ns) if i % 2 == 1]),
    }
    res = {"fraud": len(fs), "normal": len(ns), "thresholds": metrics(fs, ns),
           "splits": {k: {"fraud": len(v[0]), "normal": len(v[1]), "thresholds": metrics(*v)} for k, v in split.items()},
           "extraNormal": {"normal": len(xs), "fpr": {str(th): sum(s >= th for s, _ in xs) / len(xs) if xs else 0 for th in THRESHOLDS}}}
    tf = collections.Counter(); tn = collections.Counter()
    for _, c in fs:
        tf.update(c.keys())
    for _, c in ns:
        tn.update(c.keys())
    res["tacticCoverage"] = {k: {"fraud": tf[k] / len(fs), "normal": tn[k] / len(ns)} for k in sorted(set(tf) | set(tn), key=lambda k: -tf[k])}
    res["meanRisk"] = {"fraud": sum(s for s, _ in fs) / len(fs), "normal": sum(s for s, _ in ns) / len(ns)}
    dev_best = max(res["splits"]["dev"]["thresholds"], key=lambda t: t["f1"])
    test_at = next(t for t in res["splits"]["test"]["thresholds"] if t["threshold"] == dev_best["threshold"])
    res["devBestThreshold"] = dev_best["threshold"]
    summary = (f"dev 最优阈值 ≥{dev_best['threshold']}（dev F1 {dev_best['f1']:.3f}）→ test F1 {test_at['f1']:.3f}"
               f"（P {test_at['precision']:.1%} / R {test_at['recall']:.1%} / 误报 {test_at['fpr']:.1%}）；"
               f"额外 {len(xs)} 通未见过的正常对话误报率 {res['extraNormal']['fpr'][str(dev_best['threshold'])]:.1%}")
    if a.quiet:
        print(summary)
    else:
        print(f"诈骗 {len(fs)} 通 / 正常 {len(ns)} 通；平均风险分 诈骗 {res['meanRisk']['fraud']:.1f} · 正常 {res['meanRisk']['normal']:.1f}")
        print("\n全部 795 + 795 通：\n" + table(res["thresholds"]))
        print("\ntest 划分（奇数下标，调规则时不看样本）：\n" + table(res["splits"]["test"]["thresholds"]))
        print("\n" + summary)
        print("\n| 话术标签 | 诈骗对话命中率 | 正常对话命中率 |\n|---|---|---|")
        for k, v in list(res["tacticCoverage"].items())[:16]:
            print(f"| {k} | {v['fraud']:.0%} | {v['normal']:.0%} |")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
