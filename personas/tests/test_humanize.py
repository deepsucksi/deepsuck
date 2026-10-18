import re

import pytest

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
    def changed(i):
        return sum(humanize(TEXT, i, seed=s) != TEXT for s in range(200))
    lo, mid, hi = changed(0.1), changed(0.5), changed(1.0)
    assert lo < mid < hi
    assert hi > 180


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
    pool = ["我先去收个快递"]
    h = Humanizer(1.0, seed=4, ops=["digress"], weights={"digress": 10}, digressions=pool)
    assert pool[0] in h("你说吧")


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
    assert set(OPS) == {"typo", "punct", "asr", "repeat", "digress", "dialect"}


def test_cli(capsys):
    from personas.humanize.__main__ import main
    assert main(["你说什么？", "--profile", "shop_owner", "--seed", "1", "-n", "2", "--json"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and all('"ops"' in x for x in lines)
