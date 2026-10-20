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
# #185 应答字、虚词共用字表（core/name_stopchars.json）：取到的名字以这些字开头时不算（「户名对得上就行」）
# surname=false 的字一律不当名字开头；surname=true 的字可能是真姓，只有后面紧跟的文字匹配 after 时才放行，拿不准就照常当姓名
NAME_STOPCHARS = {r["char"]: (compile_js("^(?:" + r["after"] + ")") if r.get("surname") else None)
                  for r in load("name_stopchars")["chars"]}
NAME_STOPWORDS = tuple(r["word"] for r in load("name_stopchars").get("words", []))


def _stop_name(n: str, m=None, start: Optional[int] = None) -> bool:
    """名字以字表里的字（或多字词）开头、而且按上下文不是名字时返回 True。"""
    if n.startswith(NAME_STOPWORDS):
        return True
    c = n[:1]
    if c not in NAME_STOPCHARS:
        return False
    after = NAME_STOPCHARS[c]
    if after is None:
        return True
    rest = m.string[start + 1:] if m is not None and start is not None else n[1:]
    return bool(after.match(rest))


def stop_surname(c: str, rest: str = "") -> Optional[bool]:
    """#201 人设侧共用（refs.mask_names、engine.vague_digits、voice unmask）：打码姓名「c**」里星号前那个字 c 在共用字表里时，
    按字表判断它在 rest（c 后面的文字，从星号起）前面算不算「不当姓」：surname=false → True；surname=true → rest 匹配 after
    才 True，否则 False（拿不准就当姓名，照样换成「那个名字」）。c 不在字表里返回 None，由调用方按自己的 notSurname 判断。
    与 extractors.js 的 stopSurname 一致。"""
    if c not in NAME_STOPCHARS:
        return None
    after = NAME_STOPCHARS[c]
    return True if after is None else bool(after.match(rest or ""))


def masked_lead_not_surname(m, sur: str, fallback: str) -> bool:
    """#201：打码姓名正则（_NAME_MASK 一类，星号紧跟在姓 sur 后面）匹配到 m 时，sur 是不是「不当姓」。复姓一律算姓；
    单字先查共用字表（stop_surname），不在表里的再看 fallback（personas.json 的 notSurname 等）。
    拿不准就当姓名：可能是真姓的字（surname=true）后面只跟 1–3 个星号时，正好是脱敏后的 2–4 字姓名（「户名有志强」→「户名有**」），
    不放行；4 个及以上星号（「我只有****块钱」）才按字表的 after 放行。"""
    if len(sur) != 1:
        return False
    if re.search("[*＊][\u4e00-\u9fff]", m.group(0)):  # #206 星号后面还跟着一个字（「对*明」「王*明」「转到*明」「卡号是*华」）：一律当姓名（宁可多遮），先于号码语境
        return False
    star0 = re.search("[*＊]", m.group(0))
    if stars_not_name(m.string, m.start() + (star0.start() if star0 else 0)):  # #206 第六条探针：号码语境 / 「我在***上班」不当姓名，先于 _SHORT_STARS 兜底
        return True
    star = re.search("[*＊]", m.group(0))
    rest = m.string[m.start() + (star.start() if star else len(m.group(0))):]
    st = stop_surname(sur, rest)
    if st is None:
        return sur in fallback
    if st and NAME_STOPCHARS[sur] is not None and _SHORT_STARS.match(rest):
        return False
    return st


_SHORT_STARS = re.compile("[*＊]{1,3}(?![*＊])")
_MC = load("name_stopchars").get("maskContext") or {}
_NUMBER_BEFORE = compile_js(_MC.get("numberBefore") or "(?!)")
_NOT_NAME_AFTER = compile_js(_MC.get("notNameAfter") or "(?!)")
_NOT_NAME_AFTER_VERB = compile_js(_MC.get("notNameAfterVerbBefore") or "(?!)")
_NAME_AFTER = compile_js(_MC.get("nameAfter") or "(?!)")
_NAME_BEFORE = compile_js(_MC.get("nameBefore") or "(?!)")


def stars_name(s: str, pos: int) -> bool:
    """#214 审查：s 里 pos 处开始的星号前面是「户名、收款人、名下、对方叫」或后面跟「名下、的卡、的账户」等，是姓名。与 JS starsName 一致。"""
    s = str(s)
    return bool(_NAME_BEFORE.search(s[:pos]) or _NAME_AFTER.match(s, pos))


def stars_not_name(s: str, pos: int) -> bool:
    """#206 第六条探针：s 里 pos 处开始的星号按上下文不当姓名（号码语境「验证码是***」「转到**」，或「我在***上班」）。与 JS starsNotName 一致。"""
    s = str(s)
    if stars_name(s, pos):  # #214：「转到**名下」「打到**的卡上」仍是姓名
        return False
    return bool(_NUMBER_BEFORE.search(s[:pos]) or _not_name_after(s, pos))


def _not_name_after(s: str, pos: int) -> bool:
    """#221：「我在***上班」「我在*那边」——只在星号前是位置动词时生效；星号紧跟常见姓（「李*那边」）一律按姓名。与 JS notNameAfter 一致。"""
    if pos > 0 and s[pos - 1] in _SURNAMES:
        return False
    return bool(_NOT_NAME_AFTER.match(s, pos) and _NOT_NAME_AFTER_VERB.search(s[:pos]))




_NAME_DIGITS = "零一二三四五六七八九"
_SPLIT_SPELLINGS = frozenset((_C["nameRules"].get("split") or {}).get("spellings") or [])


def _clean_name(n: str, m=None, start: Optional[int] = None):
    # ASR 数字规整（ITN）会把“张三”转成“张3”：单个阿拉伯数字还原为汉字（等长，脱敏区间不变）
    n = re.sub(r"[0-9]", lambda m: _NAME_DIGITS[int(m.group(0))], n)
    if _NOT_NAMES.search(n) or _stop_name(n, m, start):
        return None
    if n in _SPLIT_SPELLINGS:  # #206「收款人是弓长张，伟大的伟」：拆字说法本身不是姓名（姓留给拆字报姓规则，只露姓）
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


# #222 P0：姓名语境里的真名（「转给李四」「是李四吗」「我叫张三」），规则见 core/extractors.json nameRules.nameContext。
# 与 extractors.js NAME_CONTEXT_RE / cleanNameContext / findNameContext 一致
_NC = _C["nameRules"]["nameContext"]
_NC_TITLES = tuple(sorted(set(_NC["titles"]) | set(_TITLES), key=len, reverse=True))
_NC_NAME = "((?:" + "|".join(_NC["compoundSurnames"]) + "|[" + _SURNAMES + "])(?:(?![" + _NC["givenStop"] + "])[\u4e00-\u9fa5]){1,2}?)"
_NC_TITLE_ALT = "|".join(re.escape(t) for t in _NC_TITLES)


def _nc_re(lead: str, tail: str) -> re.Pattern:
    return re.compile(lead + r"\s*[:：]?\s*(?!" + "|".join(_NC["notWords"]) + ")" + _NC_NAME + "(?=" + tail + ")")


def _leads(xs) -> str:
    return "(" + "|".join(sorted(xs, key=len, reverse=True)) + ")"


NAME_CONTEXT_RE = _nc_re(_leads(_NC["leads"]), _NC_TITLE_ALT + "|" + _NC["stops"])
# #222 后续：「张三是吧」——句首或非汉字后面的名字 + 是吧
NAME_SHIBA_RE = _nc_re("(^|[^\u4e00-\u9fa5])", _NC["shibaTail"])
# #220：「张三三点钟」——句首或非汉字后面的名字 + 中文钟点
NAME_TIME_RE = _nc_re("(^|[^\u4e00-\u9fa5])", _NC["timeTail"])
NAME_CONTEXT_RES = (NAME_CONTEXT_RE, NAME_SHIBA_RE, NAME_TIME_RE)
_NC_ASK_AMOUNT = re.compile("(?:" + _NC["askAmount"] + ")(?:" + _NC["askTail"] + "|[^\u4e00-\u9fa5]|$)")


def _clean_name_context(n: str, m=None, start: Optional[int] = None):
    """姓名语境里的名字：lead 为「是」时后面必须紧跟「吗」；后面紧跟称呼（「王阿姨」「王小姐」）不算；其余同 _clean_name。"""
    if m is None or start is None:
        return None
    rest = m.string[start + len(n):]
    lead = m.group(1)
    if lead in _NC["amountLeads"]:
        # #220：给 / 是 引导时，名字须后面紧跟金额、整词不是常见词（「给黄金三万」「给万一」不算）；「是 + 名字 + 吗」照旧
        ask = lead == _NC["askLead"] and rest.startswith(_NC["askTail"])
        if not ask and (not _NC_ASK_AMOUNT.match(rest) or n in _NC["amountLeadNotNames"]):
            return None
    after = m.string[start + 1:]
    if any(after.startswith(t) for t in _NC_TITLES) or rest.startswith(_NC_TITLES):
        return None
    c = _clean_name(n, m, start)
    return c if c == n else None


def find_name_context(text: Optional[str]) -> List[dict]:
    """#222：只跑姓名语境规则，返回 [{"value", "start", "end", "lead"}]（语音 IntelProcessor 复用）。"""
    s = str(text or "")
    out = []
    for rx in NAME_CONTEXT_RES:
        for m in rx.finditer(s):
            start = m.start(2)
            v = _clean_name_context(m.group(2), m, start)
            if v and not any(start < o["end"] and o["start"] < start + len(v) for o in out):
                out.append({"value": v, "start": start, "end": start + len(v), "lead": m.group(1)})
    return sorted(out, key=lambda o: o["start"])


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
    # 完整的 ETH / TRON 地址先认领：地址里常含 vx / VX 等字母组合，不能先被当成微信号截走（#8）
    scan(RE["eth"], "crypto_eth", meta=lambda *a: {"chain": "Ethereum/EVM"})
    scan(RE["tron"], "crypto_tron", meta=lambda *a: {"chain": "TRON"})
    scan(RE["alipay"], "alipay", group=1)
    scan(RE["qq"], "qq", group=1)
    scan(RE["wechat"], "wechat", group=1)
    scan(RE["email"], "email")
    scan(RE["urlBare"], "url", clean=_trim_url,
         meta=lambda raw, m, st: {"bare": True} if re.search(r"[a-z]", raw.split(".")[0], re.I) else False)
    scan(RE["btc"], "crypto_btc", meta=lambda *a: {"chain": "Bitcoin"})
    scan(RE["idCard"], "id_card", meta=id_meta)
    scan(RE["bankCard"], "bank_card", meta=card_meta)
    scan(RE["hotline"], "phone", meta=lambda *a: {"kind": "hotline"})
    def landline_meta(raw, m, start):
        # 不带横杠的座机（多由断续报号拼接而来）：前面紧挨订单号 / 工号 / 验证码等词时不算电话
        if "-" not in raw and _RE_BLOCK_BEFORE and _RE_BLOCK_BEFORE.search(_unblock_typos(s[max(0, start - 16):start])):
            return False
        return {"kind": "landline"}

    scan(RE["landline"], "phone", meta=landline_meta)
    scan(RE["mobile"], "phone", meta=lambda *a: {"kind": "mobile"})
    scan(RE["name"], "name", group=1, clean=_clean_name)
    scan(RE["nameMid"], "name", group=1, clean=_clean_name_mid)
    # #216 P0：人设回复「对方叫李四是吧」「他叫王志强」——人称 + 叫 后面的姓名（必须以常见姓氏开头，规则同 nameMid）
    scan(RE["namePerson"], "name", group=1, clean=_clean_name_mid)
    # #222 P0：「转给 / 打给 / 汇给 + 名字」「是 + 名字 + 吗」「我叫 / 我是 + 名字」
    for rx in NAME_CONTEXT_RES:  # #222 后续：名字 + 是吧
        scan(rx, "name", group=2, clean=_clean_name_context)

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
        # #220：规范化会把「张三1000」并成「张31000」，姓名语境再按原文跑一遍，没被占用的名字补上（与 extractors.js 一致）
        spans = [(e["start"], e["end"]) for e in out if e["sensitive"]]
        for h in find_name_context(raw_text):
            if not _overlaps(spans, h["start"], h["end"]):
                out.append({"type": "name", "label": LABELS.get("name", "name"), "value": h["value"],
                            "masked": R.mask("name", h["value"]), "start": h["start"], "end": h["end"],
                            "sensitive": True, "meta": {}})
                spans.append((h["start"], h["end"]))
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
_FRAG = "[0-9](?:" + _SEP_CLS + "{0,%d}[0-9])*" % _DJ["maxSep"]
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


# #8：钱包地址跨回合拼接（上一回合末尾 0x… / T… + 下一回合开头的十六进制 / Base58 片段）
_WST: dict = _ST.get("wallet") or {}
_B58C = "1-9A-HJ-NP-Za-km-z"
# 片段内部也可以带停顿分段（“0x2bc，9fff9efd…”“然后…sNoN，aNDswW，L63c”），每处分隔至多 maxSep 个
_WCHUNKS = "[0-9A-Za-z]+(?:" + _SEP_CLS + "{1,%d}[0-9A-Za-z]+)*" % _DJ["maxSep"]
_RE_WTAIL = re.compile("(?<![0-9A-Za-z])((?:0x|T)" + _WCHUNKS + ")(" + re.sub(r"\$$", "", _ST.get("tailFiller", "$")) + ")$") if _WST else None
_RE_WHEAD = re.compile("(" + re.sub(r"^\^", "", _ST.get("headFiller", "^")) + ")(" + _WCHUNKS + ")(?![0-9A-Za-z])") if _WST else None
_RE_ALNUM = re.compile("[0-9A-Za-z]+")
_RE_PAUSE_END = re.compile(r"^[\s，,、]*(?:…|⋯|\.{2,})")
_RE_W_CTX = re.compile(_WST["context"]) if _WST.get("context") else None
_RE_HEX_ONLY = re.compile("[0-9a-fA-F]+")
_RE_B58_ONLY = re.compile("[" + _B58C + "]+")
_WALLET_TYPES = ("crypto_eth", "crypto_tron", "crypto_btc")

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

    def weak_card(a, b, pause_after=False):
        """#1：片段被单回合提取认成了银行卡、但只是 16–18 位且不过 Luhn（多半是拆开的长卡号的一段）：
        允许它参与拼接，拼接结果过 Luhn 时取代这条单段结果（stitch 输出里的 supersedes）。
        #8：断续报卡号时，后半段（“1776…1855…023”“1567…5024…481”）可能整段或部分被认成手机号 / 座机，同样处理（拼接时还要求有卡号上下文）；
        回合以停顿（…）收尾的 16–18 位卡号即使过 Luhn 也允许接上下一回合开头的 1–3 位，拼成 19 位且过 Luhn 时取代（weakLuhn）。"""
        sa, sb = norm.span(a, b)
        hit = [e for e in ents if e["start"] < sb and e["end"] > sa]
        if len(hit) != 1 or hit[0]["type"] not in ("bank_card", "phone"):
            return None
        d = re.sub(r"[^0-9]", "", s[a:b])
        e = hit[0]
        v = re.sub(r"[^0-9]", "", str(e["value"]))
        if e["type"] == "phone":
            # 片段只有一部分是手机号，或整段被拼成了不带横杠的座机 / 热线（“0750…8275…730”）
            joined = v == d and "-" not in str(e["value"]) and "." not in str(e["value"]) and " " not in str(e["value"])
            return e if (len(v) < len(d) and v in d) or joined else None
        if v != d or len(d) > 18 or (luhn(d) and not pause_after):
            return None
        return dict(e, weakLuhn=True) if luhn(d) else e

    def mk(a, b, **extra):
        sa, sb = norm.span(a, b)
        o = {"start": sa, "end": sb, "digits": re.sub(r"[^0-9]", "", s[a:b]), "ns": a, "ne": b}
        o.update(extra)
        return o

    out = {"text": s, "ents": ents, "head": None, "tail": None}
    t = _RE_TAIL.search(s)
    if t:
        a, b = t.start(), t.start() + len(t.group(1))
        wk = None if free(a, b) else weak_card(a, b, pause_after=bool(_RE_PAUSE_END.match(s[b:])))
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
    out["wtail"] = out["whead"] = None
    if _RE_WTAIL:

        def chunks(a, b):
            """片段里的字母数字段（原文坐标），拼接时按需要的长度取前缀 / 全部。"""
            return [(norm.span(a + m.start(), a + m.end()), m.group(0)) for m in _RE_ALNUM.finditer(s[a:b])]
        w = _RE_WTAIL.search(s)
        if w:
            a = w.start(1)
            ctx = s[max(0, a - _WST.get("contextChars", 24)):a]
            if _RE_W_CTX is None or _RE_W_CTX.search(ctx):
                out["wtail"] = chunks(a, w.end(1))
        h = _RE_WHEAD.match(s)
        if h:
            out["whead"] = chunks(h.start(2), h.end(2))
    return out


def _score(d: str, ctx: str) -> Optional[dict]:
    kind = _plausible(d)
    if not kind:
        return None
    if kind == "phone":
        return {"type": "phone", "conf": _round2(0.6 + (0.3 if _RE_PHONE_CTX.search(ctx) else 0)), "meta": {"kind": "mobile"}}
    if kind in ("landline", "hotline"):
        return {"type": "phone", "conf": _round2(0.3 + (0.3 if _RE_PHONE_CTX.search(ctx) else 0)), "meta": {"kind": kind}}
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
            weak = [p[1]["weak"] for p in parts if p[1].get("weak")]
            if sc and weak and not (sc["type"] == "bank_card" and sc["meta"]["luhn"]
                                    and (not any(w["type"] == "phone" for w in weak)
                                         or _RE_BANK_CTX.search(tail["before"] + F[i]["text"][tail["ns"]:tail["ne"]]))
                                    and (not any(w.get("weakLuhn") for w in weak) or len(d) == 19)):
                sc = None  # 含被单回合认成卡号 / 手机号的片段：拼接结果必须是过 Luhn 的银行卡才取代它（手机号段另需卡号上下文，过 Luhn 的段须拼成 19 位）
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
    out += _stitch_wallets(F, seen)
    return out


def _wallet_part(chunks, ents, take=None):
    """取片段的全部（take=None）或前若干个字符段，凑满 take 个字符；返回 (文本, 原文起止, 被取代的非钱包情报) 或 None。"""
    used, n = [], 0
    for sp, txt in chunks:
        if take is not None and n >= take:
            break
        used.append((sp, txt))
        n += len(txt)
    if not used or (take is not None and n != take):
        return None
    sa, sb = used[0][0][0], used[-1][0][1]
    hit = [e for e in ents if e["start"] < sb and e["end"] > sa]
    if any(e["type"] in _WALLET_TYPES or e["start"] < sa or e["end"] > sb for e in hit):
        return None  # 已是完整钱包地址，或与片段外的情报重叠
    return "".join(x for _, x in used), sa, sb, hit


def _stitch_wallets(F, seen) -> List[dict]:
    """#8：钱包地址拆进相邻两个回合（每段内部也可带停顿）。上一回合末尾片段 + 下一回合开头片段合计正好 0x+40 / T+33、
    字符集吻合、上一回合片段前有钱包上下文词才输出；被单回合误认成微信号等的部分由拼接结果取代（supersedes）。"""
    out = []
    for i in range(len(F) - 1):
        tc, hc = F[i].get("wtail"), F[i + 1].get("whead")
        if not tc or not hc:
            continue
        tp = _wallet_part(tc, F[i]["ents"])
        if not tp or len(tp[0]) < _WST.get("minTail", 4):
            continue
        eth = tp[0].startswith("0x")
        need = (42 if eth else 34) - len(tp[0])
        if need < _WST.get("minHead", 3):
            continue
        hp = _wallet_part(hc, F[i + 1]["ents"], need)
        if not hp:
            continue
        v = tp[0] + hp[0]
        type_ = "crypto_eth" if eth else "crypto_tron"
        if not (_RE_HEX_ONLY.fullmatch(v[2:]) if eth else _RE_B58_ONLY.fullmatch(v)):
            continue
        key = type_ + "|" + v.lower()
        if key in seen:
            continue
        seen.add(key)
        masked = R.mask(type_, v)
        same = len(masked) == len(v)
        n0 = len(tp[0])
        parts = [{"turn": i, "start": tp[1], "end": tp[2], "masked": masked[:n0] if same else "*" * n0},
                 {"turn": i + 1, "start": hp[1], "end": hp[2], "masked": masked[n0:] if same else "*" * len(hp[0])}]
        o = {"type": type_, "label": LABELS.get(type_, type_), "value": v, "masked": masked, "sensitive": True,
             "confidence": 0.9, "turns": [i, i + 1], "parts": parts,
             "meta": {"chain": "Ethereum/EVM" if eth else "TRON", "stitched": True}}
        sup = [{"turn": turn, "type": e["type"], "value": e["value"], "start": e["start"], "end": e["end"]}
               for turn, part in ((i, tp), (i + 1, hp)) for e in part[3]]
        if sup:
            o["supersedes"] = sup
        out.append(o)
    return out
