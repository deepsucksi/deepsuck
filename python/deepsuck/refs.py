"""对方报过哪几种信息（代称），没报过的说法不进人设提示词（#173）；纯星号的逐字解释算名字（#172）。

与 site/assets/js/llm.js 的 maskNames / speakMasked / heardRefs / dropUnheard 逐字一致（共用用例 tests/fixtures/unsaid_refs.json、
tests/fixtures/redact.json 的 charExplain）。配置在 site/assets/core/personas.json 的 unsaidRefs，说明见 unsaidRefsComment。
语音端 voice/persona.py 用 heard_refs / drop_unheard 给提示词去掉对方没报过的那类说法。
"""
from __future__ import annotations

import re
from typing import Iterable

from .core import load
from .extractors import extract_sensitive, masked_lead_not_surname, stars_name, stars_not_name
from .redact import redact_text

_P = load("personas")
_DE = _P["digitEcho"]
UR: dict = _P["unsaidRefs"]
_SPL = load("extractors")["nameRules"]["split"]
_EXP = load("extractors")["nameRules"]["explain"]
NAME = _DE["name"]

_SPLIT_PRE = "(?:(?:" + "|".join(re.escape(x[:-1]) for x in sorted(_SPL["spellings"], key=len, reverse=True)) + ")" + _SPL["link"] + ")"
_SPLIT_BEFORE_NAME = re.compile(_SPLIT_PRE + "(?=〔?" + NAME + ")")
_NAME_MASK = re.compile(_SPLIT_PRE + "?(姓)?(" + "|".join(_DE["compoundSurnames"]) + "|[\u4e00-\u9fff])"
                        "(?:[*＊](?:(?![" + _DE["nameTailStop"] + "])[\u4e00-\u9fff](?![*＊]))?(?![0-9A-Za-z*＊])|[*＊]{2,4}(?![0-9A-Za-z*＊]))")
_NAME_TAIL = re.compile("(〔?" + NAME + "〕?)(?:[ \u3000…,，、.．·~～\\-—]{1,2}[*＊]+(?![0-9A-Za-z*＊]))+")
# #172：纯星号的逐字解释（「弓长张，****」「伟是****」「****，****」）
_HAN = "[\u4e00-\u9fff]"
_NOT_NEAR = "0-9A-Za-z_.:\\/@+#?=&%~\\-*＊"
_STAR_CHAIN = ("(?<![" + _NOT_NEAR + "])(?<![0-9A-Za-z]\\s)[*＊]+(?:" + _EXP["sep"] + "(?:就是)?[*＊]+)*(?![" + _NOT_NEAR + "])(?!\\s[0-9A-Za-z])")
_SPLIT_FULL = "(?:" + "|".join(re.escape(x[:-1]) + _SPL["link"] + re.escape(x[-1]) for x in sorted(_SPL["spellings"], key=len, reverse=True)) + ")"
_SEEN_EXPLAIN = "(?:(?:就是|是)?" + _HAN + "{1,4}" + _EXP["link"] + _HAN + _EXP["tail"] + ")"
_LEAD_CHAR = "(?<![^\\s，,、。！？!?；;…:：])(?![" + _DE["notSurname"] + UR["notLead"] + "])" + _HAN + "字?(?:就是|是)"
_EXPLAIN_NAME = re.compile("(?:" + _SPLIT_FULL + "(?:" + _EXP["sep"] + _SEEN_EXPLAIN + ")?" + _EXP["sep"] + "(?:就是|是)?|" + _LEAD_CHAR + ")" + _STAR_CHAIN)
_BARE_STARS = re.compile(_STAR_CHAIN)
_CLAUSE_SEP = "，,。；;！？!?\n"
_NUMBER_CUE = re.compile("[0-9０-９]|" + UR["numberCue"])
_NAME_DUP = re.compile("(〔?" + NAME + "〕?)(?:" + _EXP["sep"] + "(?:就是|是)?〔?" + NAME + "〕?)+")
_MASKED = re.compile(r"(?:[A-Za-z0-9]+…)?(?:[0-9]{2,6}[ \u00a0](?=[*＊]))*[A-Za-z0-9_.:/@+#?=&%~\-]*[*＊][A-Za-z0-9_.:/@+#?=&%~\-*＊]*(?:[ \u00a0][0-9*＊]+)*"
                     r"|[A-Za-z0-9]{2,}\.\.\.[A-Za-z0-9]{2,}")
REF_ORDER = ("name", "number", "url", "wallet", "email")
# 打码金额（「****块钱」「**元」）：1-4 个星号后接 块/块钱/元，念量词说法，heard_refs 记 number（不当姓名）。
# 说法是台词，待审批；与 llm.js AMOUNT_STARS_RE / AMOUNT_PHRASE 一致
AMOUNT_PHRASE = "那么点"
_AMOUNT_STARS = re.compile("(?<![0-9A-Za-z*＊])[*＊]{1,4}(?:块钱|块|元)")
_REF_KIND = {UR["phrase"][k]: k for k in REF_ORDER}


def mask_names(text: str, bracket: bool = False) -> str:
    """打码姓名换成“那个名字”（#130 / #157 / #158 / #172），与 llm.js maskNames 一致。"""
    w = "〔" + NAME + "〕" if bracket else NAME
    amount = "〔" + UR["phrase"]["number"] + "〕" if bracket else AMOUNT_PHRASE

    def rep(m: re.Match) -> str:
        # #201：星号前的字是不是姓先查共用字表 core/name_stopchars.json，不在表里的再看 notSurname
        return m.group(0) if masked_lead_not_surname(m, m.group(2), _DE["notSurname"]) else w

    s = _AMOUNT_STARS.sub(lambda _m: amount, str(text or ""))  # 打码金额先换，免得「剩*块」被当成姓名
    s = _NAME_MASK.sub(rep, s)
    s = _SPLIT_BEFORE_NAME.sub("", s)
    s = _NAME_TAIL.sub(r"\1", s)
    s = _EXPLAIN_NAME.sub(lambda _m: w, s)
    # #172：没有数字和号码字样时，单独的纯星号串也是逐字解释的名字。#214：按逗号、句号等分段看号码字样
    # （「卡号是***，户名***」后一段是姓名）；#206 第六条探针：号码语境（「转到***」）和「我在***上班」除外，
    # 「转到**名下」「打到**的卡上」一律是姓名
    def bare(m: re.Match) -> str:
        st, pos = m.string, m.start()
        if stars_not_name(st, pos):
            return m.group(0)
        if stars_name(st, pos):
            return w
        a = max(st.rfind(c, 0, pos) for c in _CLAUSE_SEP) + 1
        b = min([i for i in (st.find(c, m.end()) for c in _CLAUSE_SEP) if i >= 0] or [len(st)])
        return m.group(0) if _NUMBER_CUE.search(st[a:b]) else w

    s = _BARE_STARS.sub(bare, s)
    return _NAME_DUP.sub(r"\1", _NAME_TAIL.sub(r"\1", s))


def masked_phrase(tok: str) -> str:
    t = str(tok)
    if re.search(r"[A-Za-z0-9]\.\.\.[A-Za-z0-9]", t) and not re.search("[*＊]", t):
        return UR["phrase"]["wallet"]
    if "@" in t and "://" not in t:
        return UR["phrase"]["email"]
    if re.search(r"://|^www\.|\.[A-Za-z*＊]{2,}(?:[/?#]|$)", t, re.I) and not re.fullmatch(r"[0-9*＊ .\-]+", t):
        return UR["phrase"]["url"]
    return UR["phrase"]["number"]


def speak_masked(text: str, bracket: bool = False) -> str:
    """打码值换成代称（bracket=True 时加〔〕），与 llm.js speakMasked 的代称部分一致。"""
    wrap = (lambda p: "〔" + p + "〕") if bracket else (lambda p: p)
    s = mask_names(text, bracket)

    def rep(m: re.Match) -> str:
        g = m.group(0)
        lead = re.match(r"^\s*", g).group(0)
        return lead + wrap(masked_phrase(g.strip()))

    return re.sub("[*＊]+", "", _MASKED.sub(rep, s))


def heard_refs(texts: Iterable[str]) -> set:
    """对方的话（已脱敏）里出现过的代称种类：{"name", "number", "url", "wallet", "email"} 的子集。"""
    out: set = set()
    for t in texts or ():
        s = mask_names(str(t or ""), True)
        s = redact_text(s, extract_sensitive(s))
        for m in re.findall("〔([^〔〕]+)〕", speak_masked(s, True)):
            if m in _REF_KIND:
                out.add(_REF_KIND[m])
    return out


_QUOTED = re.compile("“[^“”]*”")
_TIDY = (
    (re.compile("\u0001(?:[、或]?\u0001)*"), "\u0001"),
    (re.compile("[、或]\u0001"), ""),
    (re.compile("\u0001[、或]"), ""),
    (re.compile("[，,](?:要提就说|就说|只说|比如|说)\u0001(?=[；;。，,）)]|$)"), ""),
    (re.compile("(?:要提就说|就说|只说|比如|说)\u0001(?:[，,]|(?=[；;。）)]|$))"), ""),
    (re.compile("[（(]像\u0001[）)]"), ""),
    (re.compile("\u0001"), ""),
)


def drop_unheard(text: str, refs) -> str:
    """规则、建议策略里引号括起来的说法，含对方没报过的那类代称（unsaidRefs.kinds）的整段去掉，再理顺旁边的标点。"""
    refs = set(refs or ())
    gone = [w for k, ws in UR["kinds"].items() if k not in refs for w in ws]
    s = _QUOTED.sub(lambda m: "\u0001" if any(w in m.group(0) for w in gone) else m.group(0), str(text or ""))
    for r, b in _TIDY:
        s = r.sub(b, s)
    return s


def forbidden_in(text: str, refs) -> list:
    """对方没报过号码 / 户名时提示词里不该出现的说法（unsaidRefs.forbid），测试用。"""
    refs = set(refs or ())
    need = {"那个号": "number", "那个名字": "name"}
    return [w for w in UR["forbid"] if need.get(w) not in refs and w in str(text or "")]
