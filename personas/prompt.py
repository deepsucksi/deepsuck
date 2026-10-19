"""人设系统提示词（大模型模式 / 评测用）。数据唯一来源：site/assets/core/personas.json
（每个人设的 ``prompt`` 字段 + 顶层 ``promptRules``）；不需要 PyYAML。

    python -m personas.prompt wang        # 打印王阿姨的完整系统提示词
"""
from __future__ import annotations

import json
import sys
from typing import Dict, List

from .humanize.confusion import _core_path

_D = json.loads(_core_path().read_text(encoding="utf-8"))
PERSONA_IDS = tuple(p["id"] for p in _D["personas"])
_BY_ID = {p["id"]: p for p in _D["personas"]}


def _texts(lst) -> List[str]:
    """模板文本（含带 when 条件的句子），去重保序。"""
    out: List[str] = []
    for x in lst:
        t = x if isinstance(x, str) else x.get("t", "")
        if t and t not in out:
            out.append(t)
    return out


def load(persona_id: str) -> Dict:
    """一个人设的提示词资料（prompt 字段），附带 id / name / role / humanize_profile 与拖延句池（取自 templates）。"""
    p = _BY_ID[persona_id]
    out = dict(p["prompt"])
    out.update({"id": p["id"], "name": p["name"], "role": p["role"],
                "humanize_profile": (p.get("humanize") or {}).get("profile"),
                "stallPools": {k: _texts(p["templates"][k]) for k in ("secrecy", "loan_stall")}})
    return out


def common_rules() -> List[str]:
    return list(_D["promptRules"])


def system_prompt(persona_id: str, scenario_hint: str = "") -> str:
    """人设说明 + 共用硬性规则。#4：场景名不进人设提示词（人设只接对方已经说过的话），scenario_hint 只为兼容旧调用，已不使用。"""
    p = load(persona_id)
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(common_rules(), 1))
    parts = [p["systemPrompt"].strip()]
    parts.append("硬性规则：\n" + rules)
    return "\n".join(parts)


def reply_pool(persona_id: str) -> List[str]:
    """人设原句池（评测 / 错字率校准用）：sampleLines + elicitMoves（去掉句末分号）+ secrecy / loan_stall 拖延句，去重保序。"""
    import re
    p = load(persona_id)
    pool = list(p["sampleLines"]) + [re.sub(r"[；;]\s*$", "", x) for x in p["elicitMoves"]]
    for lines in p["stallPools"].values():
        pool += lines
    out, seen = [], set()
    for x in pool:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


if __name__ == "__main__":
    print(system_prompt(sys.argv[1] if len(sys.argv) > 1 else PERSONA_IDS[0], " ".join(sys.argv[2:])))
