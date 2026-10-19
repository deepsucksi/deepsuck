"""按通话打码（#140）：同一通电话里已经提取到的姓名、号码，后面再出现时（全名、去姓的名、拆字说法、号码换了写法）
在进模型、送 TTS、记会话前一律打码，再经 persona.unmask 变成“那个名字”/“那个号”。

逐句的提取 + 打码在共享核心（python/deepsuck/redact.py、extractors.json）里做，只认“户名/收款人 + 名字”这类上下文；
这里是每通电话一份的动态集合，只打本通电话里真提取到的值，两者叠加。原值只在本进程内存里，不落盘、不写日志。
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from deepsuck.redact import mask

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
        sep = r"[，,、\s]{0,2}" if len(given) >= 2 else ""
        pats.append(re.escape(cz) + r"(?:的)?" + re.escape(sur) + (r"?(?:" + sep + g + r")?" if g else "?"))
    pats.append(re.escape(name))
    if len(given) >= 2:
        pats.append(g)
    return pats


def digit_pattern(digits: str) -> str:
    """号码去空格 / 连字符等写法都认：1 3 8-1234-5678、138 1234 5678。前后不能紧挨数字。"""
    return r"(?<![0-9])" + _SEP.join(digits) + r"(?![0-9])"


class CallRedactor:
    """每通电话一份：learn(session) 记下已提取的姓名和号码，apply(text) 把它们的各种说法打码。"""

    def __init__(self):
        self._items: Dict[str, Tuple[str, str]] = {}  # key -> (正则源码, 打码值)
        self._re = None
        self._sub: List[str] = []

    def __len__(self) -> int:
        return len(self._items)

    def add(self, type_: str, raw) -> None:
        raw = str(raw or "").strip()
        if not raw:
            return
        if type_ == "name":
            for p in name_patterns(raw):
                self._items.setdefault("name|" + p, (p, mask("name", raw)))
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

    def apply(self, text) -> str:
        s = str(text or "")
        if not self._items or not s:
            return s
        if self._re is None:
            # 长的说法先匹配（“弓长张三丰”先于“张三丰”先于“三丰”）
            items = sorted(self._items.values(), key=lambda x: len(x[0]), reverse=True)
            self._sub = [m for _, m in items]
            self._re = re.compile("|".join("(" + p + ")" for p, _ in items))
        return self._re.sub(lambda m: self._sub[m.lastindex - 1], s)
