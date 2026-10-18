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
_DJ = _O.get("digitJoin")


def _esc_cls(chars: str) -> str:
    return "".join("\\" + c if c in "]\\^-" else {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(c, c) for c in chars)


_SEP = "[" + _esc_cls(_DJ["separators"]) + "]" if _DJ else r"[\s\-]"
_MAX_SEP = _DJ["maxSep"] if _DJ else 2
# 中文数字之间允许夹空格 / 横杠 / 换行 / 标点（“六二二二，零二零二”“六二二二... 零二零二”），每处至多 maxSep 个
RE_NUM_RUN = re.compile(
    "[0-9" + _NUM_CHARS + "](?:" + _SEP + "{0,%d}[0-9" % _MAX_SEP + _NUM_CHARS + "]){" + str(_O["numeralRunMin"] - 1) + ",}"
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
_KG = _O.get("keywordGap") or {}
# 表情：Python 按码点；JS 版用 UTF-16 代理对 [\uD83C-\uD83E][\uDC00-\uDFFF]（同一范围 U+1F000–U+1FBFF）
_EMOJI = "[\U0001F000-\U0001FBFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D]"
_GAP = ("(?:[" + _esc_cls(_KG.get("chars", "")) + "]" + ("|" + _EMOJI if _KG.get("emoji") else "") + ")") if _KG else None
RE_GAP_KW = [
    (re.compile(("(?:" + _GAP + "){0,%d}" % _KG.get("max", 3)).join(re.escape(ch) for ch in w)), w)
    for w in _KG.get("keywords", [])
] if _KG else []
RE_EMOJI_IN_DIGITS = re.compile("(?<=[0-9" + _NUM_CHARS + "])(?:" + _EMOJI + "){1,%d}(?=[0-9" % _KG.get("max", 3) + _NUM_CHARS + "])") \
    if _KG.get("emoji") else None
_GAP_NOT_AFTER: dict = _KG.get("notAfter") or {}
_GAP_NOT_BEFORE: dict = _KG.get("notBefore") or {}


def _gap_kw(to: str):
    def rep(m, mm, full):
        if m == to:
            return None
        a, b = mm.start(), mm.end()
        if a > 0 and full[a - 1] in _GAP_NOT_AFTER.get(to, ""):
            return None
        if b < len(full) and full[b] in _GAP_NOT_BEFORE.get(to, ""):
            return None
        return to
    return rep


RE_SPACED_DIGITS = re.compile(r"(?<![0-9])[0-9](?:[ \u00a0\-·.,_/]{1,2}[0-9]){6,}(?![0-9])")
RE_FULLWIDTH = re.compile("[\uFF01-\uFF5E\u3000]+")
_DIGIT_CHARS: dict = (_O.get("digitChars") or {}).get("map") or {}
RE_DIGIT_CHARS = re.compile("[" + "".join(_DIGIT_CHARS) + "]+") if _DIGIT_CHARS else None
RE_FILLER = re.compile("[" + re.escape(_O["fillerChars"]) + "]+") if _O.get("fillerChars") else None
RE_DIGIT_GROUPS = (
    re.compile("(?:" + "|".join(re.escape(w) for w in _O["digitGroupKeywords"]) + r")[^0-9\n]{0,4}[0-9]{2,5}(?:[ \u00a0][0-9]{2,5}){1,4}(?![0-9])")
    if _O.get("digitGroupKeywords") else None
)

_VARIANT: dict = (_O.get("variantChars") or {}).get("map") or {}
RE_VARIANT = re.compile("[" + "".join(_VARIANT) + "]") if _VARIANT else None
_TYPO: dict = (_O.get("typoKeywords") or {}).get("map") or {}
_TYPO_KEYS = sorted(_TYPO, key=lambda k: (-len(k), k))
RE_TYPO = re.compile("|".join(re.escape(k) for k in _TYPO_KEYS)) if _TYPO_KEYS else None
RE_DIGIT_JOIN = (
    re.compile("(?<![0-9A-Za-z])[0-9]{1,%d}(?:%s{1,%d}[0-9]{1,%d})+(?![0-9A-Za-z])"
               % (_DJ["maxGroup"], _SEP, _DJ["maxSep"], _DJ["maxGroup"])) if _DJ else None
)
RE_UNIT_AFTER = re.compile(_DJ["unitAfter"]) if _DJ else None
RE_STD_FORMAT = re.compile(
    r"^(?:[0-9]{4}(?:[ -][0-9]{4}){3}(?:[ -][0-9]{1,3})?|(?:86[\s-]?)?1[3-9][0-9][\s.-]?[0-9]{4}[\s.-]?[0-9]{4}"
    r"|0[0-9]{2,3}-[0-9]{7,8}|(?:400|800)[\s-]?[0-9]{3}[\s-]?[0-9]{4})$")
_WJ = _O.get("walletJoin")
_B58 = "1-9A-HJ-NP-Za-km-z"
# 中间各段至少 minChunk 个字符，最后一段至少 lastChunkMin 个（断续报地址常剩一两个字符单独念）
_LAST = (_WJ.get("lastChunkMin") or _WJ["minChunk"]) if _WJ else 0
RE_ETH_JOIN = (re.compile("(?<![0-9A-Za-z])0x[0-9a-fA-F]{1,40}(?:%s{1,%d}[0-9a-fA-F]{%d,40})*%s{1,%d}[0-9a-fA-F]{%d,40}(?![0-9A-Za-z])"
                          % (_SEP, _MAX_SEP, _WJ["minChunk"], _SEP, _MAX_SEP, _LAST)) if _WJ else None)
RE_TRON_JOIN = (re.compile("(?<![0-9A-Za-z])T[%s]{%d,33}(?:%s{1,%d}[%s]{%d,33})*%s{1,%d}[%s]{%d,33}(?![0-9A-Za-z])"
                           % (_B58, _WJ["minChunk"] - 1, _SEP, _MAX_SEP, _B58, _WJ["minChunk"], _SEP, _MAX_SEP, _B58, _LAST))
                if _WJ else None)
_RE_HEX = re.compile("[0-9a-fA-F]+")
_RE_B58 = re.compile("[" + _B58 + "]+")


def luhn(d: str) -> bool:
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return len(d) > 0 and total % 10 == 0


def _bin_hit(d: str) -> bool:
    from .cardbin import lookup  # 延迟导入，避免循环
    return lookup(d) is not None


RE_LANDLINE_DIGITS = re.compile(r"0(?:10|2[0-9])[2-8][0-9]{7}|0[3-9][0-9]{2}[2-8][0-9]{6,7}")
RE_HOTLINE_DIGITS = re.compile(r"(?:400|800)[0-9]{7}")


def plausible_number(d: str) -> Optional[str]:
    """拼起来是否像一个完整号码：11 位手机号（可带 86）、座机（010 / 02x + 8 位，0[3-9]xx + 7/8 位，用户号 2–8 开头）、
    400 / 800 热线，或 16–19 位银行卡（Luhn / 62 银联 / BIN 命中）。"""
    if RE_LANDLINE_DIGITS.fullmatch(d):
        return "landline"
    if RE_HOTLINE_DIGITS.fullmatch(d):
        return "hotline"
    if len(d) == 11 and re.match(r"1[3-9]", d):
        return "phone"
    if len(d) == 13 and re.match(r"861[3-9]", d):
        return "phone"
    if 16 <= len(d) <= 19 and not re.fullmatch(r"([0-9])\1+", d) and (luhn(d) or d.startswith("62") or _bin_hit(d)):
        return "bank_card"
    return None


def _complete_alone(d: str) -> bool:
    return (len(d) == 11 and bool(re.match(r"1[3-9]", d))) or 16 <= len(d) <= 19


def _join_groups(m: str, tail_unit: bool):
    G = [(g.start(), g.end(), g.group(0)) for g in re.finditer(r"[0-9]+", m)]
    drop, i = set(), 0
    while i < len(G):
        best, tot = -1, G[i][2]
        if not _complete_alone(G[i][2]):
            for j in range(i + 1, len(G)):
                if _complete_alone(G[j][2]):
                    break
                if j == len(G) - 1 and tail_unit:
                    break
                tot += G[j][2]
                if len(tot) > 19:
                    break
                kind = plausible_number(tot)
                # 座机 / 热线不由两位一组的数字拼成（“开奖号码是03、15、22、23、35、47”）
                if kind in ("landline", "hotline") and sum(1 for g in G[i:j + 1] if len(g[2]) == 2) >= 2:
                    kind = None
                if kind and not RE_STD_FORMAT.match(m[G[i][0]:G[j][1]]):
                    best = j
        if best > i:
            drop.update(k for k in range(G[i][1], G[best][0]) if not ("0" <= m[k] <= "9"))
            i = best + 1
        else:
            i += 1
    return drop or None


def _join_chunks(m: str, pat: re.Pattern, want: int, offset: int = 0):
    C = [(g.start(), g.end()) for g in pat.finditer(m)]
    tot = 0
    for j, (s0, e0) in enumerate(C):
        tot += e0 - s0
        if tot == want:
            if j == 0:
                return None
            return {k + offset for k in range(C[0][1], C[j][0]) if not m[k].isascii() or not m[k].isalnum()}
        if tot > want:
            return None
    return None


def _dropper(m: str, drop):
    if not drop:
        return None
    return [(c, i) for i, c in enumerate(m) if i not in drop]


Replacement = Union[str, Sequence[Tuple[str, int]], None]


@dataclass
class _State:
    s: str
    st: List[int]
    en: List[int]


def _init(text: str) -> _State:
    return _State(text, list(range(len(text))), list(range(1, len(text) + 1)))


def _apply(state: _State, pattern: re.Pattern, replacer: Callable[..., Replacement], with_match: bool = False) -> _State:
    s = state.s
    out: List[str] = []
    st: List[int] = []
    en: List[int] = []
    last = 0
    for m in pattern.finditer(s):
        if m.group(0) == "":
            continue
        a, b = m.start(), m.end()
        rep = replacer(m.group(0), m, s) if with_match else replacer(m.group(0))
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


def _quantity_cut(m: str) -> Optional[int]:
    """#2：全中文数字串后面紧跟量词 / 时间单位（“一三九零零一一二二三三两小时”）时，末尾 1–2 个中文数字是数量，
    返回号码部分的结束下标（末尾分隔符不算号码）；不需要截断时返回 None。
    规则：末字是“两”一律截掉（“两”在单位前几乎总是数量）；否则只有整串拼不成号码、截掉末尾 1–2 个中文数字后能拼成时才截。"""
    pos = [i for i, c in enumerate(m) if c in _NUMERALS and not ("0" <= c <= "9")]
    if not pos or pos[-1] != len(m) - 1:
        return None

    def digits(t: str) -> str:
        return "".join(_NUMERALS.get(c, c) for c in t if c in _NUMERALS or "0" <= c <= "9")

    def end_of(cut: int) -> int:
        while cut > 0 and not (m[cut - 1] in _NUMERALS or "0" <= m[cut - 1] <= "9"):
            cut -= 1
        return cut
    if m[-1] == "两":
        return end_of(len(m) - 1)
    if plausible_number(digits(m)):
        return None
    for t in (1, 2):
        if len(pos) <= t:
            break
        cut = end_of(pos[-t])
        if plausible_number(digits(m[:cut])):
            return cut
    return None


def normalize(text: Optional[str]) -> Normalized:
    raw = "" if text is None else str(text)
    state = _init(raw)
    state = _apply(state, RE_FULLWIDTH, _fullwidth)
    # 异体字 / 繁体（帐→账）与关键词错别字（personas 混淆表：转帐→转账、银航→银行），逐字等长替换
    if RE_VARIANT:
        state = _apply(state, RE_VARIANT, lambda m: [(_VARIANT[m], 0)])
    if RE_TYPO:
        state = _apply(state, RE_TYPO, lambda m: [(c, i) for i, c in enumerate(_TYPO[m])])
    # 圈码数字 ①③⑨ → 139（逐字符）；装饰符号 ❤★ 等直接删除（“薇❤信”→“薇信”）
    if RE_DIGIT_CHARS:
        state = _apply(state, RE_DIGIT_CHARS, lambda m: [(_DIGIT_CHARS[c], i) for i, c in enumerate(m)])
    if RE_FILLER:
        state = _apply(state, RE_FILLER, lambda m: [])
    for pat, to in RE_SPACED_KW:
        state = _apply(state, pat, lambda m, to=to: None if m == to else to)
    if RE_EMOJI_IN_DIGITS:  # “二幺幺四🌹🌹幺三六二”：数字之间的表情当作一个空格
        state = _apply(state, RE_EMOJI_IN_DIGITS, lambda m: " ")
    for pat, to in RE_GAP_KW:  # “微，信”“微🙏信”：平台名 / 字段名中间夹标点或表情
        state = _apply(state, pat, _gap_kw(to), with_match=True)
    for pat in RE_SPACED_LETTERS:
        def rep(m):
            t = re.sub(r"[\s·]+", "", m)
            return None if t == m else t
        state = _apply(state, pat, rep)
    state = _apply(state, RE_DOT, lambda m: ".")

    def num(m, mm, full):
        if not RE_HAS_NUMERAL.search(m):
            return None
        # “13900112233两小时”：紧跟在阿拉伯数字后、后面接单位的中文数字是量词用法，不并入号码
        k = len(m)
        while k > 0 and m[k - 1] in _NUMERALS and not ("0" <= m[k - 1] <= "9"):
            k -= 1
        unit = bool(RE_UNIT_AFTER and RE_UNIT_AFTER.match(full[mm.end():]))
        if 0 < k < len(m) and unit and "0" <= m[k - 1] <= "9":
            if not RE_HAS_NUMERAL.search(m[:k]):
                return None
            return [(_NUMERALS.get(c, c) if i < k else c, i) for i, c in enumerate(m)]
        if unit:
            cut = _quantity_cut(m)
            if cut is not None:
                if not RE_HAS_NUMERAL.search(m[:cut]):
                    return None
                return [(_NUMERALS.get(c, c) if i < cut else c, i) for i, c in enumerate(m)]
        return [(_NUMERALS.get(c, c), i) for i, c in enumerate(m)]
    state = _apply(state, RE_NUM_RUN, num, with_match=True)
    state = _apply(state, RE_SPACED_DIGITS, lambda m: [(c, i) for i, c in enumerate(m) if "0" <= c <= "9"])

    def groups(m):  # “企鹅 699 700 370” → “企鹅 699700370”：只删除两侧都是数字的空格
        r = [(c, i) for i, c in enumerate(m)
             if not (c in " \u00a0" and 0 < i < len(m) - 1 and "0" <= m[i - 1] <= "9" and "0" <= m[i + 1] <= "9")]
        return None if len(r) == len(m) else r
    if RE_DIGIT_GROUPS:
        state = _apply(state, RE_DIGIT_GROUPS, groups)
    # 数字间夹空格 / 横杠 / 换行 / 标点：只有拼起来是合法手机号 / 银行卡时才拼接
    if RE_DIGIT_JOIN:
        state = _apply(state, RE_DIGIT_JOIN, lambda m, mm, full: _dropper(
            m, _join_groups(m, bool(RE_UNIT_AFTER.match(full[mm.end():])))), with_match=True)
    if RE_ETH_JOIN:
        state = _apply(state, RE_ETH_JOIN, lambda m: _dropper(m, _join_chunks(m[2:], _RE_HEX, 40, 2)))
    if RE_TRON_JOIN:
        state = _apply(state, RE_TRON_JOIN, lambda m: _dropper(m, _join_chunks(m, _RE_B58, 34)))
    return Normalized(raw, state)
