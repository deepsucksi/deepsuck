"""中文"去武装"写法规范化（与 site/assets/js/normalize.js 等价）。

骗子常写 "微 信"、"V信"、"扣扣"、"xxx点com"、"幺三九…"、"１３９"、"1 3 9 0 …" 躲避过滤。
先规范化再提取；同时维护 规范化文本 → 原文 的位置映射，脱敏时替换原文对应片段。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple, Union

from .core import load

_O = load("extractors")["obfuscation"]
_NUMERALS: dict = _O["numerals"]
_NUM_CHARS = "".join(_NUMERALS.keys())

RE_NUM_RUN = re.compile(
    "[0-9" + _NUM_CHARS + "](?:[\\s\\-]{0,2}[0-9" + _NUM_CHARS + "]){" + str(_O["numeralRunMin"] - 1) + ",}"
)
RE_HAS_NUMERAL = re.compile("[" + _NUM_CHARS + "]")
_latin = [w for w in _O["dotWords"] if re.fullmatch(r"[A-Za-z]+", w)]
_cjk = [w for w in _O["dotWords"] if w not in _latin]
RE_DOT = re.compile(
    r"(?<=[A-Za-z0-9])(?:\s*(?:" + "|".join(re.escape(w) for w in _cjk) + r")\s*|\s+(?:"
    + "|".join(re.escape(w) for w in _latin) + r")\s+)(?=[A-Za-z]{2,})"
)
RE_SPACED_LETTERS = [
    re.compile(r"(?<![A-Za-z])" + r"[\s·]+".join(re.escape(ch) for ch in w) + r"(?![A-Za-z])", re.IGNORECASE)
    for w in _O["spacedLetters"]
]
RE_SPACED_KW = [
    (re.compile(r"[\s·_\-*]+".join(re.escape(ch) for ch in w)), w) for w in _O["spaceInsideKeywords"]
]
RE_SPACED_DIGITS = re.compile(r"(?<![0-9])[0-9](?:[ \u00a0\-·.,_/]{1,2}[0-9]){6,}(?![0-9])")
RE_FULLWIDTH = re.compile("[\uFF01-\uFF5E\u3000]+")

Replacement = Union[str, Sequence[Tuple[str, int]], None]


@dataclass
class _State:
    s: str
    st: List[int]
    en: List[int]


def _init(text: str) -> _State:
    return _State(text, list(range(len(text))), list(range(1, len(text) + 1)))


def _apply(state: _State, pattern: re.Pattern, replacer: Callable[[str], Replacement]) -> _State:
    s = state.s
    out: List[str] = []
    st: List[int] = []
    en: List[int] = []
    last = 0
    for m in pattern.finditer(s):
        if m.group(0) == "":
            continue
        a, b = m.start(), m.end()
        rep = replacer(m.group(0))
        if rep is None:
            continue
        for i in range(last, a):
            out.append(s[i]); st.append(state.st[i]); en.append(state.en[i])
        if isinstance(rep, str):
            for ch in rep:
                out.append(ch); st.append(state.st[a]); en.append(state.en[b - 1])
        else:
            for ch, k in rep:
                out.append(ch); st.append(state.st[a + k]); en.append(state.en[a + k])
        last = b
    if last == 0:
        return state
    for k in range(last, len(s)):
        out.append(s[k]); st.append(state.st[k]); en.append(state.en[k])
    return _State("".join(out), st, en)


def _fullwidth(m: str):
    return [(" " if c == "\u3000" else chr(ord(c) - 0xFEE0), i) for i, c in enumerate(m)]


class Normalized:
    """normalize() 的结果：text 规范化文本；span(a, b) 把规范化区间映射回原文区间。"""

    def __init__(self, raw: str, state: _State):
        self.raw = raw
        self.text = state.s
        self.changed = state.s != raw
        self._st = state.st
        self._en = state.en

    def span(self, a: int, b: int) -> Tuple[int, int]:
        if not self.changed:
            return a, b
        if b <= a:
            v = self._st[a] if a < len(self._st) else 0
            return v, v
        return self._st[a], self._en[b - 1]

    def __repr__(self) -> str:  # pragma: no cover
        return f"Normalized({self.text!r}, changed={self.changed})"


def normalize(text: Optional[str]) -> Normalized:
    raw = "" if text is None else str(text)
    state = _init(raw)
    state = _apply(state, RE_FULLWIDTH, _fullwidth)
    for pat, to in RE_SPACED_KW:
        state = _apply(state, pat, lambda m, to=to: None if m == to else to)
    for pat in RE_SPACED_LETTERS:
        def rep(m):
            t = re.sub(r"[\s·]+", "", m)
            return None if t == m else t
        state = _apply(state, pat, rep)
    state = _apply(state, RE_DOT, lambda m: ".")

    def num(m):
        if not RE_HAS_NUMERAL.search(m):
            return None
        return [(_NUMERALS.get(c, c), i) for i, c in enumerate(m)]
    state = _apply(state, RE_NUM_RUN, num)
    state = _apply(state, RE_SPACED_DIGITS, lambda m: [(c, i) for i, c in enumerate(m) if "0" <= c <= "9"])
    return Normalized(raw, state)
