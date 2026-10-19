"""语音线少样本例句：voiceShots 能经 deepsuck.personas 读到，回话过输出守卫后不变（不含长数字、括号动作、Markdown）。"""
from deepsuck.engine import polish_reply
from voice.persona import PERSONA_BY_ID, first_turn_shot, guard_output, speakable


import pytest


@pytest.mark.parametrize("pid", ["wang", "chen", "zheng"])
def test_voice_shots_loadable_and_guard_clean(pid):
    shots = PERSONA_BY_ID[pid]["voiceShots"]
    assert len(shots) >= 15
    for it in shots:
        assert set(it) >= {"scammer", "reply"}
        assert guard_output(it["reply"]) == polish_reply(it["reply"])  # #132：守卫只做口语化（第一句快速反问的问号换“…”）
        assert "！" not in speakable(it["reply"]) and speakable(it["reply"]).strip()
    assert all(isinstance(r, str) for r in PERSONA_BY_ID[pid]["voiceStyle"])


def test_new_voice_shots_in_system_prompt():
    from voice.persona import system_prompt
    for pid in ("chen", "zheng"):
        sp = system_prompt(pid, "loan")
        assert PERSONA_BY_ID[pid]["voiceStyle"][0] in sp
        # #132：开口就反问的例句每轮都按 first_turn_shot 改成接词陈述再拼进提示词（例句文字本身不改）
        assert any(first_turn_shot(x["reply"], i) in sp for x in PERSONA_BY_ID[pid]["voiceShots"] if x.get("scenario") == "loan" for i in range(5))
