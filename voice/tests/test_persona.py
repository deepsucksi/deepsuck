from voice.persona import FILLERS, guard_output, speakable, system_prompt


def test_system_prompt_uses_core_json():
    sp = system_prompt("wang", "refund", "elicit_account", ["收款银行卡号"])
    assert "王阿姨" in sp and "收款银行卡号" in sp
    assert "不要承认自己是 AI" in sp


def test_guard_strips_and_masks():
    assert guard_output("<think>x</think>好的（笑）**行**") == "好的行"
    assert "123456" not in guard_output("验证码是123456")
    # 不能吃掉脱敏星号
    assert guard_output("卡号6222 **** **** 7890") == "卡号6222 **** **** 7890"
    assert guard_output("bi***t***.top") == "bi***t***.top"


def test_speakable_reads_masked_tail_digitwise():
    assert speakable("尾号 ****7890") == "尾号七八九零"


def test_fillers_for_every_persona():
    assert set(FILLERS) >= {"wang", "li", "lin"}


def test_voice_openings_from_traits_yaml():
    """接电话的那一声从 personas/voice_traits.yaml 读取（#47），内容与之前手写的一致。"""
    from voice.persona import VOICE_OPENINGS

    assert VOICE_OPENINGS == {"wang": ["喂？…哪位啊"], "li": ["喂，哪位？"], "lin": ["喂？你好，哪位呀"]}
