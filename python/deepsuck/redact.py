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
    if "*" in host or "＊" in host:  # #260：已打码网址再 mask 会把 192.*.* 打成 19***，保持原样
        return s
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
        "segJoin": compile_js(o.get("segJoin") or "^$"),
    }


def find_otp_spans(text: Optional[str]) -> List[dict]:
    """找出文本里按上下文判定为验证码的数字串：[{start, end, masked}]。

    只在验证码 / 动态码 / 校验码 / 短信码 / 确认码 / OTP 等关键词附近、4–8 位时才算；
    手机号、卡号（位数超出）、金额、尾号、订单号、与关键词无关的数字都不算。
    """
    R = _otp_rules()
    if not R:
        return []
    return _find_otp(R, str(text or ""), ())


def _find_otp(R, s: str, bounds) -> List[dict]:
    """bounds：拼接文本里各分段的接缝位置（#92），接缝两侧的数字串之间只有 segJoin 时可连成一串。"""
    o = R["o"]
    kws = [(m.start(), m.end()) for m in R["kw"].finditer(s)]
    if not kws:
        return []
    groups: List[dict] = []
    for m in R["run"].finditer(s):
        n = len(R["digit"].findall(m.group(0)))
        g = groups[-1] if groups else None
        # 两段都不超过 joinPartMax 位、中间只有「，」「、」时连成一串（「4 7 2，9 1 5」）
        if g and g["n"] + n <= o["maxLen"] and (
                (g["last"] <= o["joinPartMax"] and n <= o["joinPartMax"] and R["join"].search(s[g["end"]:m.start()]))
                or (any(g["end"] <= b <= m.start() for b in bounds) and R["segJoin"].search(s[g["end"]:m.start()]))):
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


def otp_seg_window() -> int:
    """跨分段验证码判断看前后几段（redact.otp.segWindow，#92）。"""
    R = _otp_rules()
    return int(R["o"].get("segWindow", 2)) if R else 0


def find_otp_spans_segments(texts: Optional[Iterable[Optional[str]]], window: Optional[int] = None) -> List[List[dict]]:
    """跨 ASR 分段找验证码（#92）：texts 是同一通电话、同一说话方按时间排的连续分段。

    以每段为中心、连同前后各 window（默认 redact.otp.segWindow）段用 segJoiner 拼接，按 find_otp_spans 的同一套规则
    再找一遍，命中的数字串按分段切开映射回窗口里的各段（各窗口结果取并集：第 i 段的结果只取决于前后各 2×window 段）。返回与 texts 等长的列表，每项是该段的 [{start, end, masked}]（段内下标，已合并）。
    单段内的结果也包含在内；与实体的重叠由调用方处理——建议对逐段 redact_text 之后的文本调用（打码值紧挨 * 不会被当成验证码）。
    """
    segs = ["" if t is None else str(t) for t in (texts or [])]
    R = _otp_rules()
    hits: List[List[tuple]] = [[] for _ in segs]
    if not R or not segs:
        return [[] for _ in segs]
    o = R["o"]
    w = max(0, int(o.get("segWindow", 2) if window is None else window))
    joiner = o.get("segJoiner", " ")
    seen = set()
    for c in range(len(segs)):
        win = (max(0, c - w), min(len(segs), c + w + 1))
        if win in seen:
            continue
        seen.add(win)
        idx = list(range(*win))
        offs, bounds, pos = [], [], 0
        for k, i in enumerate(idx):
            if k:
                bounds.append(pos)
                pos += len(joiner)
                bounds.append(pos)
            offs.append(pos)
            pos += len(segs[i])
        joined = joiner.join(segs[i] for i in idx)
        for sp in _find_otp(R, joined, bounds):
            for k, i in enumerate(idx):
                a, b = max(sp["start"], offs[k]), min(sp["end"], offs[k] + len(segs[i]))
                if a < b:
                    hits[i].append((a - offs[k], b - offs[k]))
    out: List[List[dict]] = []
    for i, hs in enumerate(hits):
        merged: List[list] = []
        for a, b in sorted(hs):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out.append([{"start": a, "end": b, "masked": R["digit"].sub("*", segs[i][a:b])} for a, b in merged])
    return out


def redact_otp_segments(texts: Optional[Iterable[Optional[str]]], window: Optional[int] = None) -> List[str]:
    """把 find_otp_spans_segments 命中的数字换成 *（长度不变）后返回各段文本（#92）。

    对逐段 redact_text 之后的文本再调用即可；可重复调用（已打码的 * 不再匹配）。"""
    segs = ["" if t is None else str(t) for t in (texts or [])]
    out = []
    for s, sps in zip(segs, find_otp_spans_segments(segs, window)):
        for p in sorted(sps, key=lambda x: x["start"], reverse=True):
            s = s[: p["start"]] + p["masked"] + s[p["end"]:]
        out.append(s)
    return out


# ---- 卡号片段、人设侧兜底、两边说话人（#120）：规则见 core/extractors.json 的 redact.card / redact.persona ----
_CN_DIGIT = {"零": "0", "〇": "0", "一": "1", "幺": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5",
             "六": "6", "七": "7", "八": "8", "九": "9"}


def _ascii_digits(s: str) -> str:
    out = []
    for ch in s:
        if "０" <= ch <= "９":
            out.append(chr(ord(ch) - 0xFEE0))
        elif ch in _CN_DIGIT:
            out.append(_CN_DIGIT[ch])
        elif "0" <= ch <= "9":
            out.append(ch)
    return "".join(out)


@functools.lru_cache(maxsize=None)
def _card_rules():
    red = load("extractors").get("redact") or {}
    c, o = red.get("card"), red.get("otp")
    if not c or not o:
        return None
    d, sep = o["digit"], o["sep"]
    return {
        "c": c,
        "kw": compile_js(c["keyword"]),
        "run": compile_js(d + "(?:" + sep + "{0," + str(o["maxSep"]) + "}" + d + ")*"),
        "digit": compile_js(d),
        "edge": compile_js(o["edge"]),
        "prefixAfter": compile_js(c["prefixAfter"]),
        "strongBin": compile_js(c["strongBin"]),
        "notCard": compile_js(c.get("notCard") or "(?!)"),
        "tailBefore": compile_js(c["tailBefore"]),
        "tailBlock": compile_js(c["tailBlock"]),
    }


def find_card_spans(text: Optional[str]) -> List[dict]:
    """卡号片段（「6222开头」「尾号0123」，卡号语境下）：[{start, end, masked}]，数字全部换成 *。"""
    R = _card_rules()
    if not R:
        return []
    s = str(text or "")
    c = R["c"]
    kws = [(m.start(), m.end()) for m in R["kw"].finditer(s)]

    def kw_near(a, b):
        return any(k1 <= a and a - k1 <= c["window"] or k0 >= b and k0 - b <= c["window"] or (k0 < b and a < k1)
                   for k0, k1 in kws)

    runs = []
    for m in R["run"].finditer(s):
        a, b = m.start(), m.end()
        n = len(R["digit"].findall(m.group(0)))
        if (a > 0 and R["edge"].match(s[a - 1])) or (b < len(s) and R["edge"].match(s[b])):
            continue
        runs.append((a, b, n))
    prefixes = []
    for a, b, n in runs:
        if c["minLen"] <= n <= c["maxLen"] and R["prefixAfter"].search(s[b:]) \
                and not R["notCard"].search(_ascii_digits(s[a:b])):
            strong = n >= c["strongMinLen"] and R["strongBin"].search(_ascii_digits(s[a:b]))
            if strong or kw_near(a, b):
                prefixes.append((a, b))
    tails = []
    for a, b, n in runs:
        if not (c["minLen"] <= n <= c["tailMaxLen"]):
            continue
        m = R["tailBefore"].search(s[max(0, a - c["tailBeforeChars"]):a])
        if not m:
            continue
        t0 = max(0, a - c["tailBeforeChars"]) + m.start()
        if R["tailBlock"].search(s[max(0, t0 - c["tailBlockChars"]):t0]):
            continue
        if kw_near(a, b) or any(abs(a - pb) <= c["window"] or abs(pa - b) <= c["window"] for pa, pb in prefixes):
            tails.append((a, b))
    return [{"start": a, "end": b, "masked": R["digit"].sub("*", s[a:b])} for a, b in sorted(set(prefixes + tails))]


def _apply(s: str, spans) -> str:
    for p in sorted(spans, key=lambda x: x["start"], reverse=True):
        s = s[: p["start"]] + p["masked"] + s[p["end"]:]
    return s


def redact_card_segments(texts: Optional[Iterable[Optional[str]]], window: Optional[int] = None) -> List[str]:
    """卡号片段跨分段打码（窗口同 redact.otp.segWindow）：每段与前后各 window 段拼接后找 find_card_spans，映射回各段。"""
    segs = ["" if t is None else str(t) for t in (texts or [])]
    R, O = _card_rules(), _otp_rules()
    if not R or not segs:
        return segs
    w = max(0, int(O["o"].get("segWindow", 2) if window is None else window))
    joiner = O["o"].get("segJoiner", " ")
    hits: List[List[dict]] = [[] for _ in segs]
    for cidx in range(len(segs)):
        idx = list(range(max(0, cidx - w), min(len(segs), cidx + w + 1)))
        offs, pos = [], 0
        for k, i in enumerate(idx):
            pos += len(joiner) if k else 0
            offs.append(pos)
            pos += len(segs[i])
        for sp in find_card_spans(joiner.join(segs[i] for i in idx)):
            for k, i in enumerate(idx):
                a, b = max(sp["start"], offs[k]), min(sp["end"], offs[k] + len(segs[i]))
                if a < b:
                    hits[i].append({"start": a - offs[k], "end": b - offs[k],
                                    "masked": R["digit"].sub("*", segs[i][a - offs[k]:b - offs[k]])})
    out = []
    for s, hs in zip(segs, hits):
        uniq = {(h["start"], h["end"]): h for h in hs}
        cur = s
        # 重叠的区间逐个替换也安全：只把数字换成 *，长度不变
        for h in sorted(uniq.values(), key=lambda x: x["start"], reverse=True):
            cur = cur[: h["start"]] + R["digit"].sub("*", cur[h["start"]:h["end"]]) + cur[h["end"]:]
        out.append(cur)
    return out


@functools.lru_cache(maxsize=None)
def _persona_rules():
    red = load("extractors").get("redact") or {}
    p, o = red.get("persona"), red.get("otp")
    if not p or not o:
        return None
    d = o["digit"]
    return {"p": p, "digit": compile_js(d),
            "run": compile_js(d + "(?:" + p["sep"] + "{0," + str(p["maxSep"]) + "}" + d + ")*")}


def redact_persona(text: Optional[str]) -> str:
    """人设侧兜底（redact.persona）：连续 minRun 位及以上的逐位数字换成 *（长度不变，可重复执行）。"""
    s = "" if text is None else str(text)
    R = _persona_rules()
    if not R:
        return s
    return R["run"].sub(lambda m: R["digit"].sub("*", m.group(0))
                        if len(R["digit"].findall(m.group(0))) >= R["p"]["minRun"] else m.group(0), s)


def redact_dialog_segments(texts: Optional[Iterable[Optional[str]]], roles: Optional[Iterable[Optional[str]]],
                           window: Optional[int] = None) -> List[str]:
    """两边说话人合在一起打码（#120，见 redact.dialogComment）：texts 与 roles 等长、按时间排；role 为 "scammer"
    的是骗子侧，其余都算人设侧。建议对逐段 redact_text 之后的文本调用；只把数字换成 *，可重复执行。"""
    out = ["" if t is None else str(t) for t in (texts or [])]
    rs = list(roles or [])
    rs += [None] * (len(out) - len(rs))
    side = ["scammer" if r == "scammer" else "persona" for r in rs[: len(out)]]
    for who in ("scammer", "persona"):
        idx = [i for i, x in enumerate(side) if x == who]
        for i, t in zip(idx, redact_otp_segments([out[i] for i in idx], window)):
            out[i] = t
    out = redact_otp_segments(out, window)
    # 一方报数字、另一方说验证码且中间隔着别的话（「验证码多少」「是…47」「后面呢」「29」）：另一方的分段只留验证码关键词
    R = _otp_rules()
    if R:
        for who in ("scammer", "persona"):
            view = [t if side[i] == who else " ".join(m.group(0) for m in R["kw"].finditer(t))
                    for i, t in enumerate(out)]
            for i, t in enumerate(redact_otp_segments(view, window)):
                if side[i] == who:
                    out[i] = t
    out = redact_card_segments(out, window)
    return [redact_persona(t) if side[i] == "persona" else t for i, t in enumerate(out)]


# ---- 拆字报姓（#139）：规则见 core/extractors.json 的 nameRules.split，与 redact.js 共用 ----
@functools.lru_cache(maxsize=None)
def _split_rules():
    nr = load("extractors").get("nameRules") or {}
    sp = nr.get("split")
    if not sp or not sp.get("spellings"):
        return None
    alts = sorted(sp["spellings"], key=len, reverse=True)
    src = "(" + "|".join(re.escape(x[:-1]) + sp.get("link", "") + re.escape(x[-1]) for x in alts) + ")"
    asr = sp.get("asrSplit") or {}
    asr_src = ("(" + "|".join(re.escape(k) + "(?:" + sp.get("link", "") + re.escape(asr[k]) + ")?"
                              for k in sorted(asr, key=len, reverse=True)) + ")") if asr else "((?!))"
    return {
        "sp": sp,
        "re": compile_js(src),
        "asr": compile_js(asr_src),  # #163：ASR 同音写法（龚厂长），只在后面紧跟逐字解释时才算，见 split_hits
        "asrSur": asr,
        # #202 负责人决定（拿不准就遮）：首字是真姓（nameRules.surnames，龚、宫）的同音写法本身也打码（「宫长张」→「宫**」）；
        # 弓长张、尔东陈这类首字不是姓本字的拆字说法照旧不打
        "asrReal": tuple(k for k in sorted(asr, key=len, reverse=True) if k[0] in (nr.get("surnames") or "")),
        "sep": compile_js("^(?:" + sp.get("sep", "") + ")"),
        "stop": compile_js(sp["givenStop"]),
        "notNames": compile_js(nr["notNames"]) if nr.get("notNames") else None,
        # #249：拆字 / 同音写法 + 名 + 数字时，普通词白名单（「尔东陈列馆2楼」「弓长张贴500份」），与 redact.js 一致
        "numWords": tuple(sorted(sp.get("numWhitelist") or [], key=len, reverse=True)),
        "numTail": compile_js("^(?:" + (sp.get("numWhitelistTail") or "(?!)") + ")"),
    }


def split_hits(s: str, units=None) -> List[tuple]:
    """拆字报姓的位置：[(start, end, 姓)]，按 start 排。spellings 全算；asrSplit 的同音写法（#163）只在 units（explain_units
    的结果）里有一段解释紧跟在后面（按 explain.anchorGap）时才算；units 为 None 时同音写法全给出（只当锚点用，锚点本身要求紧跟解释）。"""
    R = _split_rules()
    if not R:
        return []
    out = [(m.start(), m.end(), m.group(1)[-1]) for m in R["re"].finditer(s)]
    E = _explain_rules()
    for m in R["asr"].finditer(s):
        if any(a < m.end() and m.start() < b for a, b, _ in out):
            continue
        if units is not None and not (E and any(u["start"] >= m.end() and E["gap"].search(s[m.end():u["start"]])
                                                for u in units)):
            continue
        g = m.group(1)
        key = next(k for k in sorted(R["asrSur"], key=len, reverse=True) if g.startswith(k))
        out.append((m.start(), m.end(), R["asrSur"][key]))
    return sorted(out)


def _num_whitelisted(R, s: str, sur_at: int, end: int) -> bool:
    """#249：姓那个字起到名的结尾（s[sur_at:end]）正好是白名单里的普通词，或普通词再带一个 numWhitelistTail 的字
    （「吴江路」「章程第」）时放行；「李子轩」这类比白名单词多出名字的不放行。与 redact.js numWhitelisted 一致。"""
    for w in R["numWords"]:
        if not s.startswith(w, sur_at):
            continue
        e = sur_at + len(w)
        if end <= e or (end == e + 1 and R["numTail"].match(s[e:end])):
            return True
    return False


def _num_given(R, Q, s: str, pos: int, units) -> str:
    """#249：pos 起 1–2 个汉字的名、后面紧跟数字或中文金额（sayEnd）时给出这个名，否则给空。先试 2 个字再试 1 个字：
    「工厂张三五百块」里「三五」后面是「百块」不算金额，退到「三」（后面「五百块」是金额）——「三」归名字，宁可多遮（#216）。"""
    if not Q:
        return ""
    for L in (2, 1):
        g = s[pos:pos + L]
        if len(g) < L or any(R["stop"].match(c) for c in g):
            continue
        if any(pos < u["start"] < pos + L or u["start"] == pos for u in units):
            continue
        if Q["end"].match(s[pos + L:]):
            return g
    return ""


# ---- 逐字解释名字（#158）：规则见 core/extractors.json 的 nameRules.explain，与 redact.js 共用 ----
@functools.lru_cache(maxsize=None)
def _explain_rules():
    ex = (load("extractors").get("nameRules") or {}).get("explain")
    if not ex or not ex.get("link"):
        return None
    return {
        "ex": ex,
        "han": compile_js("^" + ex["han"] + "$"),
        "link": compile_js("(?:" + ex["link"] + ")(" + ex["han"] + ")"),
        "tail": compile_js("(?:" + (ex.get("tail") or "") + ")"),
        "stop": compile_js(ex.get("wordStop") or "(?!)"),
        "tailWords": compile_js("(?:" + (ex.get("tailWords") or "(?!)") + ")"),  # #206「伟大的伟对吧」；用 match(s, pos)，不加 ^
        "particle": compile_js("^(?:" + (ex.get("particle") or "(?!)") + ")$"),
        "sep": compile_js("^(?:" + (ex.get("sep") or "") + ")$"),
        "gap": compile_js(ex["anchorGap"]),
        # #163 偏旁说法（「单人旁一个韦」「三点水的江」）：偏旁名 + (join + 部件字 + 字?)? + (link + X + tail)?，至少带一个；与 redact.js 一致
        "radical": compile_js("(?:" + "|".join(sorted(ex["radicals"], key=len, reverse=True)) + ")(?:(?:" + (ex.get("radicalJoin") or "(?!)")
                              + ")(" + ex["han"] + ")字?)?(?:(?:" + ex["link"] + ")(" + ex["han"] + ")(?:" + (ex.get("tail") or "") + "))?")
        if ex.get("radicals") else None,
        "surnames": (load("extractors").get("nameRules") or {}).get("surnames") or "",
    }


def explain_units(s: str, ents: Optional[Iterable[dict]] = None) -> List[dict]:
    """逐字解释（「伟大的伟，明天的明」「伟是伟大的伟」）：[{start, end, x, keep}]，按 start 升序、互不重叠。

    head：这一段连同前面的「就是」「是」从哪里开始（只用来判断相邻，不打码「就是」本身）；
    keep：被解释的是姓（相邻拆字报姓的姓或已提取姓名的姓），这一段不打码。与 redact.js 的 explainUnits 等价。"""
    E = _explain_rules()
    if not E:
        return []
    ex = E["ex"]
    wmin, wmax = int(ex.get("wordMin") or 2), int(ex.get("wordMax") or 4)
    leads, strong = ex.get("leads") or [], ex.get("strongLeads") or []
    han = lambda c: bool(c) and bool(E["han"].match(c))
    cands = []

    def lead_of(wstart, x):
        start = head = wstart
        st = False
        for ld in leads:
            if wstart < len(ld) or s[wstart - len(ld):wstart] != ld:
                continue
            b = wstart - len(ld)
            head = b
            if b >= 1 and s[b - 1] == x:
                start = head = b - 1
                st = True
            elif b >= 2 and s[b - 2:b] == x + "字":
                start = head = b - 2
                st = True
            elif ld in strong:
                st = True
            break
        return start, head, st

    for i in range(len(s)):
        r = E["radical"].match(s, i) if E["radical"] else None
        if r and (r.group(1) or r.group(2)):  # #163 偏旁说法：单独一段也算（strong）
            rx = r.group(2) or r.group(1)
            rs, rh, _ = lead_of(i, rx)
            cands.append({"start": rs, "head": rh, "wstart": i, "end": r.end(), "x": rx, "strong": True, "rad": True})
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
        start, head, st = lead_of(wstart, x)
        cands.append({"start": start, "head": head, "wstart": wstart, "end": end, "x": x, "strong": st})
    heads = {c["head"] for c in cands} | {c["wstart"] for c in cands}
    ok = [c for c in cands if c["end"] >= len(s) or not han(s[c["end"]]) or E["particle"].match(s[c["end"]])
          or c["end"] in heads or E["tailWords"].match(s, c["end"])]
    units: List[dict] = []
    for c in sorted(ok, key=lambda c: (c["start"], c["end"])):
        if not units or units[-1]["end"] <= c["start"]:
            units.append(c)
    if not units:
        return []
    anchors = []
    anchors += [(b, sur) for _a, b, sur in split_hits(s)]  # #163：含 asrSplit 同音写法
    sur_all = set()
    for e in ents or []:
        if not isinstance(e.get("start"), int) or e.get("type") != "name" or not e.get("value"):
            continue
        anchors.append((e["end"], str(e["value"])[0]))
        sur_all.add(str(e["value"])[0])
    out: List[dict] = []
    chain: List[dict] = []

    def flush():
        if not chain:
            return
        first = chain[0]["head"]
        sur = set(sur_all)
        anchored = False
        for a_end, a_sur in anchors:
            if a_end <= first and E["gap"].search(s[a_end:first]):
                anchored = True
                sur.add(a_sur)
        # #163：只有一段、没有锚点时，在句首或紧跟非汉字后面也算（「李子的李」「张伟晨，伟大的伟」）
        alone = bool(ex.get("standalone")) and len(chain) == 1 and (first == 0 or not han(s[first - 1]))
        if len(chain) >= 2 or anchored or alone or any(c["strong"] for c in chain):
            xs = [c["x"] for c in chain]
            out.extend({"start": c["start"], "end": c["end"], "x": c["x"], "keep": c["x"] in sur, "rad": bool(c.get("rad")),
                        **({"head": first, "xs": xs} if j == 0 else {})} for j, c in enumerate(chain))
        chain.clear()

    for u in units:
        if chain and not E["sep"].match(s[chain[-1]["end"]:u["head"]]):
            flush()
        chain.append(u)
    flush()
    return out


def find_name_spans(text: Optional[str], entities: Optional[Iterable[dict]] = None) -> List[dict]:
    """拆字报姓（「弓长张，三丰」「木子李四」）后紧跟的名：[{start, end, masked}]，名换成等长的 *。

    entities：extract() 的结果；同姓的已提取姓名决定名的长度，与敏感实体重叠的位置不再重复给出。
    逐字解释（「伟大的伟，明天的明」，#158）整段一并给出（含被解释的字），见 explain_units。
    拆字说法以外单独出现的名（「三丰」）不在这里处理。"""
    s = str(text or "")
    R = _split_rules()
    if not R:
        return []
    ents = [e for e in (entities or []) if isinstance(e.get("start"), int)]
    claimed = [(e["start"], e["end"]) for e in ents if e.get("sensitive") is not False]
    names = [str(e.get("value") or "") for e in ents if e.get("type") == "name" and len(str(e.get("value") or "")) >= 2]
    sp = R["sp"]
    # 逐字解释（#158）：拆字报姓后紧跟逐字解释时不再往后数字打码，整段解释由下面统一打码
    units = explain_units(s, ents)
    out: List[dict] = []
    # #202：首字是真姓的同音写法当拆字报姓用时（后面紧跟逐字解释，或提示词后 patterns.name 跳过它取到了紧跟的「张伟」），
    # 写法本身按姓名打码（「宫长张」→「宫**」），先占位，后面紧贴的解释段按 joiner 隔开。与 redact.js 一致
    used = [a for a, _b, _sur in split_hits(s, units)]
    for m0 in R["asr"].finditer(s):
        if any(e.get("type") == "name" and e["start"] == m0.end() - 1 for e in ents):
            used.append(m0.start())
    for a in used:
        key = next((k for k in R["asrReal"] if s.startswith(k, a)), None)
        if not key:
            continue
        b = a + len(key)
        if any(x < b and a + 1 < y for x, y in claimed):
            continue
        claimed.append((a + 1, b))
        out.append({"start": a + 1, "end": b, "masked": _stars(len(key) - 1)})
    for _a, m_end, sur in split_hits(s, units):
        sm0 = R["sep"].match(s[m_end:])  # 复审建议：判空
        pos = m_end + (sm0.end() if sm0 else 0)
        if any(u["start"] <= pos < u["end"] for u in units):
            continue
        given = next((n[1:] for n in names if n[0] == sur and s.startswith(n[1:], pos)), "")
        # #250：拆字报姓后紧跟数字或中文金额（「木子李一千元」「弓长张五百块」）时后面不是名，按 sayEnd 判断；与 redact.js 一致
        Q = _say_rules()
        if not given and Q and Q["end"].match(s[pos:]):
            # #249：「弓长张三五百块」——后面整体是金额，但退一个字（「三」）后剩下的仍是金额时，「三」按名打码（偏安全，记 #216）
            g1 = _num_given(R, Q, s, pos, units)
            if len(g1) != 1 or _num_whitelisted(R, s, m_end - 1, pos + 1) or any(pos < b and pos + 1 > a for a, b in claimed):
                continue
            claimed.append((pos, pos + 1))
            out.append({"start": pos, "end": pos + 1, "masked": _stars(1)})
            continue
        if not given:
            while len(given) < int(sp.get("givenMax", 2)) and pos + len(given) < len(s) \
                    and not R["stop"].match(s[pos + len(given)]) \
                    and not any(u["start"] == pos + len(given) for u in units) \
                    and not (given and Q and Q["end"].match(s[pos + len(given):])):  # #250「弓长张伟三万」：名后接金额就停
                given += s[pos + len(given)]
            if given and R["notNames"] and R["notNames"].search(given):
                given = ""
        end = pos + len(given)
        if given and _num_whitelisted(R, s, m_end - 1, end):
            continue  # #249：「立早章程第3条」「木子李子5斤」：拆字说法 + 名正好是普通词，放行（不看后面，语音出口先换数字再打码也一致）
        if not given or any(a < end and pos < b for a, b in claimed):
            continue
        claimed.append((pos, end))
        out.append({"start": pos, "end": end, "masked": _stars(len(given))})
    # #249 负责人规则：同音 / ASR 听错的拆字写法（「工厂张」「尔东陈」，homophones 逐字变体，含 asrSplit）后面直接跟 1–2 个字的名
    # （连姓 2–3 个汉字）再跟数字或中文金额时，名按姓名打码；普通词按 numWhitelist 放行。与 redact.js 一致
    Q = _say_rules()
    hits = split_hits(s, units)
    for m in (Q["variant"].finditer(s) if Q else ()):
        a0, b0 = m.start(), m.end()
        if any(x < b0 and a0 < y for x, y, _ in hits):
            continue
        sm0 = R["sep"].match(s[b0:])
        pos = b0 + (sm0.end() if sm0 else 0)
        if any(u["start"] <= pos < u["end"] for u in units):
            continue
        given = _num_given(R, Q, s, pos, units)
        end = pos + len(given)
        if not given or _num_whitelisted(R, s, b0 - 1, end) or (R["notNames"] and R["notNames"].search(given)):
            continue
        i = pos
        while i < end:  # 提示词后提取器已取到一部分（「收款人尔东陈伟明500」取了「尔东陈伟」）时只补没盖住的字
            if any(x <= i < y for x, y in claimed):
                i += 1
                continue
            j = i
            while j < end and not any(x <= j < y for x, y in claimed):
                j += 1
            claimed.append((i, j))
            out.append({"start": i, "end": j, "masked": _stars(j - i)})
            i = j
    # #163：一串解释前面（隔 sep）紧挨着 2–3 个汉字、以姓开头、名里含被解释的字（「张伟晨，伟大的伟」）时，按姓名打码；与 redact.js 一致
    ER = _explain_rules()
    for u in units:
        if not ER or not ER["ex"].get("standalone") or "head" not in u:
            continue
        p = u["head"]
        while p > 0 and ER["sep"].match(s[p - 1:u["head"]]):
            p -= 1
        for L in (3, 2):
            a = p - L
            if a < 0:
                continue
            cand = s[a:p]
            if not all(ER["han"].match(c) for c in cand) or cand[0] not in ER["surnames"]:
                continue
            if not any(x in cand[1:] for x in u["xs"]):
                continue
            if any(c0 < p and a + 1 < c1 for c0, c1 in claimed):
                break
            claimed.append((a + 1, p))
            out.append({"start": a + 1, "end": p, "masked": _stars(L - 1), "kind": "nameBefore"})
            break
    joiner = ((_explain_rules() or {}).get("ex") or {}).get("joiner") or ""
    for u in units:
        if u["keep"] or any(a < u["end"] and u["start"] < b for a, b in claimed):
            continue
        glue = joiner if any(b == u["start"] for _, b in claimed) else ""
        claimed.append((u["start"], u["end"]))
        sp = {"start": u["start"], "end": u["end"], "masked": glue + _stars(u["end"] - u["start"])}
        if u.get("rad"):
            sp["kind"] = "radical"  # #163：语音出口（persona.drop_name_explain）按 kind 换成「那个名字」
        out.append(sp)
    out.sort(key=lambda e: e["start"])
    return out


# ---- #163 复审：文字出口（refs.mask_names / llm.js maskNames）把拆字报姓、逐字解释、偏旁说法连同前面的姓名整体读成「那个名字」，
# 与语音出口 voice/persona.drop_name_explain 对齐。与 redact.js nameSayRegions 一致 ----
@functools.lru_cache(maxsize=None)
def _say_rules():
    R, E = _split_rules(), _explain_rules()
    if not R or not E:
        return None
    hom = R["sp"].get("homophones") or {}
    cls = lambda c: "[" + c + hom.get(c, "") + "]"
    return {
        "variant": compile_js("(" + "|".join("".join(cls(c) for c in x) for x in sorted(R["sp"]["spellings"], key=len, reverse=True)) + ")"),
        "sepc": re.compile(r"[\s，,、：:；;。]"),
        "absorbLead": re.compile(r"[叫是姓名人：:\s，,。、]"),
        "run": re.compile(r"^[\s，,、：:；;。]{0,2}(?:就是|是)?$"),
        "end": compile_js("^(?:" + (R["sp"].get("sayEnd") or "(?!)") + ")"),
        "surnames": (load("extractors").get("nameRules") or {}).get("surnames") or "",
    }


def name_say_regions(text: Optional[str], entities: Optional[Iterable[dict]] = None) -> List[List[int]]:
    """文字出口要整体读成「那个名字」的区间 [[start, end], ...]（已合并、按 start 排）。entities：extract_sensitive 的结果。"""
    s = str(text or "")
    R, E, Q = _split_rules(), _explain_rules(), _say_rules()
    if not R or not E or not Q:
        return []
    ents = [e for e in (entities or []) if isinstance(e.get("start"), int)]
    units = explain_units(s, ents)
    spans = find_name_spans(s, ents)
    regs = [[u["start"], u["end"]] for u in units]
    regs += [[sp["start"] - 1, sp["end"]] for sp in spans if sp.get("kind") == "nameBefore"]
    han = lambda c: bool(c) and bool(E["han"].match(c))

    def end_ok(pos):
        if pos >= len(s) or not han(s[pos]) or E["particle"].match(s[pos]) or E["tailWords"].match(s, pos) or Q["end"].match(s[pos:]):
            return True
        # #259：explain_units 只给一条链的第一个 unit 写 head，与 :711 一样先判断
        return any("head" in u and u["head"] >= pos and E["sep"].match(s[pos:u["head"]]) for u in units)

    names_early = [e for e in ents if e.get("type") == "name" and e.get("value")]
    hits = [[m.start(), m.end()] for m in Q["variant"].finditer(s)] + [[a, b] for a, b, _ in split_hits(s, units)]
    for a, b in hits:
        split_end = b
        sm = R["sep"].match(s[b:])  # 复审建议：sep 匹配不上时不抛错
        pos = b + (sm.end() if sm else 0)
        absorbed = False
        for sp in spans:
            # #259 复审：紧跟的是逐字解释（explain unit）而不是名时不往后延，否则 end_ok 落在解释链中间判不过、拆字姓漏打
            if not sp.get("kind") and sp["start"] == pos and re.fullmatch(r"\*+", sp["masked"]) \
                    and not any(u["start"] == sp["start"] for u in units):
                b = sp["end"]
                absorbed = True
        # #260：拆字报姓后紧跟已提取姓名（「弓长张三丰」里姓与名重叠在姓字上）时整段并入，避免留下「弓长张**」
        for e in names_early:
            if e["start"] == split_end - 1 or e["start"] == pos:
                b = max(b, e["end"])
                absorbed = True
        # #260：已打码文本（「弓长张**」「耳东陈，**」）把尾随星号并入，say_names 一次换成「那个名字」
        sm2 = R["sep"].match(s[b:])
        p2 = b + (sm2.end() if sm2 else 0)
        if p2 < len(s) and s[p2] in "*＊":
            while p2 < len(s) and s[p2] in "*＊":
                p2 += 1
            b = p2
            absorbed = True
        if not absorbed and not end_ok(b):
            continue
        if a > 0 and s[a - 1] == "姓":
            a -= 1
        regs.append([a, b])
    if not regs:
        return []
    names = [e for e in ents if e.get("type") == "name" and e.get("value")]
    for r in regs:
        for _ in range(4):
            q, k = r[0], 0
            while q > 0 and k < 2 and Q["sepc"].match(s[q - 1]):
                q, k = q - 1, k + 1
            e = next((n for n in names if n["end"] == q and n["start"] < q), None)
            if e:
                r[0] = e["start"]
                continue
            if q > 0 and s[q - 1] in Q["surnames"] and (q - 1 == 0 or Q["absorbLead"].match(s[q - 2])):
                r[0] = q - 1
                continue
            break
    regs.sort(key=lambda x: (x[0], -x[1]))
    out: List[List[int]] = []
    for r in regs:
        if out and (r[0] <= out[-1][1] or Q["run"].match(s[out[-1][1]:r[0]])):
            out[-1][1] = max(out[-1][1], r[1])
        else:
            out.append([r[0], r[1]])
    return out


def say_names(text: Optional[str], entities: Optional[Iterable[dict]] = None, phrase: str = "那个名字") -> str:
    """把 name_say_regions 的区间换成 phrase（默认「那个名字」）。"""
    s = str(text or "")
    for a, b in reversed(name_say_regions(s, entities)):
        s = s[:a] + phrase + s[b:]
    return s


def redact_text(text: Optional[str], entities: Optional[Iterable[dict]]) -> str:
    """把文本中的敏感片段替换成脱敏结果（entities 来自 extract()）；
    拆字报姓后的名与逐字解释一并打码（#139 / #158，find_name_spans）；
    另外按上下文给验证码类短数字打码（与实体重叠的交给实体自己的规则）。"""
    s = str(text or "")
    ents = [e for e in (entities or []) if isinstance(e.get("start"), int)]
    lst = [{"start": e["start"], "end": e["end"], "masked": e.get("masked") or mask(e["type"], e["value"])}
           for e in ents if e.get("sensitive") is not False]
    names = find_name_spans(s, ents)
    lst += names
    ents = ents + [dict(n, sensitive=True) for n in names]
    for p in find_otp_spans(s):
        if not any(e["start"] < p["end"] and p["start"] < e["end"] for e in ents):
            lst.append(p)
    if not lst:
        return s
    lst.sort(key=lambda e: e["start"], reverse=True)
    for e in lst:
        s = s[: e["start"]] + e["masked"] + s[e["end"]:]
    return s
