"""脱敏模块（与 site/assets/js/redact.js 等价）：所有对外展示 / 导出的情报都必须经过这里。"""
from __future__ import annotations

import functools
import re
from typing import Iterable, List, Optional

from .core import compile_js, load


def _digits(s) -> str:
    return re.sub(r"[^0-9]", "", str(s or ""))


def _stars(n: int) -> str:
    return "*" * max(0, n)


def mask_bank_card(v) -> str:
    """PCI DSS：16–19 位保留前 6 位与后 4 位；8–15 位只留后 4 位；少于 8 位全部打码。"""
    d = _digits(v)
    if len(d) < 8:
        return _stars(len(d))
    if len(d) < 16:
        return _stars(len(d) - 4) + d[-4:]
    return d[:6] + _stars(len(d) - 10) + d[-4:]


def format_card_groups(v) -> str:
    """仅用于展示：把（已打码的）卡号每 4 位一组，622202*********3445 -> 6222 02** **** ***3 445。

    存储、导出、STIX 仍用不分组的 mask_bank_card 结果；含数字与 * 以外字符的值原样返回。
    """
    raw = "" if v is None else str(v)
    s = re.sub(r"[\s-]", "", raw)
    if not re.fullmatch(r"[0-9*]+", s):
        return raw
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def mask_phone(v) -> str:
    d = _digits(v)
    if len(d) == 13 and d.startswith("86"):
        d = d[2:]
    if re.match(r"^400|^800", d) and len(d) == 10:
        return d[:3] + "-***-" + d[-4:]
    if len(d) == 11:
        return d[:3] + "****" + d[-4:]
    if len(d) <= 4:
        return _stars(len(d))
    return d[:2] + _stars(len(d) - 4) + d[-2:]


def mask_crypto(v) -> str:
    s = str(v or "")
    if len(s) <= 10:
        return s[:2] + "..."
    head = 6 if re.match(r"^0x", s, re.I) else (6 if re.match(r"^bc1", s, re.I) else 4)
    return s[:head] + "..." + s[-4:]


def mask_qq(v) -> str:
    d = _digits(v)
    if len(d) <= 4:
        return _stars(len(d))
    return d[:2] + _stars(len(d) - 4) + d[-2:]


def mask_handle(v) -> str:
    s = str(v or "")
    if len(s) <= 4:
        return s[:1] + _stars(len(s) - 1)
    return s[:2] + _stars(min(6, len(s) - 4)) + s[-2:]


def mask_id_card(v) -> str:
    s = re.sub(r"\s", "", str(v or "").upper())
    if len(s) < 10:
        return _stars(len(s))
    return s[:6] + "********" + s[-4:]


def mask_name(v) -> str:
    s = str(v or "")
    if not s:
        return ""
    return s[0] + _stars(len(s) - 1)


def mask_email(v) -> str:
    s = str(v or "")
    at = s.find("@")
    if at < 1:
        return mask_handle(s)
    user = s[:at]
    return user[: min(2, len(user))] + "***" + s[at:]


_URL = re.compile(r"^((?:https?:)?//)?([^/?#:]+)(:[0-9]+)?([/?#].*)?$", re.I | re.S)


def mask_url(v) -> str:
    s = str(v or "").strip()
    m = _URL.match(s)
    if not m:
        return "***"
    proto = m.group(1) or ""
    host = m.group(2) or ""
    if re.match(r"^www\.", host, re.I):
        proto += host[:4]
        host = host[4:]
    has_path = bool(m.group(4) and len(m.group(4)) > 1)
    labels = host.split(".")
    tld = labels.pop() if len(labels) > 1 else ""
    rest = ".".join(labels)
    if re.fullmatch(r"[0-9]+(\.[0-9]+){2}", rest):
        masked_rest = rest.split(".")[0] + ".*.*"
    elif len(rest) <= 4:
        masked_rest = rest[:1] + "***"
    else:
        masked_rest = rest[:2] + "***" + rest[-2:]
    return proto + masked_rest + ("." + tld if tld else "") + ("/***" if has_path else "")


def _mask_alipay(v) -> str:
    if "@" in str(v):
        return mask_email(v)
    if re.fullmatch(r"[0-9]{11}", _digits(v)):
        return mask_phone(v)
    return mask_handle(v)


MASKERS = {
    "bank_card": mask_bank_card,
    "phone": mask_phone,
    "hotline": mask_phone,
    "crypto_btc": mask_crypto,
    "crypto_eth": mask_crypto,
    "crypto_tron": mask_crypto,
    "url": mask_url,
    "qq": mask_qq,
    "wechat": mask_handle,
    "alipay": _mask_alipay,
    "email": mask_email,
    "id_card": mask_id_card,
    "name": mask_name,
}


def mask(type_: str, value) -> str:
    """按情报类型脱敏；未知类型保守地打码。"""
    fn = MASKERS.get(type_)
    return fn(value) if fn else mask_handle(value)


# ---- 验证码类短数字（#33）：规则见 core/extractors.json 的 redact.otp，与 redact.js 共用 ----
@functools.lru_cache(maxsize=None)
def _otp_rules():
    o = (load("extractors").get("redact") or {}).get("otp")
    if not o:
        return None
    d, sep = o["digit"], o["sep"]
    return {
        "o": o,
        "kw": compile_js(o["keyword"], o.get("keywordFlags", "")),
        "run": compile_js(d + "(?:" + sep + "{0," + str(o["maxSep"]) + "}" + d + ")*"),
        "digit": compile_js(d),
        "join": compile_js(o["join"]),
        "breaks": compile_js(o["breaks"]),
        "gapBlock": compile_js(o["gapBlock"]),
        "edge": compile_js(o["edge"]),
        "blockBefore": compile_js(o["blockBefore"]),
        "unitAfter": compile_js(o["unitAfter"]),
    }


def find_otp_spans(text: Optional[str]) -> List[dict]:
    """找出文本里按上下文判定为验证码的数字串：[{start, end, masked}]。

    只在验证码 / 动态码 / 校验码 / 短信码 / 确认码 / OTP 等关键词附近、4–8 位时才算；
    手机号、卡号（位数超出）、金额、尾号、订单号、与关键词无关的数字都不算。
    """
    R = _otp_rules()
    s = str(text or "")
    if not R:
        return []
    o = R["o"]
    kws = [(m.start(), m.end()) for m in R["kw"].finditer(s)]
    if not kws:
        return []
    groups: List[dict] = []
    for m in R["run"].finditer(s):
        n = len(R["digit"].findall(m.group(0)))
        g = groups[-1] if groups else None
        # 两段都不超过 joinPartMax 位、中间只有「，」「、」时连成一串（「4 7 2，9 1 5」）
        if (g and g["last"] <= o["joinPartMax"] and n <= o["joinPartMax"] and g["n"] + n <= o["maxLen"]
                and R["join"].search(s[g["end"]:m.start()])):
            g["end"], g["n"], g["last"] = m.end(), g["n"] + n, n
        else:
            groups.append({"start": m.start(), "end": m.end(), "n": n, "last": n})

    def repeated(g) -> bool:
        # 超过 maxLen 位时只接受空白隔开的两段、每段 minLen–maxLen 位（重复报码「472915 472915」）；
        # 手机号（3-4-4）、卡号（4 段以上）不在此列，由实体规则负责
        parts = re.split(r"\s+", s[g["start"]:g["end"]])
        return len(parts) == 2 and all(o["minLen"] <= len(R["digit"].findall(p)) <= o["maxLen"] for p in parts)

    out = []
    for g in groups:
        a, b = g["start"], g["end"]
        if g["n"] < o["minLen"] or (g["n"] > o["maxLen"] and not repeated(g)):
            continue
        if (a > 0 and R["edge"].match(s[a - 1])) or (b < len(s) and R["edge"].match(s[b])):
            continue
        if R["blockBefore"].search(s[max(0, a - o["blockBeforeChars"]):a]) or R["unitAfter"].search(s[b:]):
            continue
        near = False
        for k0, k1 in kws:
            if k1 <= a:
                if a - k1 > o["after"]:
                    continue
                gap = s[k1:a]
            elif k0 >= b:
                if k0 - b > o["before"]:
                    continue
                gap = s[b:k0]
            else:
                continue
            if not R["gapBlock"].search(gap) and len(R["breaks"].findall(gap)) <= o["maxBreaks"]:
                near = True
                break
        if near:
            out.append({"start": a, "end": b, "masked": R["digit"].sub("*", s[a:b])})
    return out


def redact_text(text: Optional[str], entities: Optional[Iterable[dict]]) -> str:
    """把文本中的敏感片段替换成脱敏结果（entities 来自 extract()）；
    另外按上下文给验证码类短数字打码（与实体重叠的交给实体自己的规则）。"""
    s = str(text or "")
    ents = [e for e in (entities or []) if isinstance(e.get("start"), int)]
    lst = [{"start": e["start"], "end": e["end"], "masked": e.get("masked") or mask(e["type"], e["value"])}
           for e in ents if e.get("sensitive") is not False]
    for p in find_otp_spans(s):
        if not any(e["start"] < p["end"] and p["start"] < e["end"] for e in ents):
            lst.append(p)
    if not lst:
        return s
    lst.sort(key=lambda e: e["start"], reverse=True)
    for e in lst:
        s = s[: e["start"]] + e["masked"] + s[e["end"]:]
    return s
