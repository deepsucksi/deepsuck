"""#11 人设统一的跨语言一致性：首页角色 id 集合 == 体验页选项（/api/config）== 评测人设集合。
数据唯一来源是 site/assets/core/personas.json；首页与 JS 侧的细节核对见 tests/personas_unify.test.js。"""
import importlib.util
import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
CORE = json.loads((ROOT / "site/assets/core/personas.json").read_text(encoding="utf-8"))
IDS = [p["id"] for p in CORE["personas"]]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _home_ids():
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    cards = re.findall(r'class="team-member[^"]*" data-persona="([a-z]+)"', html)
    js = (ROOT / "site/assets/js/home.js").read_text(encoding="utf-8")
    cast = re.findall(r"\{ id: '([a-z]+)', name: '[^']+' \}", js)
    assert cards == cast, (cards, cast)
    return cards


def test_home_equals_live_options_equals_eval(tmp_path):
    from voice import app as A
    home = _home_ids()
    live = TestClient(A.create_app("rule")).get("/api/config").json()
    live_ids = [p["id"] for p in live["personas"]]

    from personas import prompt as PR
    from personas.voice_traits import personas as voice_traits
    from personas.humanize import PERSONA_PROFILES
    M = _load("llm_scammer_unify", "eval/llm_scammer.py")
    RB = _load("realism_blind_unify", "eval/realism_blind.py")
    # noise_eval.py 是脚本（导入即解析命令行），只读它的 TIER_PROFILES 字面量
    import ast
    src = (ROOT / "eval/noise_eval.py").read_text(encoding="utf-8")
    tiers = ast.literal_eval(re.search(r"^TIER_PROFILES = (\(.*?\))", src, re.M).group(1))
    from deepsuck import sim
    eval_sets = {
        "llm_scammer 默认": M.run(cache_dir=tmp_path)["config"]["personas"],
        "realism_blind": list(RB.PERSONAS),
        "noise_eval 人设档": [p for p in tiers if p not in ("retiree", "mom", "graduate", "shop_owner")],
        "personas.prompt": list(PR.PERSONA_IDS),
        "voice_traits": list(voice_traits()),
        "humanize 人设预设": list(PERSONA_PROFILES),
        "sim": [p["id"] for p in sim.PERSONAS],
    }
    assert home == IDS == live_ids == ["wang", "chen", "lin", "zheng"]
    for k, v in eval_sets.items():
        assert v == IDS, (k, v)


def test_live_options_carry_homepage_number_role_photo():
    from voice import app as A
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    cards = re.findall(r'data-persona="([a-z]+)"[\s\S]*?round6/([a-z]+)-800\.webp[\s\S]*?team-number">(\d+)</span><b[^>]*>([^<]+)</b>', html)
    live = TestClient(A.create_app("rule")).get("/api/config").json()["personas"]
    assert [(p["id"], p["photo"].rsplit("/", 1)[-1], p["no"], p["role"]) for p in live] == \
        [(i, f"{ph}-400.webp", no, role) for i, ph, no, role in cards]


def test_retired_ids_resolve_everywhere():
    from deepsuck.personas import PERSONA_ALIASES, resolve_persona_id
    from deepsuck import Session
    assert PERSONA_ALIASES == CORE["aliases"] == {"li": "wang", "xiaochen": "chen", "mom": "chen", "shop_owner": "zheng"}
    for old, new in PERSONA_ALIASES.items():
        assert resolve_persona_id(old) == new
        assert Session("refund", old).persona["id"] == new
    from voice.persona import system_prompt
    assert system_prompt("li", "refund") == system_prompt("wang", "refund")
    assert system_prompt("xiaochen", "loan") == system_prompt("chen", "loan")
    # 别名只用于人设 id；humanize 的基础预设名 mom / shop_owner 仍是基础预设
    from personas.humanize import PROFILES, PERSONA_PROFILES
    assert {"mom", "shop_owner"} <= set(PROFILES) and not ({"mom", "shop_owner"} & set(PERSONA_PROFILES))
