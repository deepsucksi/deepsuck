"""情报提取器（与 site/assets/js/extractors.js 等价）。

识别银行卡、手机号、钱包地址、URL、QQ/微信/支付宝等；敏感结果都带 masked 字段，展示与导出只能用 masked。
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional

from .core import compile_js, load
from .normalize import normalize
from . import redact as R
from .cardbin import lookup as cardbin_lookup

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


_NOT_NAMES = re.compile(_C["nameRules"]["notNames"])
_NAME_BOUNDARY = re.compile(_C["nameRules"]["boundary"])
_SURNAMES = _C["nameRules"]["surnames"]
_TITLES = tuple(_C["nameRules"]["titleSuffix"])


_NAME_DIGITS = "零一二三四五六七八九"


def _clean_name(n: str, m=None, start: Optional[int] = None):
    # ASR 数字规整（ITN）会把“张三”转成“张3”：单个阿拉伯数字还原为汉字（等长，脱敏区间不变）
    n = re.sub(r"[0-9]", lambda m: _NAME_DIGITS[int(m.group(0))], n)
    if _NOT_NAMES.search(n):
        return None
    c = re.search(r"[开卡银账的是事在和与就吧了啊呢哦，电手微那呃嗯合你我找他她这打转加对说哈]|然后", n)
    if c and c.start() >= 2:
        n = n[: c.start()]
    # “户名周杰农业银行”（户名后的逗号被去掉）：第 3、4 个字起是银行名 / 开户行时截断
    if m is not None and start is not None:
        for k in (2, 3):
            if k < len(n) and _NAME_BOUNDARY.match(m.string[start + k:]):
                n = n[:k]
                break
    return n if len(n) >= 2 else None


def _clean_name_mid(n: str, m=None, start: Optional[int] = None):
    """句中姓名（“钱转到李强的账户”）：必须以常见姓氏开头，其余规则同 _clean_name。"""
    if not n or n[0] not in _SURNAMES or any(n.endswith(t) for t in _TITLES):
        return None
    return _clean_name(n, m, start)


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
        md = {"digits": len(d), "luhn": luhn(d), "unionpay": d.startswith("62"), "bank": bank}
        # 本地 BIN 表（hexindai/bcbc，MIT）：只记录发卡行与卡种，不记录 BIN 数字本身
        b = cardbin_lookup(d)
        if b:
            md["issuer"] = {"bank": b["bank"], "bankCode": b["bankCode"], "cardType": b["cardType"],
                            "cardTypeName": b["cardTypeName"], "lengthOk": b["lengthOk"]}
            if not bank:
                md["bank"] = b["bank"]
                md["bankFrom"] = "bin"
        return md

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
    scan(RE["nameMid"], "name", group=1, clean=_clean_name_mid)

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


# ---- 跨回合拼接（与 site/assets/js/extractors.js 的 stitch 等价）----
from .normalize import plausible_number as _plausible  # noqa: E402
from .cardbin import lookup as _bin_lookup  # noqa: E402

_ST: dict = _C.get("stitch") or {}
_DJ = _C["obfuscation"]["digitJoin"]
_SEP_CLS = "[" + "".join("\\" + c if c in "]\\^-" else {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(c, c)
                         for c in _DJ["separators"]) + "]"
_FRAG = "[0-9](?:" + _SEP_CLS + "{0,3}[0-9])*"
_RE_TAIL = re.compile("(" + _FRAG + ")(" + re.sub(r"\$$", "", _ST.get("tailFiller", "$")) + ")$")
_RE_HEAD = re.compile("(" + re.sub(r"^\^", "", _ST.get("headFiller", "^")) + ")(" + _FRAG + ")")
_RE_TAIL_ONLY = re.compile("^" + _ST.get("tailFiller", "$"))
_RE_UNIT = re.compile(_DJ["unitAfter"])
_RE_BANK_CTX = re.compile(_ST.get("bankContext", "卡号"))
_RE_PHONE_CTX = re.compile(_ST.get("phoneContext", "电话"))
_RE_BLOCK_BEFORE = re.compile(_ST["blockBefore"]) if _ST.get("blockBefore") else None
_RE_BLOCK_AFTER = re.compile(_ST["blockAfter"]) if _ST.get("blockAfter") else None
_BLOCK_TYPOS: dict = ((_ST.get("blockTypos") or {}).get("map")) or {}
_RE_BLOCK_TYPOS = re.compile("|".join(re.escape(k) for k in sorted(_BLOCK_TYPOS, key=lambda k: (-len(k), k)))) if _BLOCK_TYPOS else None


def _unblock_typos(t: str) -> str:
    """屏蔽词的手写错字（房问号 / 工好）换回正写再判断（等长替换）。"""
    return _RE_BLOCK_TYPOS.sub(lambda m: _BLOCK_TYPOS[m.group(0)], t) if _RE_BLOCK_TYPOS else t


_NUMERALS: dict = _C["obfuscation"]["numerals"]
_RE_NUMERAL_CHAR = re.compile("[" + "".join(_NUMERALS) + "]")


def _round2(x: float) -> float:
    import math
    v = math.floor(x * 100 + 0.5) / 100
    return int(v) if float(v).is_integer() else v


def _fragments(raw: str) -> dict:
    norm = normalize(raw)
    ents = extract_sensitive(raw)
    # 片段可能短于 numeralRunMin（“二二三三”），这里把中文数字逐字换成阿拉伯数字（等长，坐标不变）
    s = _RE_NUMERAL_CHAR.sub(lambda m: _NUMERALS[m.group(0)], norm.text)

    def free(a, b):
        sa, sb = norm.span(a, b)
        return not any(e["start"] < sb and e["end"] > sa for e in ents)

    def weak_card(a, b):
        """#1：片段被单回合提取认成了银行卡、但只是 16–18 位且不过 Luhn（多半是拆开的长卡号的一段）：
        允许它参与拼接，拼接结果过 Luhn 时取代这条单段结果（stitch 输出里的 supersedes）。"""
        sa, sb = norm.span(a, b)
        hit = [e for e in ents if e["start"] < sb and e["end"] > sa]
        if len(hit) != 1 or hit[0]["type"] != "bank_card":
            return None
        d = re.sub(r"[^0-9]", "", s[a:b])
        e = hit[0]
        if re.sub(r"[^0-9]", "", str(e["value"])) != d or len(d) > 18 or luhn(d):
            return None
        return e

    def mk(a, b, **extra):
        sa, sb = norm.span(a, b)
        o = {"start": sa, "end": sb, "digits": re.sub(r"[^0-9]", "", s[a:b]), "ns": a, "ne": b}
        o.update(extra)
        return o

    out = {"text": s, "ents": ents, "head": None, "tail": None}
    t = _RE_TAIL.search(s)
    if t:
        a, b = t.start(), t.start() + len(t.group(1))
        wk = None if free(a, b) else weak_card(a, b)
        if (wk or free(a, b)) and not (_RE_BLOCK_BEFORE and _RE_BLOCK_BEFORE.search(_unblock_typos(s[max(0, a - 16):a]))):
            out["tail"] = mk(a, b, before=s[max(0, a - 16):a])
            if wk:
                out["tail"]["weak"] = wk
    h = _RE_HEAD.match(s)
    if h:
        a2 = len(h.group(1))
        b2 = a2 + len(h.group(2))
        rest = s[b2:]
        wk = None if free(a2, b2) else weak_card(a2, b2)
        if (wk or free(a2, b2)) and not _RE_UNIT.match(rest) and not (_RE_BLOCK_AFTER and _RE_BLOCK_AFTER.search(_unblock_typos(rest))):
            out["head"] = mk(a2, b2, only=bool(_RE_TAIL_ONLY.match(rest)))
            if wk:
                out["head"]["weak"] = wk
    if out["tail"] and _RE_UNIT.match(s[out["tail"]["ne"]:]):
        out["tail"] = None
    return out


def _score(d: str, ctx: str) -> Optional[dict]:
    kind = _plausible(d)
    if not kind:
        return None
    if kind == "phone":
        return {"type": "phone", "conf": _round2(0.6 + (0.3 if _RE_PHONE_CTX.search(ctx) else 0)), "meta": {"kind": "mobile"}}
    b = _bin_lookup(d)
    lu = luhn(d)
    conf = 0.3 + (0.3 if lu else 0) + (0.2 if b else 0) + (0.1 if b and b["lengthOk"] else 0) \
        + (0.1 if d.startswith("62") else 0) + (0.2 if _RE_BANK_CTX.search(ctx) else 0)
    md = {"digits": len(d), "luhn": lu, "unionpay": d.startswith("62"), "bank": next((x for x in BANKS if x in ctx), None)}
    if b:
        md["issuer"] = {"bank": b["bank"], "bankCode": b["bankCode"], "cardType": b["cardType"],
                        "cardTypeName": b["cardTypeName"], "lengthOk": b["lengthOk"]}
        if not md["bank"]:
            md["bank"] = b["bank"]
            md["bankFrom"] = "bin"
    return {"type": "bank_card", "conf": _round2(min(1, conf)), "meta": md}


def stitch(turns, window: Optional[int] = None, min_confidence: Optional[float] = None) -> List[dict]:
    """stitch(turns) -> 拼接得到的情报列表（见 JS 版说明）。turns 为同一说话方相邻回合的原文，按时间顺序。"""
    W = window or _ST.get("window", 3)
    min_conf = _ST.get("minConfidence", 0.5) if min_confidence is None else min_confidence
    F = [_fragments("" if t is None else str(t)) for t in (turns or [])]
    out, seen = [], set()
    for f in F:
        for e in f["ents"]:
            seen.add(e["type"] + "|" + re.sub(r"[^0-9A-Za-z]", "", str(e["value"])).lower())
    i = 0
    while i < len(F):
        tail = F[i]["tail"]
        if not tail or len(tail["digits"]) < 3:
            i += 1
            continue
        parts = [(i, tail)]
        d = tail["digits"]
        best = None
        for j in range(i + 1, min(len(F), i + W)):
            h = F[j]["head"]
            if not h or (j > i + 1 and not parts[-1][1].get("only")):
                break
            if j > i + 1 and not F[j - 1]["head"]:
                break
            parts.append((j, h))
            d += h["digits"]
            if len(d) > 19:
                break
            sc = _score(d, tail["before"] + F[i]["text"][tail["ns"]:tail["ne"]])
            if sc and any(p[1].get("weak") for p in parts) and not (sc["type"] == "bank_card" and sc["meta"]["luhn"]):
                sc = None  # 含被单回合认成卡号的片段：拼接结果必须是过 Luhn 的银行卡才取代它
            if sc and sc["conf"] >= min_conf and (best is None or sc["conf"] > best[0]["conf"]
                                                    or (sc["conf"] == best[0]["conf"] and len(d) > len(best[1]))):
                best = (sc, d, list(parts))
        if not best:
            i += 1
            continue
        sc, d, ps = best
        key = sc["type"] + "|" + d
        if key in seen:
            i += 1
            continue
        seen.add(key)
        masked = R.mask(sc["type"], d)
        same = len(masked) == len(d)
        off = 0
        plist = []
        for turn, f in ps:
            n = len(f["digits"])
            plist.append({"turn": turn, "start": f["start"], "end": f["end"], "masked": masked[off:off + n] if same else "*" * n})
            off += n
        md = sc["meta"]
        md["stitched"] = True
        o = {"type": sc["type"], "label": LABELS.get(sc["type"], sc["type"]), "value": d, "masked": masked,
             "sensitive": True, "confidence": sc["conf"], "turns": [p[0] for p in ps], "parts": plist, "meta": md}
        sup = [{"turn": turn, "type": f["weak"]["type"], "value": f["weak"]["value"], "start": f["weak"]["start"],
                "end": f["weak"]["end"]} for turn, f in ps if f.get("weak")]
        if sup:
            o["supersedes"] = sup
        out.append(o)
        i = ps[-1][0]  # 已用掉的回合不再作为起点（JS 版 i = last - 1 后 i++）
    return out
