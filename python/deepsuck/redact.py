"""脱敏模块（与 site/assets/js/redact.js 等价）：所有对外展示 / 导出的情报都必须经过这里。"""
from __future__ import annotations

import re
from typing import Iterable, Optional


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


def redact_text(text: Optional[str], entities: Optional[Iterable[dict]]) -> str:
    """把文本中的敏感片段替换成脱敏结果（entities 来自 extract()）。"""
    s = str(text or "")
    if not entities:
        return s
    lst = [e for e in entities if isinstance(e.get("start"), int) and e.get("sensitive") is not False]
    lst.sort(key=lambda e: e["start"], reverse=True)
    for e in lst:
        s = s[: e["start"]] + (e.get("masked") or mask(e["type"], e["value"])) + s[e["end"]:]
    return s
