"""可程序化的“真人化”后处理：让机器人人设的文字回复更像真人随手打的字或语音转文字。

用法::

    from personas.humanize import humanize, Humanizer
    humanize("好的，我已经知道了。", intensity=0.5, seed=7)
    h = Humanizer(profile="wang", seed=1)            # 一个实例 = 一整场对话（错字映射、跑题、道歉次数都按场记）
    h.apply("你说的账户是哪个银行的？", context="转到这个账户").text

设计约束：

- 只做“看得懂”的扰动：同音/形近错别字、标点风格、语音转文字式断句与口头语、重复确认、跑题、方言词、
  第三人称自称、道歉 / “你忙吧”收尾、表情代替逗号、一句话拆成几条发；
- 数字串（号码、卡号、金额、钱包地址、网址、打码值 ``*``）和占位符 ``{...}`` 不改动，而且它们**内部和紧挨着的
  前后一个字符**都不插入错字、表情、标点，也不在那里拆条（情报提取依赖这些位置）；
- 错字按“每百字错字数”配置（``typoPer100``；``handwriting`` 档用 ``handwritingTypoPer100``），集中在常用词与地名；
  同一个实例里同一个词一旦写错，后面再出现时大概率照同样的错写（会话级错字映射），被对方指出也不改；
- 与 JS 版 ``site/assets/js/humanize.js`` 逐字一致：同一个 seed、同样的调用序列得到同样的输出（mulberry32 随机数，
  tests/fixtures/humanize.json 由 JS 生成、pytest 逐项比对）；
- intensity=0 时原样返回；不负责安全过滤：输出仍然要经过守卫。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import confusion as C
from .profiles import resolve

MIN_DIGRESSIONS = 3  # 预设跑题句滤掉道具后少于这个数就用默认池补（#129）
OPS: Tuple[str, ...] = ("dialect", "selfref", "repeat", "digress", "extras", "typo", "asr", "punct", "emoji", "split")
MODES = ("chat", "voice")
PUNCT_STYLES = ("comma", "none")

# intensity=1 时每种操作的基准概率 / 比例
BASE_RATES: Dict[str, float] = {
    "typo": 10.0,     # 没有配置 typoPer100 时：每百字错字数 = 10 × intensity × 错字倍数
    "punct": 0.9,     # 没有固定标点风格时，整条文本随机应用一种标点风格的概率
    "asr": 1.0,       # 语音模式下改写断句的概率
    "repeat": 0.4,    # 追加/前置一句重复确认的概率
    "digress": 0.25,  # 插入一句跑题的概率
    "dialect": 1.0,   # 设置了方言时，每个匹配处被替换的概率 = 0.5 + 0.5 * 该值 * intensity
}
STICKY = 0.6          # 已写错过的词再次出现时，照同样的错写的概率（不受本条配额限制，但计入整场错字数）
DEBT_MAX = 2.0        # 错字“欠账”的上下限：短句攒着、长句还上，整场密度贴近目标
# 配合类意图：回复本身是在“照做 / 确认 / 找东西”，后面不接跑题句（接了读起来像故意打岔）
COOP_INTENTS = ("coop_step", "fake_progress", "confirm_intel", "re_ask")

_DIGITS = set("0123456789０１２３４５６７８９*＊")
_CN_NUM = set("零〇一二两三四五六七八九十百千万亿")
_CN_UNIT = set("块元")
_ASCII_TAIL = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/@-")
_SENT_END = "。！？!?"
_PUNCT = "，,。！？!?；;：:、…~～"
_CLAUSE_SEP = "，,。！？!?；;…~～"
_ECHO_SEP = "，,。！？!?；;：:…~～ \t\n"


def _mulberry32(seed: int):
    state = [seed & 0xFFFFFFFF]

    def rng() -> float:
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rng


class _Rand:
    """与 JS 版相同的取整方式：choice = seq[floor(r × n)]，洗牌为 Fisher–Yates。"""

    def __init__(self, seed: Optional[int] = None, rng=None):
        if rng is not None:
            self._r = rng.random if hasattr(rng, "random") else rng
        else:
            self._r = _mulberry32(random.getrandbits(32) if seed is None else int(seed))

    def random(self) -> float:
        return self._r()

    def below(self, n: int) -> int:
        return int(math.floor(self._r() * n))

    def choice(self, seq):
        return seq[self.below(len(seq))]


@dataclass
class Result:
    text: str
    ops: List[str] = field(default_factory=list)  # 实际生效的操作，便于调试与评测
    parts: List[str] = field(default_factory=list)  # 拆条后的各条消息（text = "\n".join(parts)）


def _is_han(c: str) -> bool:
    return "\u4e00" <= c <= "\u9fff"


def han_count(text: str) -> int:
    return sum(_is_han(c) for c in text)


def _find_all(text: str, word: str) -> List[int]:
    out, i = [], text.find(word)
    while word and i >= 0:
        out.append(i)
        i = text.find(word, i + len(word))
    return out


def protected_mask(text: str, keep: Sequence[str] = ()) -> List[bool]:
    """数字串、打码值、英文 / 网址 / 钱包地址、中文数字金额、占位符 {...} 与 keep 里的词。"""
    n = len(text)
    m = [False] * n
    i = 0
    while i < n:
        c, j = text[i], i
        if c == "{":
            k = i + 1
            while k < n and text[k] not in "{}":
                k += 1
            if k < n and text[k] == "}":
                j = k + 1
        elif c in _DIGITS:
            while j < n and text[j] in _DIGITS:
                j += 1
        elif ("A" <= c <= "Z") or ("a" <= c <= "z"):
            while j < n and text[j] in _ASCII_TAIL:
                j += 1
        elif c in C.SPOKEN_DIGITS and _spoken_run(text, i) >= 0:
            j = _spoken_run(text, i)
        elif c in _CN_NUM:
            k = i
            while k < n and text[k] in _CN_NUM:
                k += 1
            if k < n and text[k] in _CN_UNIT:
                j = k + 1
            elif k - i >= 3:
                j = k
        if j > i:
            for x in range(i, j):
                m[x] = True
            i = j
        else:
            i += 1
    for w in keep:
        for s in _find_all(text, w) if w else []:
            for x in range(s, s + len(w)):
                m[x] = True
    for w in C.PROTECT_WORDS:
        for s, e in _find_spaced(text, w):
            for x in range(s, e):
                m[x] = True
    return m


def _spoken_run(text: str, i: int) -> int:
    """从 i 开始的逐字报号串（spokenDigits，字间可夹单个空格）：够格时返回串尾（不含），否则 -1。"""
    n, k, cnt, last, spaced = len(text), i, 0, -1, False
    while k < n:
        if text[k] in C.SPOKEN_DIGITS:
            cnt += 1
            last = k
            k += 1
        elif text[k] == " " and cnt and k + 1 < n and text[k + 1] in C.SPOKEN_DIGITS:
            spaced = True
            k += 1
        else:
            break
    # 3 个以上；或 2 个且字间有空格（“幺 三”）；或整条消息就是这串数字（跨回合拆开报号时的短段）
    whole = not text[:i].strip() and not text[last + 1:].strip(" ，,。")
    return last + 1 if cnt >= 3 or (cnt >= 2 and spaced) or (cnt >= 1 and whole) else -1


def _whole_spoken(text: str) -> List[str]:
    """整条消息（去掉首尾空白与逗号句号）就是一段逐字报号的数字时，返回这段数字，否则 []。"""
    i = len(text) - len(text.lstrip())
    if i >= len(text) or text[i] not in C.SPOKEN_DIGITS:
        return []
    j = _spoken_run(text, i)
    return [text[i:j]] if j > 0 and not text[j:].strip(" ，,。") else []


def _find_spaced(text: str, word: str) -> List[Tuple[int, int]]:
    """word 在 text 里的出现（字与字之间允许夹一个空格，如“微 信”），返回 [start, end)。"""
    out, n, L = [], len(text), len(word)
    i = 0
    while L and i < n:
        if text[i] == word[0]:
            k, q = i + 1, 1
            while q < L and k < n:
                if text[k] == word[q]:
                    k += 1
                    q += 1
                elif text[k] == " " and k + 1 < n and text[k + 1] == word[q]:
                    k += 1
                else:
                    break
            if q == L:
                out.append((i, k))
                i = k
                continue
        i += 1
    return out


_NAME_VALUE_LEAD = "：: "


def _name_value_sep(text: str) -> List[int]:
    """“户名周杰，农业银行”里人名后面的那个分隔符位置：提示词后（可隔冒号 / 空格）1–4 个汉字，紧跟的标点或空格。"""
    out = []
    for w in C.NAME_CUES:
        for s in _find_all(text, w):
            k = s + len(w)
            while k < len(text) and text[k] in _NAME_VALUE_LEAD:
                k += 1
            v = k
            while v < len(text) and v - k < 4 and _is_han(text[v]):
                v += 1
            if v > k and v < len(text) and (text[v] in _PUNCT or text[v] == " "):
                out.append(v)
    return out


def _halo(m: List[bool]) -> List[bool]:
    n = len(m)
    return [m[i] or (i > 0 and m[i - 1]) or (i + 1 < n and m[i + 1]) for i in range(n)]


def cue_frozen(text: str) -> List[bool]:
    """紧跟在 NAME_CUES（户名、收款人……）后面的那个字符：不改标点、不在那里断句 / 拆条 / 放表情。"""
    m = [False] * len(text)
    for w in C.NAME_CUES:
        for s in _find_all(text, w):
            e = s + len(w)
            if e < len(text):
                m[e] = True
    for v in _name_value_sep(text):  # 人名后面的逗号也不动（语音断句删掉它，“周杰农业银行”会被读成人名）
        m[v] = True
    return m


def digit_safe_positions(text: str, keep: Sequence[str] = ()) -> List[bool]:
    """True = 这个位置可以改动（不在受保护片段内，也不紧挨着它）。测试与评测用。"""
    return [not x for x in _halo(protected_mask(text, keep))]


class Humanizer:
    """带随机种子与强度参数的真人化处理器；一个实例对应一整场对话。

    参数：
        intensity: 0–1，总体强度（影响重复确认、跑题、方言、断句；错字密度另由 typo_per_100 决定）；
        seed: 随机种子；同一个实例连续调用会推进同一个随机序列；
        mode: "chat"（打字）或 "voice"（语音输入：按口语断句、加口头语）；
        dialect: None 或 confusion.DIALECT 的键；
        ops: 启用的操作集合，默认全部（chat 不做 asr；voice 没有固定标点风格时不做 punct）；
        weights: 每种操作的强度倍数，例如 {"typo": 0.5}；
        digressions: 跑题句子池；keep: 额外保护、不做任何改动的词；
        profile: 预设名（retiree / mom / graduate / shop_owner）或人设 id（wang / chen / lin / zheng），显式参数优先；
        max_typos: 每条最多几处新错字；
        typo_per_100: 每百字错字目标（覆盖预设）；
        handwriting: 手写输入档：错字密度改用 handwritingTypoPer100，并启用手写识别错的高频形近字；
        shape_typos: 默认档是否夹少量形近字（默认：打字模式开、语音模式关，预设可单独设置）；
        punct_style: "comma"（一逗到底）/ "none"（全不打，空格断开）/ None（每条随机一种，旧行为）。
    """

    def __init__(self, intensity: Optional[float] = None, seed: Optional[int] = None, *, mode: Optional[str] = None,
                 dialect: Optional[str] = None, ops: Optional[Iterable[str]] = None,
                 weights: Optional[Dict[str, float]] = None, digressions: Optional[Sequence[str]] = None,
                 keep: Sequence[str] = (), profile: Optional[str] = None, max_typos: Optional[int] = None,
                 rng=None, handwriting: Optional[bool] = None, typo_per_100: Optional[float] = None,
                 shape_typos: Optional[bool] = None, punct_style: Optional[str] = None):
        prof = resolve(profile) if profile else {}
        self.profile = profile
        self.intensity = float(prof.get("intensity", 0.3) if intensity is None else intensity)
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("intensity must be within [0, 1]")
        self.mode = mode or prof.get("mode", "chat")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.dialect = dialect if dialect is not None else prof.get("dialect")
        if self.dialect is not None and self.dialect not in C.DIALECT:
            raise ValueError(f"unknown dialect: {self.dialect}")
        self.punct_style = punct_style if punct_style is not None else prof.get("punctStyle")
        if self.punct_style is not None and self.punct_style not in PUNCT_STYLES:
            raise ValueError(f"punct_style must be one of {PUNCT_STYLES}")
        if ops is None:
            ops = prof.get("ops")
        if ops is None:
            drop = {"asr"} if self.mode == "chat" else (set() if self.punct_style else {"punct"})
            ops = [o for o in OPS if o not in drop]
        self.ops = set(ops)
        unknown = self.ops - set(OPS)
        if unknown:
            raise ValueError(f"unknown ops: {sorted(unknown)}")
        self.weights = {**prof.get("weights", {}), **(weights or {})}
        self.props_ok = tuple(prof.get("propsOk") or ())
        # #129：跑题句不编道具——含人设背景里没有的道具词（吃药、买菜、广场舞、外孙……）的句子不用（只改选取，不改文字）
        self.digressions = [d for d in (digressions or prof.get("digressions") or C.DIGRESSIONS) if not self._invents_prop(d)]
        if not digressions and len(self.digressions) < MIN_DIGRESSIONS:
            # 预设的跑题句滤掉道具后不够（王阿姨只剩一句），用默认池里同样不编道具的句子补上，免得一句话反复出现
            self.digressions += [d for d in C.DIGRESSIONS if d not in self.digressions and not self._invents_prop(d)]
        self.keep = tuple(keep) + tuple(prof.get("keep", ())) + tuple(C.NAME_CUES)  # 人名提示词本身不写错
        self._apply_keep: Tuple[str, ...] = ()
        self.handwriting = bool(prof.get("handwriting", False) if handwriting is None else handwriting)
        if shape_typos is None:
            shape_typos = prof.get("shapeTypos", self.mode == "chat")
        self.shape_typos = bool(shape_typos) or self.handwriting
        if typo_per_100 is None:
            key = "handwritingTypoPer100" if self.handwriting else "typoPer100"
            typo_per_100 = prof.get(key)
            if typo_per_100 is None and self.handwriting:
                typo_per_100 = prof.get("typoPer100")
            if typo_per_100 is None:
                typo_per_100 = BASE_RATES["typo"] * self.intensity * (3.0 if self.handwriting else 1.0)
        self.typo_per_100 = max(0.0, float(typo_per_100) * self.weights.get("typo", 1.0))
        self.max_typos = max_typos if max_typos is not None else max(1 + round(3 * self.intensity),
                                                                     int(self.typo_per_100 * 0.4) + 1)
        self.self_ref = list(prof.get("selfRef") or [])
        self.self_ref_rate = float(prof.get("selfRefRate", 0.0))
        self.apologies = list(prof.get("apologies") or [])
        self.apology_rate = float(prof.get("apologyRate", 0.0))
        self.closings = list(prof.get("closings") or [])
        self.closing_rate = float(prof.get("closingRate", 0.0))
        self.emojis = list(prof.get("emojis") or [])
        self.emoji_rate = float(prof.get("emojiComma", 0.0))
        self.split_rate = float(prof.get("split", 0.0))
        self.rng = _Rand(seed, rng)
        # 会话级状态
        self.typo_map: Dict[str, str] = {}
        self._debt = 0.0
        self._turn = 0
        self._last_extra = ""
        self._used_digressions: List[str] = []
        self._used_apologies: List[str] = []
        words = []
        for table, w in ((C.PLACE_WORDS, 4.0), (C.COMMON_WORDS, 3.0), (C.HOMOPHONE_WORDS, 2.0)):
            for k, v in table.items():
                words.append((k, v, w))
        self._words = sorted(words, key=lambda x: -len(x[0]))

    # ------------------------------------------------------------------ helpers
    def _p(self, op: str, scale: float = 1.0) -> float:
        return max(0.0, min(1.0, BASE_RATES[op] * self.weights.get(op, 1.0) * self.intensity * scale))

    def _hit(self, p: float) -> bool:
        return p > 0 and self.rng.random() < p

    def _core(self, text: str) -> List[bool]:
        return protected_mask(text, self.keep + self._apply_keep)

    def _prepend(self, piece: str, text: str, joint: str) -> Optional[str]:
        core = self._core(text)
        if text and core[0]:
            return None
        return piece + joint + text

    def _append(self, text: str, piece: str, joint: str = "。") -> Optional[str]:
        core = self._core(text)
        i = len(text)
        while i > 0 and text[i - 1] in _PUNCT:
            i -= 1
        if i < len(text):
            if i > 0 and core[i - 1]:
                return text + piece  # 保留紧挨数字的原标点，不在那里插新标点
            return text[:i] + joint + piece
        if i > 0 and core[i - 1]:
            return None
        return text + joint + piece

    def _attach(self, text: str, piece: str, prefix: bool, pre_joint: str, post_joint: str) -> Optional[str]:
        a = self._prepend(piece, text, pre_joint) if prefix else self._append(text, piece, post_joint)
        if a is None:
            a = self._append(text, piece, post_joint) if prefix else self._prepend(piece, text, pre_joint)
        return a

    def _take(self, pool: List[str], used: List[str]) -> str:
        left = [x for x in pool if x not in used] or list(pool)
        if len(left) == len(pool):
            del used[:]
        x = self.rng.choice(left)
        used.append(x)
        return x

    # ------------------------------------------------------------------ ops
    def _dialect(self, text: str) -> Tuple[str, bool]:
        if not self.dialect:
            return text, False
        p = min(1.0, 0.5 + 0.5 * self._p("dialect")) if self.intensity > 0 else 0.0
        changed = False
        for src, alts in sorted(C.DIALECT[self.dialect], key=lambda x: -len(x[0])):
            halo = _halo(self._core(text))
            out, i = [], 0
            for s in _find_all(text, src):
                e = s + len(src)
                if any(halo[s:e]) or not self._hit(p):
                    continue
                out.append(text[i:s])
                out.append(self.rng.choice(alts))
                i = e
                changed = True
            out.append(text[i:])
            text = "".join(out)
        return text, changed

    def _selfref(self, text: str) -> Tuple[str, bool]:
        if not self.self_ref or self.self_ref_rate <= 0:
            return text, False
        halo = _halo(self._core(text))
        out, n = [], 0
        for i, ch in enumerate(text):
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prv = text[i - 1] if i > 0 else ""
            if (ch == "我" and nxt not in ("们", "我") and prv not in ("自", "我") and not halo[i] and n < 2
                    and self._hit(self.self_ref_rate)):
                out.append(self.rng.choice(self.self_ref))
                n += 1
            else:
                out.append(ch)
        return "".join(out), n > 0

    def _echo(self, context: str) -> Optional[str]:
        """从对方的话里挑一个可以复述的关键短语：优先名词性关键词，没有时用不含数字 / 人称 / 祈使的 2–8 字短分句。"""
        ctx = context or ""
        keys, taken = [], [False] * len(ctx)
        for k in sorted(C.ECHO_KEYWORDS, key=len, reverse=True):
            for s in _find_all(ctx, k):
                if not any(taken[s:s + len(k)]):
                    keys.append((s, k))
                    for i in range(s, s + len(k)):
                        taken[i] = True
        keys.sort(key=lambda x: x[0])
        uniq: List[str] = []
        for _, k in keys:
            if k not in uniq:
                uniq.append(k)
        if uniq:
            return self.rng.choice(uniq)
        parts, cur = [], ""
        for ch in ctx + " ":
            if ch in _ECHO_SEP:
                if cur:
                    parts.append(cur)
                cur = ""
            else:
                cur += ch
        bad = set("0123456789０１２３４５６７８９*＊ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        parts = [x for x in parts if 2 <= len(x) <= 8 and not (set(x) & bad) and not any(w in x for w in C.ECHO_AVOID)]
        if not parts:
            return None
        return self.rng.choice(parts)

    def _repeat(self, text: str, context: Optional[str]) -> Tuple[str, bool]:
        if not self._hit(self._p("repeat")):
            return text, False
        echo = self._echo(context) if context else None
        if echo:
            line = self.rng.choice(C.CONFIRM_TEMPLATES).replace("{echo}", echo)
            joint = "" if line[-1] in _PUNCT else "，"  # 避免“清零？，先付……”这样的双标点
            out = self._attach(text, line, self.rng.random() < 0.6, joint, "。")
        else:
            line = self.rng.choice(C.CONFIRM_GENERIC)
            out = self._append(text, line, "，")
        return (out, True) if out is not None else (text, False)

    def _invents_prop(self, line: str) -> bool:
        return any(w in line and w not in self.props_ok for w in C.DIGRESSION_PROPS)

    def _digress(self, text: str, intent: Optional[str] = None, context: Optional[str] = None) -> Tuple[str, bool]:
        # #129：对方还没开口（开场白，没有 context）时不插跑题句
        if not (context or "").strip() or not self.digressions or intent in COOP_INTENTS or not self._hit(self._p("digress")):
            return text, False
        # 同一个实例（一整段对话）里跑题句不重复，用完一轮才重来
        d = self._take(self.digressions, self._used_digressions)
        out = self._attach(text, d, self.rng.random() < 0.5, "……", "。")
        return (out, True) if out is not None else (text, False)

    def _extras(self, text: str) -> Tuple[str, List[str]]:
        """道歉、“你忙吧”式收尾；同一种不连续两条出现。不再主动报年龄（年龄感只靠节奏和偶尔没听清）。"""
        done: List[str] = []
        if self.apologies and self._last_extra != "apology" and not done and self._hit(self.apology_rate):
            line = self._take(self.apologies, self._used_apologies)
            out = self._prepend(line, text, "，")
            if out is not None:
                text = out
                done.append("apology")
        if self.closings and self._last_extra != "closing" and not done and not text.rstrip().endswith(("？", "?")) \
                and self._hit(self.closing_rate):
            out = self._append(text, self.rng.choice(self.closings), "，")
            if out is not None:
                text = out
                done.append("closing")
        self._last_extra = done[0] if done else ""
        return text, done

    def _typo(self, text: str) -> Tuple[str, int]:
        rate = self.typo_per_100
        if rate <= 0 or self.max_typos <= 0:
            return text, 0
        lam = han_count(text) * rate / 100.0
        self._debt = min(self._debt + lam, lam + DEBT_MAX)
        cap = min(self.max_typos, max(1, int(math.floor(self._debt + 1.0))))
        halo = _halo(self._core(text))
        for w in C.NAME_CUES:  # 人名提示词后面 3 个字不写错（错字可能被提取器读成人名，如“户名发找”）
            for st in _find_all(text, w):
                for x in range(st + len(w), min(len(text), st + len(w) + 3)):
                    halo[x] = True
        taken = [False] * len(text)
        sites = []  # [start, end, key, alts, weight]
        for word, alts, w in self._words:
            for s in _find_all(text, word):
                e = s + len(word)
                if not any(halo[s:e]) and not any(taken[s:e]):
                    sites.append((s, e, word, alts, w))
                    for k in range(s, e):
                        taken[k] = True
        for i, ch in enumerate(text):
            if halo[i] or taken[i]:
                continue
            alts = list(C.HOMOPHONE_CHARS.get(ch, ()))
            w = 1.0
            if self.shape_typos:
                alts += C.SHAPE_CHARS.get(ch, [])
            if self.handwriting and ch in C.HANDWRITING_CHARS:
                alts += C.HANDWRITING_CHARS[ch]
                w = 2.0
            if alts:
                sites.append((i, i + 1, ch, alts, w))
        forced, rest = [], []
        for st in sites:
            if st[2] in self.typo_map:
                if len(forced) < cap and self.rng.random() < STICKY:
                    forced.append(st)
                else:
                    rest.append((st[0], st[1], st[2], st[3], st[4] * 8.0))
            else:
                rest.append(st)
        k = int(math.floor(self._debt - len(forced) + self.rng.random()))
        k = max(0, min(k, self.max_typos - len(forced), len(rest)))
        chosen = list(forced)
        for _ in range(k):
            total = 0.0
            for st in rest:
                total += st[4]
            r = self.rng.random() * total
            idx = len(rest) - 1
            for j, st in enumerate(rest):
                r -= st[4]
                if r < 0:
                    idx = j
                    break
            chosen.append(rest.pop(idx))
        self._debt = max(self._debt - len(chosen), -DEBT_MAX)
        reps = []
        for s, e, key, alts, _ in chosen:
            rep = self.typo_map.get(key)
            if rep is None:
                rep = self.rng.choice(alts)
                self.typo_map[key] = rep
            reps.append((s, e, rep))
        for s, e, rep in sorted(reps, key=lambda x: -x[0]):
            text = text[:s] + rep + text[e:]
        return text, len(reps)

    def _asr(self, text: str) -> Tuple[str, bool]:
        if not self._hit(self._p("asr")):
            return text, False
        # 切成 [分句, 其后的分隔符]，空分句并入前一个分隔符
        segs: List[List[str]] = []
        cur, sep = "", ""
        for ch in text:
            if ch in _CLAUSE_SEP:
                sep += ch
            else:
                if sep:
                    segs.append([cur, sep])
                    cur, sep = "", ""
                cur += ch
        segs.append([cur, sep])
        clean: List[List[str]] = []
        lead = ""
        for c, s in segs:
            if c.strip():
                clean.append([c.strip(), s])
            elif clean:
                clean[-1][1] += c + s
            else:
                lead += c + s
        if not clean:
            return text, False
        p_fill = 0.45 * self.intensity
        out = []
        for i, (c, s) in enumerate(clean):
            if i > 0 and not self._core(c)[0] and self._hit(p_fill):
                c = self.rng.choice(C.ASR_FILLERS) + c
            out.append(c)
        if self._hit(0.35 * self.intensity):  # 口吃式重复
            j = self.rng.below(len(out))
            for w in C.STUTTER_WORDS:
                if out[j].startswith(w):
                    out[j] = w + out[j]
                    break
        # 语音输入法常见：整段没有句号，靠空格或逗号随意断开，末尾偶尔带个问号；紧挨数字的分隔符保持原样
        seps = {"comma": ["，", "，", ""], "none": [" ", " ", ""]}.get(self.punct_style or "", [" ", "，", ""])
        s = out[0]
        for i in range(1, len(out)):
            pick = self.rng.choice(seps)
            if self._core(out[i - 1])[-1] or self._core(out[i])[0] or out[i - 1].endswith(tuple(C.NAME_CUES)) \
                    or len(out[i - 1]) in _name_value_sep(out[i - 1] + "，"):
                pick = clean[i - 1][1]
            s += pick + out[i]
        if text.rstrip().endswith(("？", "?")) and self.rng.random() < 0.5 and not self._core(s)[-1]:
            s += "？"
        return s, True

    def _restyle(self, text: str, fn) -> str:
        """逐个标点改写；受保护片段内部与紧挨它的标点不动。fn(ch) 返回替换串。"""
        core = self._core(text)
        fz = cue_frozen(text)
        n = len(text)
        out = []
        for i, ch in enumerate(text):
            adj = core[i] or (i > 0 and core[i - 1]) or (i + 1 < n and core[i + 1]) or fz[i]
            out.append(ch if adj else fn(ch))
        return "".join(out)

    def _strip_edges(self, text: str, chars: str) -> str:
        core = self._core(text)
        a, b = 0, len(text)
        while a < b and text[a] in chars and not (a + 1 < len(text) and core[a + 1]):
            a += 1
        while b > a and text[b - 1] in chars and not (b - 2 >= 0 and core[b - 2]):
            b -= 1
        return text[a:b]

    @staticmethod
    def _collapse(text: str, sep: str) -> str:
        out = []
        for ch in text:
            if ch == sep and out and out[-1] == sep:
                continue
            out.append(ch)
        return "".join(out)

    def _punct(self, text: str) -> Tuple[str, Optional[str]]:
        if self.punct_style:
            q = text.rstrip().endswith(("？", "?"))
            if self.punct_style == "comma":
                new = self._restyle(text, lambda c: "，" if (c in _PUNCT or c == " ") else c)
                new = self._strip_edges(self._collapse(new, "，"), "，")
                if q and new and new[-1] not in "？?" and not self._core(new)[-1]:
                    new += "？"
            else:
                new = self._restyle(text, lambda c: " " if c in _PUNCT else c)
                new = self._strip_edges(self._collapse(new, " "), " ")
            return new, self.punct_style
        if not self._hit(self._p("punct")):
            return text, None
        styles = ["drop_final", "comma_space", "all_comma", "double", "halfwidth", "tilde"]
        if self.intensity >= 0.6:
            styles.append("strip_all")
        style = self.rng.choice(styles)
        if style == "drop_final":
            core = self._core(text)
            b = len(text)
            while b > 0 and text[b - 1] in _SENT_END and not (b - 2 >= 0 and core[b - 2]):
                b -= 1
            new = text[:b]
        elif style == "comma_space":
            new = self._restyle(text, lambda c: " " if c in "，," else c)
        elif style == "all_comma":
            new = self._restyle(text, lambda c: "，" if c in "。！!；;" else c)
            new = self._strip_edges(new, "，") if new.endswith("，") else new
        elif style == "double":
            new = self._restyle(text, lambda c: c + c if c in "？?！!" else c)
            if new == text:
                core = self._core(text)
                for i, ch in enumerate(text):
                    if ch == "。" and not (core[i] or (i > 0 and core[i - 1]) or (i + 1 < len(text) and core[i + 1])):
                        new = text[:i] + "。。。" + text[i + 1:]
                        break
        elif style == "halfwidth":
            tr = {"，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";"}
            new = self._restyle(text, lambda c: tr.get(c, c))
        elif style == "tilde":
            core = self._core(text)
            if text and text[-1] in "。！!":
                new = text if (len(text) >= 2 and core[-2]) else text[:-1] + "~"
            else:
                new = text if (text and core[-1]) else text + "~"
        else:  # strip_all
            new = self._restyle(text, lambda c: " " if c in _PUNCT else c)
            new = self._strip_edges(self._collapse(new, " "), " ")
        return new, style

    def _safe_seps(self, text: str, chars: str) -> List[int]:
        core = self._core(text)
        fz = cue_frozen(text)
        n = len(text)
        return [i for i in range(1, n - 1) if text[i] in chars and not (core[i - 1] or core[i] or core[i + 1] or fz[i])]

    def _emoji(self, text: str) -> Tuple[str, bool]:
        if not self.emojis or not self._hit(self.emoji_rate):
            return text, False
        pos = self._safe_seps(text, "，, ")
        if not pos:
            return text, False
        i = self.rng.choice(pos)
        return text[:i] + self.rng.choice(self.emojis) + text[i + 1:], True

    def _split(self, text: str) -> List[str]:
        if not self._hit(self.split_rate):
            return [text]
        cands = self._safe_seps(text, "，,。！？!?；; ")
        cuts: List[int] = []
        want = 2 if self.rng.random() < 0.35 else 1
        for _ in range(want):
            ok = []
            for p in cands:
                if p in cuts:
                    continue
                bounds = sorted(cuts + [p])
                pieces, prev = [], 0
                for b in bounds:
                    pieces.append(text[prev:b])
                    prev = b + 1
                pieces.append(text[prev:])
                if all(han_count(x) >= 2 for x in pieces):
                    ok.append(p)
            if not ok:
                break
            cuts.append(self.rng.choice(ok))
        if not cuts:
            return [text]
        parts, prev = [], 0
        for b in sorted(cuts):
            keep_q = text[b] in "？?"
            parts.append(text[prev:b] + (text[b] if keep_q else ""))
            prev = b + 1
        parts.append(text[prev:])
        return [x.strip() for x in parts]

    # ------------------------------------------------------------------ public
    def apply(self, text: str, context: Optional[str] = None, intent: Optional[str] = None) -> Result:
        """对一条回复做真人化。context 是对方上一条消息（用于“重复确认”时复述）；intent 是规则引擎的意图（可选，
        配合类意图 COOP_INTENTS 不接跑题句）。"""
        text = str(text or "")
        if self.intensity <= 0 or not text.strip():
            return Result(text, [], [text])
        # 整条消息就是一小段逐字报的数字（跨回合拆开报号，如“幺 三”）：本条后续拼上别的话也照样保护
        self._apply_keep = tuple(_whole_spoken(text))
        self._turn += 1
        applied: List[str] = []
        if "dialect" in self.ops:
            text, ok = self._dialect(text)
            ok and applied.append("dialect")
        if "selfref" in self.ops:
            text, ok = self._selfref(text)
            ok and applied.append("selfref")
        if "repeat" in self.ops:
            text, ok = self._repeat(text, context)
            ok and applied.append("repeat")
        if "digress" in self.ops:
            text, ok = self._digress(text, intent, context)
            ok and applied.append("digress")
        if "extras" in self.ops:
            text, done = self._extras(text)
            applied += done
        if "typo" in self.ops:
            text, n = self._typo(text)
            n and applied.append(f"typo:{n}")
        if "asr" in self.ops:
            text, ok = self._asr(text)
            ok and applied.append("asr")
        if "punct" in self.ops:
            text, style = self._punct(text)
            style and applied.append(f"punct:{style}")
        if "emoji" in self.ops:
            text, ok = self._emoji(text)
            ok and applied.append("emoji")
        parts = self._split(text) if "split" in self.ops else [text]
        if len(parts) > 1:
            applied.append(f"split:{len(parts)}")
        return Result("\n".join(parts), applied, parts)

    def __call__(self, text: str, context: Optional[str] = None, intent: Optional[str] = None) -> str:
        return self.apply(text, context, intent).text


def humanize(text: str, intensity: Optional[float] = None, seed: Optional[int] = None, **kwargs) -> str:
    """一次性调用：``humanize(text, 0.4, seed=1, mode="voice", dialect="西南", context=...)``。"""
    context = kwargs.pop("context", None)
    return Humanizer(intensity, seed, **kwargs).apply(text, context).text
