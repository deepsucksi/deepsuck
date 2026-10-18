"""诈骗话术分类器（与 site/assets/js/tactics.js 等价）：可解释的关键词规则 + 0–100 风险分。"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .core import compile_js, load
from .normalize import normalize

_C = load("tactics")
TACTICS = [
    {"id": t["id"], "label": t["label"], "weight": t["weight"], "cap": t.get("cap", 3), "weak": bool(t.get("weak")), "re": compile_js(t["pattern"])}
    for t in _C["tactics"]
]
BY_ID = {t["id"]: t for t in TACTICS}


def classify(text: Optional[str]) -> List[dict]:
    """classify(text) -> [{id, label, weight, match}]"""
    s = normalize(str(text or "")).text
    hits = []
    for t in TACTICS:
        m = t["re"].search(s)
        if m:
            hits.append({"id": t["id"], "label": t["label"], "weight": t["weight"], "match": m.group(0)})
    return hits


def _js_round(x: float) -> int:
    return int(math.floor(x + 0.5))


def risk_score(counts: Optional[Dict[str, int]]) -> int:
    raw = 0
    strong = False
    for k, c in (counts or {}).items():
        t = BY_ID.get(k)
        if not t or not c > 0:
            continue
        raw += t["weight"] * min(t["cap"], c)  # cap：同一话术最多累计几次
        if not t["weak"]:
            strong = True
    if not strong:
        raw /= 2  # 只有弱信号（如“客服”“尽快”）时减半：正常客服来电也常见
    return min(100, _js_round(100 * (1 - math.exp(-raw / 18))))
