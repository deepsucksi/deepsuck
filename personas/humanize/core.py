"""可程序化的“真人化”后处理：让机器人人设的文字回复更像真人随手打的字或语音转文字。

用法::

    from personas.humanize import humanize, Humanizer
    humanize("好的，我已经知道了。", intensity=0.5, seed=7)
    Humanizer(profile="retiree", seed=1).apply("你说的账户是哪个银行的？", context="转到这个账户")

设计约束：

- 只做“看得懂”的扰动：同音/形近错别字、标点缺失或乱用、语音转文字式断句与口头语、
  重复确认、跑题、方言词；不改变数字、打码值（*）、占位符 ``{...}`` 和英文/网址片段；
- 同一个 seed 得到同样的结果（只用 ``random.Random`` 实例，不碰全局随机数）；
- intensity=0 时原样返回；intensity 越大，扰动越多（上限 1.0）。
- 不负责安全过滤：输出仍然要经过 voice/persona.py 的 guard_output 之类的守卫。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import confusion as C
from .profiles import PROFILES

OPS: Tuple[str, ...] = ("dialect", "repeat", "digress", "typo", "punct", "asr")
MODES = ("chat", "voice")

# intensity=1 时每种操作的基准概率 / 比例
BASE_RATES: Dict[str, float] = {
    "typo": 0.35,     # 每个候选位置被替换的概率（另有每条上限）
    "punct": 0.9,     # 整条文本应用一种标点风格的概率
    "asr": 1.0,       # 语音模式下改写断句的概率
    "repeat": 0.4,    # 追加/前置一句重复确认的概率
    "digress": 0.25,  # 插入一句跑题的概率
    "dialect": 1.0,   # 设置了方言时，每个匹配处被替换的概率 = 0.5 + 0.5 * 该值 * intensity
}

_PROTECT = re.compile(
    r"\{[^{}]*\}"                      # 占位符 {银行卡}
    r"|[0-9０-９*＊]+"                  # 数字与打码值
    r"|[A-Za-z][A-Za-z0-9_.:/@\-]*"     # 英文、网址、APP 名
)
_SENT_END = "。！？!?"
_PUNCT = "，,。！？!?；;：:、…~～"
_CLAUSE_SPLIT = re.compile(r"[，,。！？!?；;…~～]+")
_ECHO_SPLIT = re.compile(r"[，,。！？!?；;：:…~～\s]+")


@dataclass
class Result:
    text: str
    ops: List[str] = field(default_factory=list)  # 实际生效的操作，便于调试与评测


def _protected_mask(text: str, keep: Sequence[str] = ()) -> List[bool]:
    mask = [False] * len(text)
    for m in _PROTECT.finditer(text):
        for i in range(m.start(), m.end()):
            mask[i] = True
    for w in keep:
        if not w:
            continue
        for m in re.finditer(re.escape(w), text):
            for i in range(m.start(), m.end()):
                mask[i] = True
    return mask


def _free(mask: List[bool], start: int, end: int) -> bool:
    return not any(mask[start:end])


class Humanizer:
    """带随机种子与强度参数的真人化处理器。

    参数：
        intensity: 0–1，总体强度；
        seed: 随机种子；同一个实例连续调用会推进同一个随机序列；
        mode: "chat"（打字：错别字含形近字，标点乱用）或 "voice"（语音输入：只有同音错字，按口语断句、加口头语）；
        dialect: None 或 confusion.DIALECT 的键（北方、东北、西南、粤式普通话）；
        ops: 启用的操作集合，默认按 mode 决定（chat 不做 asr，voice 不做 punct）；
        weights: 每种操作的强度倍数，例如 {"typo": 0.5}；
        digressions: 跑题句子池，默认用 confusion.DIGRESSIONS；
        keep: 额外保护、不做任何改动的词（例如人设名字）；
        profile: personas/humanize/profiles.py 中的预设名，显式参数优先于预设；
        max_typos: 每条最多几处错别字，默认 1 + round(3 * intensity)；
        handwriting: 是否出现形近字（手写输入识别错、看错）；默认打字模式开、语音模式关，预设可单独打开
            （例如老人语音和手写输入混用：retiree 预设在 voice 模式下也有形近字）。
    """

    def __init__(self, intensity: Optional[float] = None, seed: Optional[int] = None, *, mode: Optional[str] = None,
                 dialect: Optional[str] = None, ops: Optional[Iterable[str]] = None,
                 weights: Optional[Dict[str, float]] = None, digressions: Optional[Sequence[str]] = None,
                 keep: Sequence[str] = (), profile: Optional[str] = None, max_typos: Optional[int] = None,
                 rng: Optional[random.Random] = None, handwriting: Optional[bool] = None):
        prof = dict(PROFILES[profile]) if profile else {}
        if profile and profile not in PROFILES:
            raise KeyError(profile)
        self.intensity = float(prof.get("intensity", 0.3) if intensity is None else intensity)
        if not 0.0 <= self.intensity <= 1.0:
            raise ValueError("intensity must be within [0, 1]")
        self.mode = mode or prof.get("mode", "chat")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.dialect = dialect if dialect is not None else prof.get("dialect")
        if self.dialect is not None and self.dialect not in C.DIALECT:
            raise ValueError(f"unknown dialect: {self.dialect}")
        if ops is None:
            ops = prof.get("ops")
        if ops is None:
            ops = [o for o in OPS if o != ("asr" if self.mode == "chat" else "punct")]
        self.ops = set(ops)
        unknown = self.ops - set(OPS)
        if unknown:
            raise ValueError(f"unknown ops: {sorted(unknown)}")
        self.weights = {**prof.get("weights", {}), **(weights or {})}
        self.digressions = list(digressions or prof.get("digressions") or C.DIGRESSIONS)
        self.keep = tuple(keep) + tuple(prof.get("keep", ()))
        self.max_typos = max_typos if max_typos is not None else 1 + round(3 * self.intensity)
        if handwriting is None:
            handwriting = prof.get("handwriting", self.mode == "chat")
        self.handwriting = bool(handwriting)
        self.rng = rng or random.Random(seed)
        self._used_digressions: List[str] = []

    # ------------------------------------------------------------------ helpers
    def _p(self, op: str, scale: float = 1.0) -> float:
        return max(0.0, min(1.0, BASE_RATES[op] * self.weights.get(op, 1.0) * self.intensity * scale))

    def _hit(self, p: float) -> bool:
        return p > 0 and self.rng.random() < p

    # ------------------------------------------------------------------ ops
    def _dialect(self, text: str) -> Tuple[str, bool]:
        if not self.dialect:
            return text, False
        p = min(1.0, 0.5 + 0.5 * self._p("dialect")) if self.intensity > 0 else 0.0
        changed = False
        for src, alts in sorted(C.DIALECT[self.dialect], key=lambda x: -len(x[0])):
            out, i = [], 0
            mask = _protected_mask(text, self.keep)
            for m in re.finditer(re.escape(src), text):
                if m.start() < i or not _free(mask, m.start(), m.end()) or not self._hit(p):
                    continue
                out.append(text[i:m.start()])
                out.append(self.rng.choice(alts))
                i = m.end()
                changed = True
            out.append(text[i:])
            text = "".join(out)
        return text, changed

    def _typo(self, text: str) -> Tuple[str, int]:
        p = self._p("typo")
        if p <= 0 or self.max_typos <= 0:
            return text, 0
        mask = _protected_mask(text, self.keep)
        sites = []  # (start, end, alternatives)
        taken = [False] * len(text)
        for word, alts in sorted(C.HOMOPHONE_WORDS.items(), key=lambda x: -len(x[0])):
            for m in re.finditer(re.escape(word), text):
                s, e = m.start(), m.end()
                if _free(mask, s, e) and not any(taken[s:e]):
                    sites.append((s, e, alts))
                    for k in range(s, e):
                        taken[k] = True
        for i, ch in enumerate(text):
            if mask[i] or taken[i]:
                continue
            alts = list(C.HOMOPHONE_CHARS.get(ch, ()))
            if self.handwriting:
                alts += C.SHAPE_CHARS.get(ch, [])
            if alts:
                sites.append((i, i + 1, alts))
        self.rng.shuffle(sites)
        chosen = []
        for s, e, alts in sites:
            if len(chosen) >= self.max_typos:
                break
            if self._hit(p):
                chosen.append((s, e, self.rng.choice(alts)))
        for s, e, rep in sorted(chosen, reverse=True):
            text = text[:s] + rep + text[e:]
        return text, len(chosen)

    def _echo(self, context: str) -> Optional[str]:
        """从对方的话里挑一个可以复述的关键短语。

        优先 confusion.ECHO_KEYWORDS 里的名词性关键词（“安全账户”“验证码”）；没有时才用完整的短分句（2–8 字），
        且分句不能含数字 / 打码、人称或称呼、祈使词——原样复述骗子的半句话（“要不我帮您转接高级专员”）像角色互换。
        """
        ctx = context or ""
        keys, taken = [], [False] * len(ctx)
        for k in sorted(C.ECHO_KEYWORDS, key=len, reverse=True):
            for m in re.finditer(re.escape(k), ctx):
                if not any(taken[m.start():m.end()]):
                    keys.append((m.start(), k))
                    for i in range(m.start(), m.end()):
                        taken[i] = True
        keys = list(dict.fromkeys(k for _, k in sorted(keys)))
        if keys:
            return self.rng.choice(keys)
        parts = [x for x in _ECHO_SPLIT.split(ctx)
                 if 2 <= len(x) <= 8 and not re.search(r"[0-9０-９*＊A-Za-z]", x)
                 and not any(w in x for w in C.ECHO_AVOID)]
        if not parts:
            return None
        return self.rng.choice(parts)

    def _repeat(self, text: str, context: Optional[str]) -> Tuple[str, bool]:
        if not self._hit(self._p("repeat")):
            return text, False
        echo = self._echo(context) if context else None
        if echo:
            line = self.rng.choice(C.CONFIRM_TEMPLATES).format(echo=echo)
            joint = "" if line[-1] in _PUNCT else "，"  # 避免“清零？，先付……”这样的双标点
            return (line + joint + text) if self.rng.random() < 0.6 else (text.rstrip(_PUNCT) + "。" + line), True
        line = self.rng.choice(C.CONFIRM_GENERIC)
        return text.rstrip(_PUNCT) + "，" + line, True

    def _digress(self, text: str) -> Tuple[str, bool]:
        if not self.digressions or not self._hit(self._p("digress")):
            return text, False
        # 同一个实例（一整段对话）里跑题句不重复，用完一轮才重来：大模型骗子会把重复的“我孙子刚放学回来了”当成消遣
        left = [x for x in self.digressions if x not in self._used_digressions] or self.digressions
        if len(left) == len(self.digressions):
            self._used_digressions = []
        d = self.rng.choice(left)
        self._used_digressions.append(d)
        if self.rng.random() < 0.5:
            return d + "……" + text, True
        return text.rstrip(_PUNCT) + "。" + d, True

    def _punct(self, text: str) -> Tuple[str, Optional[str]]:
        if not self._hit(self._p("punct")):
            return text, None
        styles = ["drop_final", "comma_space", "all_comma", "double", "halfwidth", "tilde"]
        if self.intensity >= 0.6:
            styles.append("strip_all")
        style = self.rng.choice(styles)
        if style == "drop_final":
            new = text.rstrip(_SENT_END + "。")
        elif style == "comma_space":
            new = re.sub(r"[，,]", " ", text)
        elif style == "all_comma":
            new = re.sub(r"[。！!；;]", "，", text).rstrip("，")
        elif style == "double":
            new = re.sub(r"([？?！!])", r"\1\1", text)
            new = re.sub(r"。", "。。。", new, count=1) if new == text else new
        elif style == "halfwidth":
            new = text.translate(str.maketrans("，。！？：；", ",.!?:;"))
        elif style == "tilde":
            new = re.sub(r"[。！!]$", "~", text) if re.search(r"[。！!]$", text) else text + "~"
        else:  # strip_all
            new = re.sub(r"[，,。！？!?；;：:、…~～]+", " ", text).strip()
        return new, style

    def _asr(self, text: str) -> Tuple[str, bool]:
        if not self._hit(self._p("asr")):
            return text, False
        clauses = [c for c in _CLAUSE_SPLIT.split(text) if c.strip()]
        if not clauses:
            return text, False
        p_fill = 0.45 * self.intensity
        out = []
        for i, c in enumerate(clauses):
            c = c.strip()
            if i > 0 and self._hit(p_fill):
                c = self.rng.choice(C.ASR_FILLERS) + c
            out.append(c)
        if self._hit(0.35 * self.intensity):  # 口吃式重复
            j = self.rng.randrange(len(out))
            for w in C.STUTTER_WORDS:
                if out[j].startswith(w):
                    out[j] = w + out[j]
                    break
        # 语音输入法常见：整段没有句号，靠空格或逗号随意断开，末尾偶尔带个问号
        seps = [" ", "，", ""]
        s = out[0]
        for c in out[1:]:
            s += self.rng.choice(seps) + c
        if text.rstrip().endswith(("？", "?")) and self.rng.random() < 0.5:
            s += "？"
        return s, True

    # ------------------------------------------------------------------ public
    def apply(self, text: str, context: Optional[str] = None) -> Result:
        """对一条回复做真人化。context 是对方上一条消息（用于“重复确认”时复述）。"""
        text = str(text or "")
        if self.intensity <= 0 or not text.strip():
            return Result(text, [])
        applied: List[str] = []
        if "dialect" in self.ops:
            text, ok = self._dialect(text)
            ok and applied.append("dialect")
        if "repeat" in self.ops:
            text, ok = self._repeat(text, context)
            ok and applied.append("repeat")
        if "digress" in self.ops:
            text, ok = self._digress(text)
            ok and applied.append("digress")
        if "typo" in self.ops:
            text, n = self._typo(text)
            n and applied.append(f"typo:{n}")
        if "asr" in self.ops:
            text, ok = self._asr(text)
            ok and applied.append("asr")
        if "punct" in self.ops:
            text, style = self._punct(text)
            style and applied.append(f"punct:{style}")
        return Result(text, applied)

    def __call__(self, text: str, context: Optional[str] = None) -> str:
        return self.apply(text, context).text


def humanize(text: str, intensity: Optional[float] = None, seed: Optional[int] = None, **kwargs) -> str:
    """一次性调用：``humanize(text, 0.4, seed=1, mode="voice", dialect="西南", context=...)``。"""
    context = kwargs.pop("context", None)
    return Humanizer(intensity, seed, **kwargs).apply(text, context).text
