"""#209（b）：不重复追问。发出前的确定性处理，不往提示词里加规则句。

一条回复里，问「已经拿到的字段」或「上一条回复刚问过的同一字段」的短问句（按逗号、句号分的小句）去掉；第一小句不去（免得整条变空）。
送 TTS 时按句分段过（GuardTextFilter），会话记录整条过（BotTextTap），两边结果一致：同一条回复里第一段照放，后面的段才可能去掉。
字段：bank（卡号 / 账号）、name（户名 / 收款人）、phone、url、wallet，与 session.have_goal 的目标同名。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set

FIELDS: Dict[str, re.Pattern] = {
    "bank": re.compile(r"卡号|账号|帐号|哪张卡|开户行|哪个银行|哪家银行"),
    "name": re.compile(r"户名|收款人|名字"),
    "phone": re.compile(r"电话|手机号"),
    "url": re.compile(r"链接|网址"),
    "wallet": re.compile(r"钱包|地址"),
}
_ASK = re.compile(r"多少|是谁|叫啥|叫什么|是什么|是啥|哪个|哪家|哪张|报一下|报下|说一下|说下|再说|念一下|念一遍|发一下|发过来|发我|给我|[？?]")
_SENT = re.compile(r"[^。？！?!；;…\n，,]+[。？！?!；;…\n，,\s]*")  # 按分句（含逗号）切
ASK_MAX = 12  # 只去短问句（去标点后不超过 12 字），带别的内容的长句不动
_PUNCT = re.compile(r"[\s。，,、？！?!；;…：:~～—\-\"“”'‘’]")


def asked(text: str) -> Set[str]:
    """一段话里问到了哪些字段（只看短问句）。"""
    out: Set[str] = set()
    for m in _SENT.finditer(str(text or "")):
        out |= _ask_fields(m.group(0))
    return out


def _ask_fields(sent: str) -> Set[str]:
    core = _PUNCT.sub("", sent)
    if not core or len(core) > ASK_MAX or not _ASK.search(sent):
        return set()
    return {f for f, rx in FIELDS.items() if rx.search(sent)}


def _drop(sent: str, have: Set[str], last: Set[str]) -> bool:
    f = _ask_fields(sent)
    return bool(f) and f <= (set(have) | set(last))


def drop_reask(text: str, have: Iterable[str], last: Iterable[str]) -> str:
    """整条回复：第一句以后，问的字段全在 have（已拿到）或 last（上一条刚问过）里的短问句去掉。"""
    have, last = set(have or ()), set(last or ())
    sents = [m.group(0) for m in _SENT.finditer(str(text or ""))]
    if len(sents) <= 1 or not (have or last):
        return str(text or "")
    keep = [sents[0]] + [x for x in sents[1:] if not _drop(x, have, last)]
    return "".join(keep).rstrip("，, ")


class ReaskGuard:
    """每通电话一份：从 session 取已拿到的字段、上一条人设回复问过的字段；按回复记已放出的段（送 TTS 分段用）。"""

    GOALS = ("bank", "name", "phone", "url", "wallet")

    def __init__(self, session):
        self.session = session
        self._key: Optional[int] = None
        self._emitted = False

    def have(self) -> Set[str]:
        return {g for g in self.GOALS if self.session.have_goal(g)}

    def last_asked(self) -> Set[str]:
        bots = [m for m in getattr(self.session, "messages", []) or [] if m.get("role") == "bot"]
        return asked(bots[-1].get("text", "")) if bots else set()

    def _reply_key(self) -> int:
        return sum(1 for m in getattr(self.session, "messages", []) or [] if m.get("role") == "bot")

    def text(self, text: str) -> str:
        """整条回复（会话记录用）。"""
        return drop_reask(text, self.have(), self.last_asked())

    def segment(self, seg: str) -> str:
        """送 TTS 的一段：同一条回复里已经放出过一段以后，整段都是该去的短问句就去掉。"""
        key = self._reply_key()
        if key != self._key:
            self._key, self._emitted = key, False
        sents = [m.group(0) for m in _SENT.finditer(str(seg or ""))]
        if not sents:
            return seg
        have, last = self.have(), self.last_asked()
        out: List[str] = []
        for x in sents:
            if self._emitted and _drop(x, have, last):
                continue
            out.append(x)
            if _PUNCT.sub("", x):
                self._emitted = True
        return "".join(out)

    def reset(self):
        self._key, self._emitted = None, False
