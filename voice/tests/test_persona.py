import re
from voice.persona import FILLERS, guard_output, speakable, system_prompt


def test_system_prompt_uses_core_json():
    sp = system_prompt("wang", "refund", "elicit_account", ["收款银行卡号"])
    assert "王阿姨" in sp and "收款银行卡号" in sp
    assert "不要承认自己是 AI" in sp


def test_guard_strips_and_masks():
    assert guard_output("<think>x</think>好的（笑）**行**") == "好的行"
    assert "123456" not in guard_output("验证码是123456")
    # #121：夹着脱敏星号的号码也是一串数字，整串换成含糊说法（不再留开头、尾号）
    assert re.fullmatch("卡号(?:那几个数没听清|那串数没记住|那几位没看清)", guard_output("卡号6222 **** **** 7890"))  # #130：说法轮换
    assert "*" not in guard_output("bi***t***.top")  # #130：打码网址也换成含糊说法（“那个网址”之类），不念星号


def test_speakable_never_reads_masked_tail():
    assert re.fullmatch("(?:后面几位没听清|后面几位没看清|后面几个没记住)", speakable("尾号 ****7890"))


def test_fillers_for_every_persona():
    assert set(FILLERS) == {"wang", "chen", "lin", "zheng"}


def test_voice_openings_from_personas_json():
    """接电话的那一声从 personas.json 的 voiceTraits.opening 读取（#47 / #11），王阿姨、小林与之前手写的一致。"""
    from voice.persona import VOICE_OPENINGS

    assert VOICE_OPENINGS == {"wang": ["喂？…哪位啊"], "chen": ["喂？…你说"], "lin": ["喂？你好，哪位呀"], "zheng": ["喂，哪个？"]}
