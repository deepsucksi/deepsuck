"""按通话打码（#140）：同一通电话里已经提取到的姓名、号码，后面再出现时（全名、去姓的名、拆字说法、号码换了写法）
在进模型、送 TTS、记会话前一律打码，再经 persona.unmask 变成“那个名字”/“那个号”。

逐句的提取 + 打码在共享核心（python/deepsuck/redact.py、extractors.json）里做，只认“户名/收款人 + 名字”这类上下文；
这里是每通电话一份的动态集合，只打本通电话里真提取到的值，两者叠加。原值只在本进程内存里，不落盘、不写日志。
逐字解释（「伟大的伟」，#158 的 nameRules.explain）按通话跟进见 explain_segments / CallRedactor._explain（#165）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from deepsuck.redact import _explain_rules, mask

# 姓氏的拆字说法（报户名时常说“弓长张，三丰”）
CHAIZI: Dict[str, Tuple[str, ...]] = {
    "张": ("弓长",), "李": ("木子",), "陈": ("耳东",), "章": ("立早",), "吴": ("口天",),
}
_COMPOUND = ("欧阳", "司马", "诸葛", "上官", "东方", "慕容", "令狐", "皇甫", "夏侯", "尉迟", "公孙", "长孙",
             "宇文", "司徒", "端木", "独孤", "南宫", "西门", "轩辕", "呼延", "澹台", "百里", "东郭", "申屠")
_HAN = re.compile(r"^[\u4e00-\u9fff]{2,6}$")
_DIGIT_MIN = 5  # 少于 5 位的数字串不按通话记（太容易误伤金额、日期）
_SEP = r"[\s\-－—–·.]*"


def split_name(name: str) -> Tuple[str, str]:
    """(姓, 名)。常见复姓整体当姓。"""
    sur = next((c for c in _COMPOUND if name.startswith(c) and len(name) > len(c)), name[:1])
    return sur, name[len(sur):]


def name_patterns(name: str) -> List[str]:
    """一个姓名的各种说法（正则源码）：拆字 + 名、全名、去姓的名（≥2 字）。"""
    if not _HAN.match(name):
        return []
    sur, given = split_name(name)
    g = re.escape(given)
    pats = []
    for cz in CHAIZI.get(sur, ()):
        # “弓长张三丰”“弓长张，三丰”“弓长的张”“弓长张”（只报姓也打，免得模型复述拆字）。
        # 名只有 1 个字时不跨标点连（“耳东陈，立刻转”的“立”不是名），只认紧挨着的“耳东陈立”。
        # 共享核心（#142）已把拆字后的名打成星号时（“弓长张，**”），连星号一起换掉，免得剩下“，**”被念成“那个号”。
        sep = r"[，,、\s]{0,2}" if len(given) >= 2 else ""
        tail = r"(?:" + sep + g + r"|[，,、\s]{0,2}[*＊]{1,4})?" if g else r"(?:[，,、\s]{0,2}[*＊]{1,4})?"
        pats.append(re.escape(cz) + r"(?:的)?" + re.escape(sur) + "?" + tail)
    pats.append(re.escape(name))
    if len(given) >= 2:
        pats.append(g)
    return pats


# #165：逐字解释（#158，共享核心 nameRules.explain）：「伟大的伟」「伟是伟大的伟」「东方的那个东字」。
# 逐句规则只在至少 2 段、带「就是 / X是」、或紧跟拆字报姓 / 已提取姓名时才打；按通话时，本通已记住的姓名本身就是上下文，
# 所以被解释的字是已记住姓名里的字（姓除外，与 张** 只留姓一致）时，单独一段也打。
# 打码值用这个姓名的打码值（张**，经 persona.unmask 读成“那个名字”），整串解释并成一个；紧跟在姓名打码后面的解释
# （含共享核心已打成的纯星号串，如“张**，****”）并入同一个名字，与 llm.js 的 NAME_TAIL_RE 一致，免得剩下“，****”读成“那个号”。
_EX_MARK = "\ue000"  # 解释段占位（私用区字符，替换完即消失）
_NAME_TAIL_SEP = r"[ \u3000…,，、.．·~～\-—]{1,2}"


def explain_segments(s: str) -> List[List[dict]]:
    """文本里所有逐字解释段，按 nameRules.explain 的 sep 分串：[[{start, end, x}, ...], ...]。
    只认段本身（词 + link + X + tail，可带「X是」「X字是」；X 后面是非汉字、结尾、语气词或下一段），不看逐句的打码门槛。"""
    E = _explain_rules()
    if not E or not s:
        return []
    ex = E["ex"]
    wmin, wmax = int(ex.get("wordMin") or 2), int(ex.get("wordMax") or 4)
    leads = ex.get("leads") or []
    han = lambda c: bool(c) and bool(E["han"].match(c))
    cands = []
    for i in range(len(s)):
        m = E["link"].match(s, i)
        if not m:
            continue
        x = m.group(1)
        wstart = -1
        for L in range(1, wmax + 1):
            if i - L < 0:
                break
            c = s[i - L]
            if not han(c) or E["stop"].search(c):
                break
            if L >= wmin and x in s[i - L:i]:
                wstart = i - L
                break
        if wstart < 0:
            continue
        end = m.end()
        t = E["tail"].match(s, end)
        if t:
            end = t.end()
        start = head = wstart
        for ld in leads:
            if wstart < len(ld) or s[wstart - len(ld):wstart] != ld:
                continue
            b = head = wstart - len(ld)
            if b >= 1 and s[b - 1] == x:
                start = head = b - 1
            elif b >= 2 and s[b - 2:b] == x + "字":
                start = head = b - 2
            break
        cands.append({"start": start, "head": head, "wstart": wstart, "end": end, "x": x})
    heads = {c["head"] for c in cands} | {c["wstart"] for c in cands}
    ok = [c for c in cands if c["end"] >= len(s) or not han(s[c["end"]]) or E["particle"].match(s[c["end"]])
          or c["end"] in heads]
    units: List[dict] = []
    for c in sorted(ok, key=lambda c: (c["start"], c["end"])):
        if not units or units[-1]["end"] <= c["start"]:
            units.append(c)
    chains: List[List[dict]] = []
    for u in units:
        if chains and E["sep"].match(s[chains[-1][-1]["end"]:u["head"]]):
            chains[-1].append(u)
        else:
            chains.append([u])
    return chains


def digit_pattern(digits: str) -> str:
    """号码去空格 / 连字符等写法都认：1 3 8-1234-5678、138 1234 5678。前后不能紧挨数字。"""
    return r"(?<![0-9])" + _SEP.join(digits) + r"(?![0-9])"


class CallRedactor:
    """每通电话一份：learn(session) 记下已提取的姓名和号码，apply(text) 把它们的各种说法打码。"""

    def __init__(self):
        self._items: Dict[str, Tuple[str, str]] = {}  # key -> (正则源码, 打码值)
        self._names: Dict[str, Tuple[str, str]] = {}  # 姓名原值 -> (姓, 打码值)，逐字解释用（#165）
        self._tail = None
        self._re = None
        self._sub: List[str] = []

    def __len__(self) -> int:
        return len(self._items)

    def add(self, type_: str, raw) -> None:
        raw = str(raw or "").strip()
        if not raw:
            return
        if type_ == "name":
            pats = name_patterns(raw)
            for p in pats:
                self._items.setdefault("name|" + p, (p, mask("name", raw)))
            if pats:
                self._names.setdefault(raw, (split_name(raw)[0], mask("name", raw)))
        else:
            d = re.sub(r"[^0-9]", "", raw)
            if len(d) >= _DIGIT_MIN and (type_ in ("bank_card", "phone", "qq", "alipay", "id_card") or d == raw):
                self._items.setdefault("num|" + d, (digit_pattern(d), mask(type_, raw)))
        self._re = None

    def learn(self, session) -> int:
        """从会话已提取的情报（原值，仅内存）里补进集合；返回集合大小。"""
        raw_intel = getattr(session, "raw_intel", None)
        for it in (raw_intel() if callable(raw_intel) else []):
            self.add(it.get("type", ""), it.get("raw"))
        return len(self._items)

    def _explain(self, s: str) -> Tuple[str, List[str]]:
        """#165：已记住姓名里的字被逐字解释时，整串解释换成占位符；返回 (文本, 每个占位对应的打码值)。"""
        if not self._names:
            return s, []
        given = "".join(n[len(sur):] for n, (sur, _) in self._names.items())
        out, masks, pos = [], [], 0
        for chain in explain_segments(s):
            owner = next((mk for u in chain for n, (sur, mk) in self._names.items() if u["x"] in n[len(sur):]), None)
            if not owner:
                continue
            for u in chain:
                if u["x"] not in given:
                    continue  # 被解释的是姓（「木子李，就是李子的李」）：不打，与 张** 只留姓一致
                out.append(s[pos:u["start"]])
                out.append(_EX_MARK)
                masks.append(owner)
                pos = u["end"]
        out.append(s[pos:])
        return "".join(out), masks

    def apply(self, text) -> str:
        s = str(text or "")
        if not self._items or not s:
            return s
        if self._re is None:
            # 长的说法先匹配（“弓长张三丰”先于“张三丰”先于“三丰”）
            items = sorted(self._items.values(), key=lambda x: len(x[0]), reverse=True)
            self._sub = [m for _, m in items]
            self._re = re.compile("|".join("(" + p + ")" for p, _ in items))
            name_masks = sorted({mk for _, mk in self._names.values()}, key=len, reverse=True)
            unit = "(?:" + _EX_MARK + "|[*＊]+(?![0-9A-Za-z*＊]))"
            alts = [_EX_MARK + "(?:" + _NAME_TAIL_SEP + _EX_MARK + ")*"]
            if name_masks:
                alts.insert(0, "(" + "|".join(re.escape(mk) for mk in name_masks) + ")(?:" + _NAME_TAIL_SEP + unit + ")+")
            self._tail = re.compile("|".join(alts))
        s, masks = self._explain(s)
        s = self._re.sub(lambda m: self._sub[m.lastindex - 1], s)
        if not self._names:
            return s
        idx = [0]

        def tail(m: re.Match) -> str:
            # 紧跟在姓名打码后面的解释（含共享核心已打成纯星号的）并入这个名字；单独的一串解释换成它所属姓名的打码值
            i, n = idx[0], m.group(0).count(_EX_MARK)
            idx[0] += n
            if m.lastindex:
                return m.group(1)
            return masks[i] if i < len(masks) else ""
        return self._tail.sub(tail, s).replace(_EX_MARK, "")
        it = iter(masks)
        # 紧跟在姓名打码后面的解释（含已打成纯星号的）并入这个名字
        if self._tail is not None:
            s = self._tail.sub(lambda m: m.group(1) + "".join(_EX_MARK * 0 for _ in ()), s) if False else s
        return s
