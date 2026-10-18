"""人设与拖延台词库（数据见 site/assets/core/personas.json / scenarios.json）。"""
from __future__ import annotations

from .core import compile_js, load

_P = load("personas")
_S = load("scenarios")


def _compile(lst):
    return [it if isinstance(it, str) else {"re": compile_js(it["when"]), "t": it["t"]} for it in lst]


PERSONAS = []
for _p in _P["personas"]:
    _q = dict(_p)
    _q["templates"] = {k: _compile(v) for k, v in _p["templates"].items()}
    PERSONAS.append(_q)
PERSONA_BY_ID = {p["id"]: p for p in PERSONAS}
STALL_SECONDS: dict = _P["stallSeconds"]
# 复述情报给骗子听的说法（不念星号）；engine.Session.speak_intel 使用
SPEAK_INTEL: dict = _P["speakIntel"]

SCENARIOS = _S["scenarios"]
SCENARIO_BY_ID = {s["id"]: s for s in SCENARIOS}
