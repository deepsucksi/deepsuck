"""语音线少样本例句：voiceShots 能经 deepsuck.personas 读到，回话过输出守卫后不变（不含长数字、括号动作、Markdown）。"""
from voice.persona import PERSONA_BY_ID, guard_output, speakable


def test_wang_voice_shots_loadable_and_guard_clean():
    shots = PERSONA_BY_ID["wang"]["voiceShots"]
    assert len(shots) >= 15
    for it in shots:
        assert set(it) >= {"scammer", "reply"}
        assert guard_output(it["reply"]) == it["reply"]
        assert "！" not in speakable(it["reply"]) and speakable(it["reply"]).strip()
    assert all(isinstance(r, str) for r in PERSONA_BY_ID["wang"]["voiceStyle"])
