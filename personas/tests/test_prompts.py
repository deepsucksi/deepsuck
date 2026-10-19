import re

import pytest

from personas import prompt as P  # noqa: E402
from personas.humanize import PROFILES  # noqa: E402

# 数据来自 site/assets/core/personas.json 的 prompt 字段（原 prompts/*.yaml 已删，旧版存档在 personas/archive/）
REQUIRED = ["id", "name", "role", "archetype", "humanize_profile", "background", "traits", "speechStyle",
            "stallMoves", "elicitMoves", "sampleLines", "systemPrompt"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


@pytest.mark.parametrize("pid", P.PERSONA_IDS)
def test_persona_schema(pid):
    p = P.load(pid)
    for k in REQUIRED:
        assert p.get(k), (pid, k)
    assert p["id"] == pid
    assert p["humanize_profile"] in PROFILES
    for k in ("traits", "stallMoves", "elicitMoves", "sampleLines"):
        assert isinstance(p[k], list) and len(p[k]) >= 3 and all(isinstance(x, str) for x in p[k])


@pytest.mark.parametrize("pid", P.PERSONA_IDS)
def test_system_prompt_has_rules_and_no_secrets(pid):
    sp = P.system_prompt(pid, "冒充客服 · 退款理赔")
    assert "硬性规则" in sp and "绝不真的转账" in sp
    assert "冒充客服" not in sp and "当前场景" not in sp  # #4：场景名不进人设提示词
    assert not re.search(r"\d{6,}", sp)
    assert not EMOJI.search(sp)
    assert "sk-" not in sp


def test_four_archetypes():
    assert sorted(P.load(p)["archetype"] for p in P.PERSONA_IDS) == sorted(["退休老人", "宝妈", "刚毕业学生", "个体小老板"])


def test_four_personas_match_homepage_roles():
    assert P.PERSONA_IDS == ("wang", "chen", "lin", "zheng")
    assert [P.load(p)["role"] for p in P.PERSONA_IDS] == ["退休老人", "宝妈", "刚毕业学生", "个体小老板"]


def test_no_age_in_prompt_data():
    """不写年龄（新规则）：提示词资料里不出现“xx岁”。"""
    for pid in P.PERSONA_IDS:
        p = P.load(pid)
        blob = " ".join([p["background"], p["speechStyle"], p["systemPrompt"]] + p["traits"] + p["sampleLines"])
        assert not re.search(r"\d+\s*岁|[一二三四五六七八九十]+岁", blob), pid
