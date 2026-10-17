"""情报提取器（与 site/assets/js/extractors.js 等价）。

识别银行卡、手机号、钱包地址、URL、QQ/微信/支付宝等；敏感结果都带 masked 字段，展示与导出只能用 masked。
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional

from .core import compile_js, load
from .normalize import normalize
from . import redact as R

_C = load("extractors")
LABELS: dict = _C["labels"]
BANKS: List[str] = _C["banks"]
CHANNELS: List[str] = _C["channels"]
RE = {k: compile_js(v["source"], v.get("flags", "")) for k, v in _C["patterns"].items()}


def luhn(num) -> bool:
    d = re.sub(r"[^0-9]", "", str(num))
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


def _overlaps(spans, s, e) -> bool:
    return any(s < b and e > a for a, b in spans)


def _trim_url(u: str, *_):
    return re.sub(r"[.,;:!?'\"）)\]]+$", "", u)


_NOT_NAMES = re.compile(r"^(?:姓名|是谁|写清|发我|多少|什么|哪个|一下|清楚)")


def _clean_name(n: str, *_):
    if _NOT_NAMES.search(n):
        return None
    m = re.search(r"[开卡银账的是在和与就吧了啊呢哦，]", n)
    if m and m.start() >= 2:
        n = n[: m.start()]
    return n if len(n) >= 2 else None


def _js_number(x: str):
    f = float(x)
    return int(f) if f.is_integer() else f


def extract(text: Optional[str]) -> List[dict]:
    """extract(text) -> [{type, label, value, masked, start, end, sensitive, meta}]

    value 只应保存在内存里用于去重；任何展示/导出都应使用 masked。
    """
    raw_text = str(text or "")
    norm = normalize(raw_text)
    s = norm.text
    out: List[dict] = []
    claimed: list = []

    def scan(pat: re.Pattern, type_: str, group: int = 0, clean: Optional[Callable] = None,
             sensitive: bool = True, no_overlap: bool = False, meta: Optional[Callable] = None):
        for m in pat.finditer(s):
            raw = m.group(group) if group else m.group(0)
            if not raw:
                continue
            start = m.start() + m.group(0).rfind(raw) if group else m.start()
            if clean:
                c = clean(raw, m, start)
                if not c:
                    continue
                raw = c
            end = start + len(raw)
            if sensitive and _overlaps(claimed, start, end):
                continue
            if not sensitive and no_overlap and _overlaps(claimed, start, end):
                continue
            md = meta(raw, m, start) if meta else {}
            if md is False:
                continue
            out.append({
                "type": type_,
                "label": LABELS.get(type_, type_),
                "value": raw,
                "masked": R.mask(type_, raw) if sensitive else raw,
                "start": start,
                "end": end,
                "sensitive": sensitive,
                "meta": md or {},
            })
            if sensitive:
                claimed.append((start, end))

    def id_meta(raw, m, start):
        before = s[max(0, start - 12):start]
        ctx = bool(re.search(r"身份证|证件号|身份号", before))
        if not ctx and raw.startswith("62") and luhn(raw):
            return False  # 更像 62 开头的银联卡
        return {"context": ctx}

    def card_meta(raw, m, start):
        d = re.sub(r"[^0-9]", "", raw)
        if len(d) < 16 or len(d) > 19:
            return False
        if re.fullmatch(r"([0-9])\1+", d):
            return False
        ctx = s[max(0, start - 24):min(len(s), start + len(raw) + 24)]
        bank = next((b for b in BANKS if b in ctx), None)
        return {"digits": len(d), "luhn": luhn(d), "unionpay": d.startswith("62"), "bank": bank}

    scan(RE["urlFull"], "url", clean=_trim_url)
    scan(RE["alipay"], "alipay", group=1)
    scan(RE["qq"], "qq", group=1)
    scan(RE["wechat"], "wechat", group=1)
    scan(RE["email"], "email")
    scan(RE["urlBare"], "url", clean=_trim_url,
         meta=lambda raw, m, st: {"bare": True} if re.search(r"[a-z]", raw.split(".")[0], re.I) else False)
    scan(RE["eth"], "crypto_eth", meta=lambda *a: {"chain": "Ethereum/EVM"})
    scan(RE["tron"], "crypto_tron", meta=lambda *a: {"chain": "TRON"})
    scan(RE["btc"], "crypto_btc", meta=lambda *a: {"chain": "Bitcoin"})
    scan(RE["idCard"], "id_card", meta=id_meta)
    scan(RE["bankCard"], "bank_card", meta=card_meta)
    scan(RE["hotline"], "phone", meta=lambda *a: {"kind": "hotline"})
    scan(RE["landline"], "phone", meta=lambda *a: {"kind": "landline"})
    scan(RE["mobile"], "phone", meta=lambda *a: {"kind": "mobile"})
    scan(RE["name"], "name", group=1, clean=_clean_name)

    # 非敏感的上下文情报（不打码、不占用区间）
    scan(RE["amount"], "amount", sensitive=False, no_overlap=True,
         meta=lambda raw, m, st: {"number": _js_number(m.group(1)), "unit": m.group(2)})
    scan(RE["appName"], "app_name", group=1, sensitive=False)
    app_seen = {e["value"] for e in out if e["type"] == "app_name"}
    scan(RE["appQuoted"], "app_name", group=1, sensitive=False,
         clean=lambda raw, *a: None if raw in app_seen else raw)
    for b in BANKS:
        i = s.find(b)
        if i >= 0:
            out.append({"type": "bank_name", "label": LABELS["bank_name"], "value": b, "masked": b,
                        "start": i, "end": i + len(b), "sensitive": False, "meta": {}})
    seen_ch = set()
    for c in CHANNELS:
        i = s.find(c)
        if i >= 0 and c.lower() not in seen_ch:
            seen_ch.add(c.lower())
            out.append({"type": "channel", "label": LABELS["channel"], "value": c, "masked": c,
                        "start": i, "end": i + len(c), "sensitive": False, "meta": {}})

    if norm.changed:
        for e in out:
            a, b = norm.span(e["start"], e["end"])
            if e["sensitive"] is False:
                e["raw"] = raw_text[a:b]
            e["start"], e["end"] = a, b
            if e["sensitive"]:
                e["obfuscated"] = raw_text[a:b] != e["value"]
    out.sort(key=lambda e: e["start"])
    return out


def extract_sensitive(text: Optional[str]) -> List[dict]:
    """只取敏感情报（账户/地址/联系方式等）。"""
    return [e for e in extract(text) if e["sensitive"]]
