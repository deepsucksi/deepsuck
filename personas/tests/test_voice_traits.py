import json
import re

import pytest

from personas import voice_traits as V  # noqa: E402
from personas.humanize import confusion as C  # noqa: E402

PERSONAS = V.personas()
CONTENT = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
# 混淆表里的“错误写法”：语音特征的任何文本都不应出现
WRONG = sorted({w for alts in C.HOMOPHONE_WORDS.values() for w in alts}, key=len, reverse=True)

# 线上已缓存音频的旧条目（不 import voice，避免引入语音依赖）；王阿姨删去“哎哟……”，其余顺序不变。
# 小林的口头语与上线版本一致（同一音色，缓存可复用）；李大爷已下线，资料在 personas/archive/li.json
CURRENT = {
    "wang": ["嗯……", "啊？", "哎……", "你说啥？", "等一下啊……", "我听听啊……", "哦……"],
    "lin": ["呃……", "嗯嗯", "啊？", "等下哈", "哦哦", "啊这……", "嗯……我想想", "诶？"],
}


def _diff(word, heard):
    """heard 中与 word 不同的那一段（去掉公共前后缀）：反问里至少要复述听错的部分。"""
    i = 0
    while i < min(len(word), len(heard)) and word[i] == heard[i]:
        i += 1
    j = 0
    while j < min(len(word), len(heard)) - i and word[-1 - j] == heard[-1 - j]:
        j += 1
    return heard[i:len(heard) - j]


def spoken_texts(t):
    yield from t["backchannel"]
    for m in t["mishear"]:
        yield m["ask"]
    yield from t["rhythm"]["chitchat_lines"]


def test_covers_all_personas():
    from personas import prompt as P
    assert set(PERSONAS) == set(P.PERSONA_IDS) == {"wang", "chen", "lin", "zheng"}


@pytest.mark.parametrize("pid", sorted(PERSONAS))
def test_schema(pid):
    t = PERSONAS[pid]
    bc = t["backchannel"]
    assert 8 <= len(bc) <= 12 and len(set(bc)) == len(bc)
    for line in bc:
        assert isinstance(line, str) and 1 <= len(CONTENT.findall(line)) <= 7, line
        assert not re.search(r"\d", line)
    assert len(t["mishear"]) >= 3
    for m in t["mishear"]:
        assert m["word"] and m["heard"] and m["word"] != m["heard"]
        assert _diff(m["word"], m["heard"]) in m["ask"], m
    s = t["speech"]
    assert s["rate"] in ("快", "中", "慢") and 1.5 <= s["chars_per_sec"] <= 8
    assert isinstance(s["dialect_words"], list) and isinstance(s["accent"], bool) and s["accent_desc"]
    r = t["rhythm"]
    assert r["pre_speech_pause"] in ("短", "中", "长") and r["chitchat"] in ("低", "中", "高")
    lo, hi = r["pause_ms"]
    assert 0 <= lo < hi <= 3000
    a, b = r["chitchat_every_turns"]
    assert 1 <= a <= b
    assert r["chitchat_lines"]


@pytest.mark.parametrize("pid", sorted(PERSONAS))
def test_spoken_text_has_no_typos_digits_or_emoji(pid):
    for text in spoken_texts(PERSONAS[pid]):
        assert not any(w in text for w in WRONG), text
        assert not re.search(r"\d{2,}", text), text
        assert not EMOJI.search(text) and "*" not in text, text


def test_rate_and_pause_are_consistent():
    order = {"短": 0, "中": 1, "长": 2}
    mids = {}
    for t in PERSONAS.values():
        mids.setdefault(order[t["rhythm"]["pre_speech_pause"]], []).append(sum(t["rhythm"]["pause_ms"]) / 2)
    levels = sorted(mids)
    for a, b in zip(levels, levels[1:]):
        assert max(mids[a]) < min(mids[b])


def test_fillers_drop_in_compatible():
    f = V.fillers()
    assert all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in f.values())
    for pid, cur in CURRENT.items():
        assert f[pid][: len(cur)] == cur


def test_current_fillers_match_voice_source():
    """voice/persona.py 不再手写 FILLERS，运行时从 personas.json 的 voiceTraits 读取（只读源码文本，不 import voice）；
    CURRENT（线上已缓存音频的旧条目）由上面的测试保证与 personas.json 一致。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "voice" / "persona.py").read_text(encoding="utf-8")
    assert "voiceTraits" in src and "personas.json" in src and "FILLERS = load_fillers()" in src
    assert not re.search(r"^FILLERS\s*=\s*\{", src, re.M), "FILLERS 仍在 voice/persona.py 里手写"
    for pid, cur in CURRENT.items():
        assert not any(f'"{pid}": {json.dumps(cur[:3], ensure_ascii=False)[:-1]}' in src for _ in [0]), f"{pid} 口头语仍在 voice/persona.py 里手写"


AGE_HEARING = re.compile(r"大点声|听不清|哎哟|耳朵|耳背|老花|眼神|孙子|年纪|岁数")


@pytest.mark.parametrize("pid", sorted(PERSONAS))
def test_no_age_or_hearing_labels_in_spoken_texts(pid):
    """口头语、听错反问、扯家常都不拿年龄、听力、眼神、孙子说事。"""
    for line in spoken_texts(PERSONAS[pid]):
        assert not AGE_HEARING.search(line), (pid, line)
