"""真人化预设。数据的唯一来源是 site/assets/core/personas.json：

- ``humanize.profiles``：4 个基础预设（retiree / mom / graduate / shop_owner，按身份分档）；
- 每个人设（王阿姨 wang、小陈妈妈 chen、小林 lin、郑老板 zheng）的 ``humanize`` 字段：``profile`` 指向基础预设，其余键覆盖它。

字段含义见 personas.json 里 ``humanize.profiles.comment``；错字率依据见 docs/REALISM.md「错字率校准」。
"""
from __future__ import annotations

from typing import Dict

from .confusion import _core_path
import json

_D = json.loads(_core_path().read_text(encoding="utf-8"))

PROFILES: Dict[str, dict] = {k: v for k, v in _D["humanize"]["profiles"].items() if k != "comment"}


def _persona_profiles() -> Dict[str, dict]:
    out = {}
    for p in _D["personas"]:
        h = dict(p.get("humanize") or {})
        base = h.pop("profile", None)
        if base is None:
            continue
        merged = {**PROFILES[base], **h, "base": base}
        out[p["id"]] = merged
    return out


# 规则引擎人设 → 合并后的预设（Humanizer(profile="wang") 可直接用）
PERSONA_PROFILES: Dict[str, dict] = _persona_profiles()


def resolve(name: str) -> dict:
    if name in PROFILES:
        return dict(PROFILES[name])
    if name in PERSONA_PROFILES:
        return dict(PERSONA_PROFILES[name])
    raise KeyError(name)
