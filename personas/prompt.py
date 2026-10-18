"""读取 personas/prompts/*.yaml，拼出完整的系统提示词（需要 PyYAML）。

    python -m personas.prompt retiree        # 打印周伯的完整系统提示词
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PERSONA_IDS = ("retiree", "mom", "graduate", "shop_owner")


def _yaml():
    try:
        import yaml  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("personas.prompt 需要 PyYAML：pip install pyyaml") from e
    return yaml


def load(persona_id: str) -> Dict:
    with open(PROMPTS_DIR / f"{persona_id}.yaml", encoding="utf-8") as f:
        return _yaml().safe_load(f)


def common_rules() -> List[str]:
    return load("_common")["rules"]


def system_prompt(persona_id: str, scenario_hint: str = "") -> str:
    p = load(persona_id)
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(common_rules(), 1))
    parts = [p["system_prompt"].strip()]
    if scenario_hint:
        parts.append(f"当前场景：{scenario_hint}")
    parts.append("硬性规则：\n" + rules)
    return "\n".join(parts)


if __name__ == "__main__":
    print(system_prompt(sys.argv[1] if len(sys.argv) > 1 else "retiree", " ".join(sys.argv[2:])))
