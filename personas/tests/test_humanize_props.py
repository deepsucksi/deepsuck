"""#129：跑题句不编道具、对方没开口不插跑题句、文字回复不带表情（JS 同规则见 tests/humanize_props.test.js）。"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from personas.humanize import Humanizer  # noqa: E402
from personas.humanize import confusion as C  # noqa: E402

PERSONAS = ("wang", "chen", "lin", "zheng", "retiree", "mom", "graduate", "shop_owner")
AUDIT_PROPS = ("药", "买菜", "广场舞", "外孙")  # 抽检抓到的
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]|\\[(?:强|玫瑰|握手|抱拳|微笑)\\]")
LINES = ["好的，你说吧，我听着。", "哦…卡号我找找，你等一下。", "这个我得问问家里人。", "你再说一遍？我没听清。"]


def test_pools_have_no_invented_props():
    for pid in PERSONAS:
        h = Humanizer(profile=pid, seed=1)
        assert len(h.digressions) >= 3, (pid, h.digressions)
        for d in h.digressions:
            assert not any(w in d for w in AUDIT_PROPS), (pid, d)
            assert not any(w in d and w not in h.props_ok for w in C.DIGRESSION_PROPS), (pid, d)


def test_props_ok_follow_background():
    assert "等下娃在哭" in Humanizer(profile="chen", seed=1).digressions  # 宝妈带娃，背景里有
    assert "等一哈有客人来买东西" in Humanizer(profile="zheng", seed=1).digressions  # 看店，背景里有
    assert not any("药" in d or "广场舞" in d for d in Humanizer(profile="wang", seed=1).digressions)


def test_outputs_never_carry_props_or_emoji():
    for pid in PERSONAS:
        for seed in range(40):
            h = Humanizer(profile=pid, seed=seed, weights={"digress": 20})
            for i, t in enumerate(LINES * 3):
                r = h.apply(t, context="你好，我这边有点事", intent="generic")
                added = r.text.replace(t, "")
                assert not any(w in r.text and w not in t for w in AUDIT_PROPS), (pid, seed, r.text)
                assert not EMOJI.search(r.text), (pid, seed, r.text)
                assert "emoji" not in r.ops


def test_no_digression_before_scammer_speaks():
    for pid in PERSONAS:
        for seed in range(60):
            h = Humanizer(profile=pid, seed=seed, weights={"digress": 50})
            assert "digress" not in h.apply("喂？哪位").ops  # 开场白：没有 context
            assert "digress" not in h.apply("喂？哪位", context="  ").ops
    assert any("digress" in Humanizer(profile="wang", seed=s, weights={"digress": 50}).apply("嗯，你说。", context="喂，你好").ops
               for s in range(20))
