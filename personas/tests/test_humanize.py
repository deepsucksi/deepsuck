import re

import pytest
from pathlib import Path

from personas.humanize import OPS, PROFILES, Humanizer, humanize
from personas.humanize import confusion as C

TEXT = "好的，我已经知道了。你说的账户是哪个银行的？我需要再确认一下622202*********3445对不对。"
CTX = "你把钱转到这个安全账户，户名写钱伟，尾号3445"


def test_intensity_zero_is_identity():
    for seed in range(20):
        assert humanize(TEXT, 0.0, seed=seed) == TEXT
        assert humanize(TEXT, 0.0, seed=seed, mode="voice", dialect="西南") == TEXT


def test_same_seed_same_output():
    for seed in range(20):
        a = humanize(TEXT, 0.7, seed=seed, context=CTX)
        b = humanize(TEXT, 0.7, seed=seed, context=CTX)
        assert a == b
    h1, h2 = Humanizer(0.6, seed=5), Humanizer(0.6, seed=5)
    assert [h1(TEXT) for _ in range(5)] == [h2(TEXT) for _ in range(5)]


def test_seeds_vary_output():
    outs = {humanize(TEXT, 0.8, seed=s) for s in range(30)}
    assert len(outs) > 10


def test_does_not_touch_global_random():
    import random
    random.seed(123)
    expected = random.random()
    random.seed(123)
    humanize(TEXT, 0.9, seed=1)
    assert random.random() == expected


def test_protected_spans_survive():
    text = "卡号622202*********3445，网址 pay-help.example 和 {银行卡} 都发我，周伯记下了。"
    for seed in range(50):
        out = humanize(text, 1.0, seed=seed, mode="chat", dialect="北方", keep=["周伯"])
        for frag in ("622202*********3445", "pay-help.example", "{银行卡}", "周伯"):
            assert frag in out, (seed, out)


def test_intensity_increases_changes():
    def changed(i):  # 改动的字符数（逐位比较 + 长度差），强度越大改得越多
        tot = 0
        for s in range(200):
            out = humanize(TEXT, i, seed=s)
            tot += sum(a != b for a, b in zip(out, TEXT)) + abs(len(out) - len(TEXT))
        return tot
    lo, mid, hi = changed(0.1), changed(0.5), changed(1.0)
    assert lo < mid < hi
    assert sum(humanize(TEXT, 1.0, seed=s) != TEXT for s in range(200)) > 180


def test_typo_only_uses_confusion_tables():
    text = "我已经知道了，在家等你的消息。"
    h = Humanizer(1.0, seed=3, ops=["typo"], max_typos=10)
    allowed = set("".join(sum(C.HOMOPHONE_WORDS.values(), []))) | set(text)
    allowed |= set("".join(sum(C.HOMOPHONE_CHARS.values(), []))) | set("".join(sum(C.SHAPE_CHARS.values(), [])))
    for _ in range(50):
        r = h.apply(text)
        assert set(r.text) <= allowed
        assert len(r.text) <= len(text) + 2


def test_max_typos_respected():
    h = Humanizer(1.0, seed=0, ops=["typo"], max_typos=1)
    text = "的的的的的的的的的的"
    for _ in range(30):
        out = h(text)
        assert sum(a != b for a, b in zip(out, text)) <= 1


def test_voice_mode_has_no_sentence_marks_and_no_shape_typos():
    h = Humanizer(1.0, seed=2, mode="voice", ops=["asr", "typo"])
    for _ in range(50):
        out = h("好的。我已经知道了！你等一下。")
        assert "。" not in out and "！" not in out
    shape_only = "".join(k for k in C.SHAPE_CHARS if k not in C.HOMOPHONE_CHARS)
    hv = Humanizer(1.0, seed=2, mode="voice", ops=["typo"], max_typos=10)
    for _ in range(50):
        assert hv(shape_only) == shape_only
    hc = Humanizer(1.0, seed=2, mode="chat", ops=["typo"], max_typos=10)
    assert any(hc(shape_only) != shape_only for _ in range(20))


def test_repeat_echoes_context_without_digits():
    h = Humanizer(1.0, seed=1, ops=["repeat"], weights={"repeat": 10})
    for _ in range(30):
        r = h.apply("好", context=CTX)
        assert r.ops == ["repeat"]
        added = r.text.replace("好", "", 1)
        assert not re.search(r"[0-9*]", added)


def test_repeat_without_context_uses_generic():
    h = Humanizer(1.0, seed=1, ops=["repeat"], weights={"repeat": 10})
    out = h("好的。")
    assert any(g in out for g in C.CONFIRM_GENERIC)


def test_digress_uses_given_pool():
    pool = ["我先去开个窗"]
    h = Humanizer(1.0, seed=4, ops=["digress"], weights={"digress": 10}, digressions=pool)
    assert pool[0] in h("你说吧", context="喂，你好")
    # #129：传进来的池子里编道具的句子同样不用；对方没开口（没有 context）不插跑题句
    h = Humanizer(1.0, seed=4, ops=["digress"], weights={"digress": 10}, digressions=["我先去收个快递"])
    assert h.digressions == [] and "快递" not in h("你说吧", context="喂，你好")
    h = Humanizer(1.0, seed=4, ops=["digress"], weights={"digress": 10}, digressions=pool)
    assert all(pool[0] not in h("你说吧") for _ in range(5))


def test_dialect_substitution():
    out = humanize("你说什么？我没有听清楚，怎么办。", 1.0, seed=1, ops=["dialect"], dialect="西南")
    assert "啥子" in out and "莫得" in out and "咋个" in out
    out = humanize("你干什么呢，怎么办", 1.0, seed=1, ops=["dialect"], dialect="东北")
    assert "干哈" in out and "咋整" in out


def test_punct_styles_recorded():
    seen = set()
    for s in range(200):
        r = Humanizer(1.0, seed=s, ops=["punct"]).apply(TEXT)
        seen.update(op for op in r.ops if op.startswith("punct:"))
    assert {"punct:drop_final", "punct:halfwidth", "punct:strip_all"} <= seen


def test_profiles_are_valid():
    assert set(PROFILES) == {"retiree", "mom", "graduate", "shop_owner"}
    for name in PROFILES:
        h = Humanizer(profile=name, seed=0)
        assert 0 < h.intensity <= 1
        for s in range(20):
            out = Humanizer(profile=name, seed=s).apply(TEXT, CTX).text
            assert "622202*********3445" in out


def test_invalid_arguments():
    with pytest.raises(ValueError):
        Humanizer(1.5)
    with pytest.raises(ValueError):
        Humanizer(0.5, mode="sms")
    with pytest.raises(ValueError):
        Humanizer(0.5, dialect="火星")
    with pytest.raises(ValueError):
        Humanizer(0.5, ops=["typo", "nope"])
    with pytest.raises(KeyError):
        Humanizer(profile="nobody")


def test_empty_text():
    assert humanize("", 1.0, seed=1) == ""
    assert humanize("   ", 1.0, seed=1) == "   "


def test_all_ops_listed():
    assert set(OPS) == {"typo", "punct", "asr", "repeat", "digress", "dialect", "selfref", "extras", "emoji", "split"}


def test_cli(capsys):
    from personas.humanize.__main__ import main
    assert main(["你说什么？", "--profile", "shop_owner", "--seed", "1", "-n", "2", "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and all('"ops"' in x for x in lines)


def test_repeat_echo_is_whole_short_clause_and_no_double_punct():
    ctx = "这些网贷额度必须全部借出来再转到我们的监管账户，系统才能清零"
    for s in range(200):
        r = Humanizer(1.0, seed=s, ops=["repeat"], weights={"repeat": 10}).apply("先付多少呀？", context=ctx)
        assert not re.search(r"[？?！!。，,]{2}", r.text.replace("？？", "")), r.text
        assert "必须全部借出来再转" not in r.text  # 超过 12 字的分句不复述、不截断


def test_digressions_do_not_repeat_within_one_conversation():
    """同一个实例（一整段对话）里跑题句用完一轮才会重复。"""
    pool = ["甲甲甲", "乙乙乙", "丙丙丙"]
    h = Humanizer(1.0, seed=3, ops=["digress"], weights={"digress": 10}, digressions=pool)
    used = []
    for _ in range(3):
        r = h.apply("好的", context="你在吗")
        used += [d for d in pool if d in r.text]
    assert sorted(used) == sorted(pool)


def test_handwriting_shape_typos_switch():
    """形近字：打字模式默认开、语音模式默认关；handwriting=True 时语音模式也有（retiree 预设：老人夹着手写输入）。"""
    shape_only = "".join(k for k in C.SHAPE_CHARS if k not in C.HOMOPHONE_CHARS)
    hv = Humanizer(1.0, seed=2, mode="voice", ops=["typo"], max_typos=10, handwriting=True)
    assert any(hv(shape_only) != shape_only for _ in range(20))
    hc = Humanizer(1.0, seed=2, mode="chat", ops=["typo"], max_typos=10, handwriting=False, shape_typos=False)
    assert all(hc(shape_only) == shape_only for _ in range(20))
    r = Humanizer(profile="retiree", seed=1)
    assert r.mode == "voice" and r.handwriting is False and r.shape_typos is True  # 默认档夹少量形近字，手写档默认关
    assert Humanizer(profile="retiree", seed=1, handwriting=True).handwriting is True
    assert Humanizer(profile="shop_owner", seed=1).shape_typos is False
    assert Humanizer(profile="mom", seed=1).shape_typos is True


def test_typo_rate_calibrated_band():
    """各基础预设在对应人设原句池（personas.json：prompt.sampleLines / elicitMoves + 拖延句）上的每百字错字数
    落在 docs/REALISM.md「错字率校准」写的区间。四位人设与四个基础预设一一对应（humanize.profile）。"""
    hz = lambda s: sum("\u4e00" <= c <= "\u9fff" for c in s)
    from personas import prompt as PR
    by_base = {PR.load(pid)["humanize_profile"]: pid for pid in PR.PERSONA_IDS}
    assert set(by_base) == set(PROFILES)

    def pool(base):
        return PR.reply_pool(by_base[base])
    rates, shape = {}, 0
    shapes = {a for v in C.SHAPE_CHARS.values() for a in v}
    for pid in PROFILES:
        typ = n = 0
        lines = pool(pid)
        for seed in range(40):
            h = Humanizer(profile=pid, seed=seed)
            for x in lines:
                r = h.apply(x)
                typ += sum(int(o.split(":")[1]) for o in r.ops if o.startswith("typo:"))
                n += hz(re.sub(r"\[[^\]]*\]", "", r.text))
                if pid == "retiree" and any(ch in shapes and ch not in x for ch in r.text):
                    shape += 1
        rates[pid] = 100 * typ / n
    assert 2.0 <= rates["retiree"] <= 4.0, rates
    assert 1.5 <= rates["mom"] <= 3.0 and 1.5 <= rates["shop_owner"] <= 3.0, rates
    assert 0.6 <= rates["graduate"] <= 1.8, rates
    assert rates["graduate"] < rates["mom"] < rates["retiree"], rates
    assert shape > 0  # 老人默认档也夹少量形近字


def test_repeat_echo_is_framed_and_never_a_role_swap():
    from personas.humanize import confusion as C
    for t in C.CONFIRM_TEMPLATES:
        assert "你" in t and "{echo}" in t  # 复述对方的话总带“你是说 / 你说的”框架
    swaps = ["要不我帮您转接高级专员", "阿姨您删视频我等", "请您马上转账", "你赶紧把钱转过来"]
    for seed in range(200):
        h = Humanizer(profile="retiree", seed=seed, weights={"repeat": 10})
        for ctx in swaps:
            out = h.apply("好的，我在弄。", context=ctx + "。验证码五分钟内有效").text
            for s in swaps:
                assert s not in out, out


def test_repeat_echo_prefers_key_phrase():
    h = Humanizer(profile="retiree", seed=1)
    seen = {h._echo("您的资金涉嫌洗钱，必须转到安全账户配合核查") for _ in range(30)}
    assert seen <= {"洗钱", "安全账户"}, seen
    assert h._echo("您好我是客服请您配合") is None  # 只有人称 / 祈使分句时宁可用通用确认
