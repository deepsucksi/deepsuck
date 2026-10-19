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
# 人设回复发出前的数字过滤配置（issue #121）；engine.vague_digits 使用
DIGIT_ECHO: dict = _P["digitEcho"]
REPLY_POLISH: dict = _P["replyPolish"]  # 大模型回复口语化后处理（#132、#134），engine.polish_reply 使用
TAIL_DEDUPE: dict = _P["tailDedupe"]  # 跨轮去重（#153），engine.dedupe_tail 使用

SCENARIOS = _S["scenarios"]
SCENARIO_BY_ID = {s["id"]: s for s in SCENARIOS}
# 别名 → 人设 id（personas.json 的 aliases：li → wang，xiaochen / mom → chen，shop_owner → zheng；旧链接 ?persona=li、旧配置 VOICE_TELEPHONY_PERSONA 仍能用）
PERSONA_ALIASES: dict = dict(_P.get("aliases") or {})


def resolve_persona_id(pid) -> str:
    pid = str(pid or "")
    return PERSONA_ALIASES.get(pid, pid)
