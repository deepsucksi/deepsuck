"""评测费用台账（仓库根目录 eval-spend.csv）与总预算护栏。

- 每次实际调用模型的评测跑完（或中途因超限 / 出错停下）都追加一行，逐笔记账；
- 同一个 --budget-tag 的所有行加起来就是这一批评测已花的钱，新一次运行的上限 = min(单次上限, 总预算 − 已花)；
- 总预算硬上限 HARD_TOTAL_CNY（10 元），--total-budget 只能调低；
- cached_tokens 列（#164 起）：usage.prompt_tokens_details.cached_tokens 的合计，是 prompt_tokens 的一部分，按缓存命中价计费；
  #164 之前的旧行这一列留空（当时没有记，不代表没命中）；Batch 调用没有缓存折扣，记 0；
- 台账只记 token 数和金额，不记 Key、不记对话内容。
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "eval-spend.csv"
HARD_TOTAL_CNY = 10.0
FIELDS = ["time", "tag", "script", "model", "requests", "prompt_tokens", "completion_tokens", "cached_tokens",
          "cost_cny", "note"]


class LedgerBudgetError(Exception):
    pass


def spent(tag: str, ledger: Path = LEDGER) -> float:
    if not Path(ledger).exists():
        return 0.0
    with open(ledger, encoding="utf-8", newline="") as f:
        return sum(float(r["cost_cny"] or 0) for r in csv.DictReader(f) if r.get("tag") == tag)


def remaining(tag: str, total: float = HARD_TOTAL_CNY, ledger: Path = LEDGER) -> float:
    total = min(float(total), HARD_TOTAL_CNY)
    return max(0.0, total - spent(tag, ledger))


def cap(max_cost: float, tag: Optional[str], total: float = HARD_TOTAL_CNY, ledger: Path = LEDGER) -> float:
    """单次上限再按总预算余额收紧；余额为 0 时拒绝运行。tag 为空时不用台账。"""
    if not tag:
        return float(max_cost)
    left = remaining(tag, total, ledger)
    if left <= 0:
        raise LedgerBudgetError(f"预算「{tag}」已用完（总预算 {min(float(total), HARD_TOTAL_CNY)} 元），拒绝运行")
    return min(float(max_cost), left)


def _migrate(p: Path) -> None:
    """旧表头（没有 cached_tokens 列）就地补列：旧行这一列留空，其余字段原样保留。"""
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        header = rows and list(rows[0].keys())
    if not rows:
        with open(p, encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
    if list(header or []) == FIELDS:
        return
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") or "" for k in FIELDS})


def append(tag: str, script: str, model: str, usage: dict, note: str = "", ledger: Path = LEDGER,
           now: Optional[str] = None) -> None:
    p = Path(ledger)
    new = not p.exists() or p.stat().st_size == 0
    if not new:
        _migrate(p)
    with open(p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"time": now or datetime.now().astimezone().isoformat(timespec="seconds"), "tag": tag,
                    "script": script, "model": model, "requests": int(usage.get("requests", 0)),
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "cached_tokens": int(usage.get("cached_tokens", 0)),
                    "cost_cny": f"{float(usage.get('cost_cny', 0.0)):.6f}", "note": note})
