import re

import pytest

yaml = pytest.importorskip("yaml")

from personas import prompt as P  # noqa: E402
from personas.humanize import PROFILES  # noqa: E402

REQUIRED = ["id", "name", "archetype", "humanize_profile", "age", "background", "traits", "speech_style",
            "stall_moves", "elicit_moves", "sample_lines", "system_prompt"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


@pytest.mark.parametrize("pid", P.PERSONA_IDS)
def test_persona_schema(pid):
    p = P.load(pid)
    for k in REQUIRED:
        assert p.get(k), (pid, k)
    assert p["id"] == pid
    assert p["humanize_profile"] in PROFILES
    for k in ("traits", "stall_moves", "elicit_moves", "sample_lines"):
        assert isinstance(p[k], list) and len(p[k]) >= 3 and all(isinstance(x, str) for x in p[k])


@pytest.mark.parametrize("pid", P.PERSONA_IDS)
def test_system_prompt_has_rules_and_no_secrets(pid):
    sp = P.system_prompt(pid, "冒充客服 · 退款理赔")
    assert "硬性规则" in sp and "绝不真的转账" in sp and "冒充客服" in sp
    assert not re.search(r"\d{6,}", sp)
    assert not EMOJI.search(sp)
    assert "sk-" not in sp


def test_four_archetypes():
    assert sorted(P.load(p)["archetype"] for p in P.PERSONA_IDS) == sorted(["退休老人", "宝妈", "刚毕业学生", "个体小老板"])
