"""老人聊天体（docs/REALISM.md「错字率校准」）：可配置错字密度与手写档、会话级错字映射、拆条、表情代逗号、
固定标点风格、第三人称自称 / 道歉 / “你忙吧”、禁用年轻网络用语与美篇体、数字串前后不动。"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
from personas.humanize import PERSONA_PROFILES, PROFILES, Humanizer, han_count, protected_mask  # noqa: E402
from personas.humanize import confusion as C  # noqa: E402
from personas.humanize.core import COOP_INTENTS, cue_frozen  # noqa: E402

CORE = json.loads((ROOT / "site" / "assets" / "core" / "personas.json").read_text(encoding="utf-8"))
EMOJI_RE = re.compile(r"\[[^\]]{1,3}\]|[\U0001F300-\U0001FAFF]")


def _t(t):
    return t if isinstance(t, str) else t["t"]


def engine_pool(pid):
    p = next(x for x in CORE["personas"] if x["id"] == pid)
    return [_t(t).replace("{call}", "小伙子").replace("{intel}", "卡号尾号3445").replace("{ask}", "")
            for v in p["templates"].values() for t in v]


def rate(pid, handwriting=False, seeds=40, turns=40, **kw):
    lines = engine_pool(pid)
    typ = n = 0
    for s in range(seeds):
        h = Humanizer(profile=pid, seed=s, handwriting=handwriting, **kw)
        for i in range(turns):
            r = h.apply(lines[(s * 13 + i * 7) % len(lines)])
            typ += sum(int(o.split(":")[1]) for o in r.ops if o.startswith("typo:"))
            n += han_count(EMOJI_RE.sub("", r.text))
    return 100 * typ / n


def test_profiles_live_in_personas_json():
    assert set(PROFILES) == {"retiree", "mom", "graduate", "shop_owner"}
    assert set(PERSONA_PROFILES) == {p["id"] for p in CORE["personas"]} == {"wang", "chen", "lin", "zheng"}
    assert {k: v["base"] for k, v in PERSONA_PROFILES.items()} == {
        "wang": "retiree", "chen": "mom", "lin": "graduate", "zheng": "shop_owner"}
    for p in list(PROFILES.values()) + list(PERSONA_PROFILES.values()):
        assert p["punctStyle"] in ("comma", "none")
        assert p["typoPer100"] > 0 and p["handwritingTypoPer100"] >= p["typoPer100"]


def test_wang_default_band_and_handwriting_tier():
    default, hw = rate("wang"), rate("wang", handwriting=True)
    assert 2.0 <= default <= 4.0, default  # 默认档：每百字 2–4
    assert hw >= 10.0, hw                  # 手写档：每百字 10+，只在 handwriting 打开时
    assert Humanizer(profile="wang").handwriting is False


def test_other_personas_raised_but_below_wang():
    wang = rate("wang")
    for pid in ("chen", "zheng"):
        r = rate(pid)
        assert 1.5 <= r <= 3.0 and r < wang, (pid, r)
    yu = rate("lin")
    assert 0.6 <= yu <= 1.8, yu
    assert rate("wang", typo_per_100=2.0) >= 1.6  # 档位可配置，王阿姨不低于每百字 2 个（允许抽样误差）


def test_typo_map_is_consistent_within_a_session_and_survives_correction():
    h = Humanizer(profile="wang", seed=3, ops=["typo"], typo_per_100=30)
    line = "我已经知道了，手机上的短信我看了，到底是哪个银行？"
    seen = {}
    for i in range(30):
        ctx = "你打错字了吧？是“已经”不是“以经”" if i % 3 == 0 else "快点"
        out = h.apply(line, ctx).text
        for orig, rep in h.typo_map.items():
            if rep in out:
                seen.setdefault(orig, set()).add(rep)
    assert seen and all(len(v) == 1 for v in seen.values()), seen  # 同一个词一场里只错成一种写法
    # 映射建立后再也不改（被指出也照错）
    snap = dict(h.typo_map)
    for _ in range(10):
        h.apply(line, "你字打错了")
    assert all(h.typo_map[k] == v for k, v in snap.items())


def test_typos_concentrate_on_common_words_and_places():
    words = set(C.COMMON_WORDS) | set(C.PLACE_WORDS) | set(C.HOMOPHONE_WORDS)
    text = "我明天去派出所，然后到超市买点东西，你把微信发我，手机号也行"
    hit_words = hit_chars = 0
    for s in range(300):
        h = Humanizer(profile="wang", seed=s, ops=["typo"])
        h.apply(text)
        for k in h.typo_map:
            if k in words:
                hit_words += 1
            else:
                hit_chars += 1
    assert hit_words > 2 * hit_chars, (hit_words, hit_chars)


def test_punct_style_fixed_per_persona():
    for pid, style in (("wang", "comma"), ("chen", "none"), ("lin", "none"), ("zheng", "comma")):
        lines = engine_pool(pid)
        for s in range(15):
            h = Humanizer(profile=pid, seed=s)
            for x in lines[:60]:
                out = h.apply(x).text
                core, fz = protected_mask(out, C.NAME_CUES), cue_frozen(out)
                for i, ch in enumerate(out):
                    adj = core[i] or (i > 0 and core[i - 1]) or (i + 1 < len(out) and core[i + 1]) or fz[i]
                    if adj or ch not in "，,。！？!?；;：:、…~～":
                        continue
                    if style == "comma":
                        assert ch == "，" or (ch in "？?" and (i == len(out) - 1 or out[i + 1] == "\n")), out
                    else:
                        assert False, (pid, out)


def test_split_and_emoji_comma_for_elders_only():
    lines = engine_pool("wang")
    h = Humanizer(profile="wang", seed=11)
    outs = [h.apply(lines[i % len(lines)], intent="generic") for i in range(300)]
    assert sum(len(r.parts) > 1 for r in outs) > 40
    assert sum("emoji" in r.ops for r in outs) > 20
    for r in outs:
        assert all(p.strip() for p in r.parts)
    g = Humanizer(profile="lin", seed=11)
    assert not any(EMOJI_RE.search(g.apply(x).text) for x in engine_pool("lin")[:200])


AGE_DECL = re.compile(r"今年.{1,3}了|一把年纪|[六七]十[一二]?了|岁数大了|年纪大了")


def test_selfref_apology_closing_no_age_declaration():
    """自称、道歉、收尾照常出现；不再主动报年龄（年龄感只靠节奏和偶尔没听清）。"""
    lines = engine_pool("wang")
    tot = {"selfref": 0, "apology": 0, "closing": 0}
    for pid in ("wang", "chen", "zheng", "retiree"):
        assert "ageLines" not in PERSONA_PROFILES.get(pid, PROFILES.get(pid, {}))
    for s in range(20):
        h = Humanizer(profile="wang", seed=s)
        prev = None
        for i in range(40):
            src = lines[(s * 7 + i) % len(lines)]
            r = h.apply(src)
            for k in tot:
                tot[k] += k in r.ops
            assert "age" not in r.ops, r.ops
            assert not AGE_DECL.search(r.text) or AGE_DECL.search(src), r.text
            extra = next((k for k in ("apology", "closing") if k in r.ops), None)
            assert not (extra and extra == prev), r.ops  # 同一种不连续两条
            prev = extra
    assert all(v > 0 for v in tot.values()), tot
    h = Humanizer(profile="wang", seed=1, weights={"repeat": 0})
    h.self_ref_rate = 1.0
    assert "阿姨" in h.apply("我在找呢").text
    assert "阿姨们" not in h.apply("我们这边好了").text


def test_no_digression_after_cooperative_reply():
    for s in range(200):
        h = Humanizer(profile="wang", seed=s, weights={"digress": 50})
        for it in COOP_INTENTS:
            assert "digress" not in h.apply("好，我照你说的点了，现在出来一个绿色的勾", intent=it).ops
    assert any("digress" in Humanizer(profile="wang", seed=s, weights={"digress": 50}).apply("嗯嗯你说", intent="generic").ops
               for s in range(20))
    assert not any("打游戏" in d for d in PERSONA_PROFILES["lin"]["digressions"])


BANNED = C.BANNED_YOUTH_SLANG + C.BANNED_ESSAY_STYLE


def _all_persona_text():
    out = []
    for p in CORE["personas"]:
        out += [_t(t) for v in p["templates"].values() for t in v] + list(p["asks"].values())
        out += [_t(t) for v in p["openings"].values() for t in (v if isinstance(v, list) else [v])]
    for prof in list(PROFILES.values()) + list(PERSONA_PROFILES.values()):
        for k in ("digressions", "apologies", "closings", "emojis", "selfRef"):
            out += list(prof.get(k) or [])
    out += C.DIGRESSIONS + C.CONFIRM_TEMPLATES + C.CONFIRM_GENERIC + C.ASR_FILLERS
    for tab in (C.HOMOPHONE_WORDS, C.COMMON_WORDS, C.PLACE_WORDS, C.HOMOPHONE_CHARS, C.SHAPE_CHARS, C.HANDWRITING_CHARS):
        out += [a for v in tab.values() for a in v]
    for p in CORE["personas"]:  # 提示词资料与语音示范句（原 prompts/*.yaml 已并入 personas.json）
        pr = p.get("prompt") or {}
        out += list(pr.get("sampleLines") or []) + list(pr.get("elicitMoves") or []) + list(pr.get("stallMoves") or [])
        out += [x["reply"] for x in p.get("voiceShots") or []]
    return out  # promptRules 本身点名了禁用词，不在扫描范围


def test_no_youth_slang_or_essay_style_in_sources():
    assert "yyds" in C.BANNED_YOUTH_SLANG and "emmm" in C.BANNED_YOUTH_SLANG and "岁月静好" in C.BANNED_ESSAY_STYLE
    bad = [(w, t) for t in _all_persona_text() for w in BANNED if w.lower() in t.lower()]
    assert not bad, bad[:5]


def test_no_youth_slang_or_essay_style_in_outputs():
    for pid in tuple(PERSONA_PROFILES) + tuple(PROFILES):
        for hw in (False, True):
            h = Humanizer(profile=pid, seed=5, handwriting=hw)
            for x in engine_pool(pid if pid in PERSONA_PROFILES else "wang")[:120]:
                out = h.apply(x, "你快点把验证码发我").text.lower()
                assert not any(w.lower() in out for w in BANNED), out


def test_common_prompt_rule_forbids_slang_and_essay_style():
    text = "\n".join(CORE["promptRules"])
    assert "yyds" in text and "美篇" in text


# ---------------------------------------------------------------- 数字串保护
DIGIT_LINES = [
    "好的，卡号尾号3454对吧？我记下了。", "你说转5000块到6222020200112233445是吧，我找找笔。",
    "那个网址 refund-tb.example 我打不开啊，你再发一遍？", "地址 TQ7xM6hYpCzD8vNp1qJ3kR5sW9uL2aBcDe 太长了，我抄不下来。",
    "电话139****2233是你们的吗？我已经知道了。", "我只有两千块，转一千块行不行？", "6222020200112233445，这个对吧，我已经知道了",
    "你说的是https://refund-tb.example/dl，我点不开。", "尾号3445", "我现在去银行，转5000元，你等我。好的。",
    "验证码我看不清，前两位是12吧，后面的我找找。", "那我转到13900112233这个号上？我先找找眼镜。",
    # 逐字报号的中文数字（可夹空格）、平台名 / 情报字段词（含“微 信”）同等保护
    "我念给你听，幺三九 幺幺 二二三三，你记一下", "卡号是六二二二 零二零二，后面我看不清", "房间号拐洞幺，进去以后呢", "加微 信 kefu，还是支付宝，你说哪个", "幺 三", "零 零 幺 幺",
]


def _spans(text):
    m = protected_mask(text)
    out, i = [], 0
    while i < len(text):
        if m[i]:
            j = i
            while j < len(text) and m[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def check_digit_neighbors(src, out):
    """输入里每个受保护片段（数字串 / 网址 / 钱包 / 打码 / 金额）在输出里原样出现，且紧挨的前后一个字符不变。"""
    ss, os_ = _spans(src), _spans(out)
    k = 0
    for a, b in ss:
        frag = src[a:b]
        left = src[a - 1] if a > 0 else None
        right = src[b] if b < len(src) else None
        while k < len(os_) and out[os_[k][0]:os_[k][1]] != frag:
            k += 1
        assert k < len(os_), (src, out)
        x, y = os_[k]
        assert (out[x - 1] if x > 0 else None) == left, (src, out)
        assert (out[y] if y < len(out) else None) == right, (src, out)
        k += 1


@pytest.mark.parametrize("pid", ["wang", "chen", "lin", "zheng", "retiree", "mom", "graduate", "shop_owner"])
@pytest.mark.parametrize("hw", [False, True])
def test_digit_strings_untouched_and_nothing_inserted_next_to_them(pid, hw):
    for s in range(40):
        h = Humanizer(profile=pid, seed=s, handwriting=hw, weights={"repeat": 3, "digress": 3})
        h.emoji_rate, h.split_rate = 0.9, 0.9
        for i, src in enumerate(DIGIT_LINES):
            r = h.apply(src, "转到安全账户 6222020200112233445")
            check_digit_neighbors(src, r.text)
            assert "\n" not in [r.text[x - 1:x] for x, _ in _spans(r.text) if x > 0]


@pytest.mark.parametrize("pid", ["wang", "chen", "zheng", "retiree", "shop_owner", "lin", "mom"])
@pytest.mark.parametrize("hw", [False, True])
def test_comma_after_name_value_kept_and_protected_words_not_typoed(pid, hw):
    from personas.humanize.confusion import PROTECT_WORDS
    lines = ["户名周杰，农业银行，卡号我抄好了", "收款人王建国，开户行建设银行", "姓名张三，电话你再说一遍", "户名：李某某，我记下了"]
    vals = ["周杰，", "王建国，", "张三，", "李某某，"]
    for s in range(60):
        h = Humanizer(profile=pid, seed=s, handwriting=hw, weights={"asr": 3})
        h.emoji_rate, h.split_rate = 0.9, 0.9
        for src, v in zip(lines, vals):
            out = h.apply(src).text
            assert v in out, (pid, src, out)
            for w in PROTECT_WORDS:
                if w in src:
                    assert w in out, (w, out)
        t = h.apply("加微 信 kefu，房间号拐洞幺，会议号你再说一遍").text
        for w in ("微 信", "房间号", "会议号", "拐洞幺"):
            assert w in t, (w, t)


@pytest.mark.parametrize("pid", ["wang", "chen", "lin", "zheng", "retiree"])
@pytest.mark.parametrize("hw", [False, True])
def test_whole_message_short_spoken_digits_kept(pid, hw):
    for s in range(40):
        h = Humanizer(profile=pid, seed=s, handwriting=hw, weights={"repeat": 3, "digress": 3})
        h.emoji_rate, h.split_rate = 0.9, 0.9
        for src in ("三三，", "九", "幺两"):
            out = h.apply(src, "转到安全账户").text
            d = src.replace("，", "")
            assert out.startswith(d), (src, out)
            nx = out[len(d):len(d) + 1]
            assert nx in ("", "，"), (src, out)
