"""GitHub 情报提交自动化（IssueOps）的核心逻辑，可在本地测试，不依赖网络（黑名单比对可注入）。

流程：解析 issue 表单 → 按发布策略脱敏（deepsuck.redact）→ 与 intel.json 去重 → 公开黑名单比对（deepsuck.blocklist）
→ 生成更新后的 intel.json / intel.stix.json / intel.csv / intel.rss，以及 PR 说明与 issue 评论（只含脱敏后的公开值）。

安全约定：
- issue 正文只从事件文件（GITHUB_EVENT_PATH）读入，不经过 shell；本模块不打印原文，也不把原文写进任何输出。
- 打码类（银行卡、姓名、账号）的原文只在内存里用于打码；所有输出在写盘前做一次泄露检查，检查失败则不生成 PR。
- 写入 GITHUB_OUTPUT 的只有固定取值（true/false）。

CLI（工作流里使用）：
  python -m deepsuck.intake process --event "$GITHUB_EVENT_PATH" --repo . --out "$RUNNER_TEMP/intake"
本地试跑（不联网）：
  python -m deepsuck.intake process --event event.json --repo .. --out /tmp/intake --offline
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import cardbin, feeds, stix
from .blocklist import host_of, wallet_key
from .core import load
from .extractors import extract, extract_sensitive
from .redact import (format_card_groups, mask, mask_bank_card, mask_handle, mask_name,  # noqa: F401
                     redact_text)

MARKER = "<!-- deepsuck-intel-intake -->"
LABEL = "intel-submission"
MAX_VALUES = 10
MAX_VALUE_LEN = 300
MAX_TEXT_LEN = 300
BANK_CARD_MASKED = feeds.BANK_CARD_MASKED

TYPE_BY_LABEL = {
    "诈骗电话": "phone", "加密钱包地址": "crypto_wallet", "诈骗网址/域名": "url", "APP/平台名称": "app",
    "收款银行卡": "bank_card", "支付宝/微信/QQ 等账号": "account", "收款户名/姓名": "name", "话术/手法": "script",
    "身份证号": "id_card",
}
LABEL_BY_TYPE = feeds.LABELS
MASKED_TYPES = feeds.MASKED_TYPES
SCENARIO_BY_LABEL = {
    "冒充客服 · 退款理赔": "refund", "冒充公检法 · 安全账户": "police", "杀猪盘 · 投资/感情": "pig",
    "刷单返利 · 做任务赚佣金": "task", "虚假贷款 · 征信修复": "loan", "冒充领导/熟人 · 借钱转账": "boss",
    "注销校园贷 · 清空网贷额度": "campus",
}
SOURCE_BY_LABEL = {"本人遇到": "community", "沙盒拖住": "sandbox", "蜜罐": "honeypot", "公开报道": "public-report"}
PLATFORM_TYPE = {"支付宝": "alipay", "微信": "wechat", "QQ": "qq", "邮箱": "email", "其他": "wechat"}
CHAIN_OF = {"crypto_tron": "TRON", "crypto_eth": "Ethereum/EVM", "crypto_btc": "Bitcoin"}

# 表单字段：(id, 标题, 类型)。必须与 .github/ISSUE_TEMPLATE/*.yml 一致（tests/test_intake.py 会核对）。
FORMS: Dict[str, List[Tuple[str, str, str]]] = {
    "intel-intake.yml": [
        ("type", "情报类型", "dropdown"), ("value", "值", "textarea"),
        ("platform", "账号所属平台（仅账号类型需要）", "dropdown"), ("bank", "开户行 / 所在链（可选）", "input"),
        ("script", "话术片段（可选）", "textarea"), ("source", "来源", "dropdown"), ("scenario", "诈骗场景", "dropdown"),
        ("tactics", "话术标签（可选）", "input"), ("first_seen", "遇到的时间", "input"),
        ("channel", "对方联系你的渠道", "dropdown"), ("notes", "补充说明（可选）", "textarea"),
        ("confirm", "提交确认", "checkboxes"),
    ],
    "intel-submission.yml": [
        ("scenario", "诈骗场景", "dropdown"), ("indicators", "情报指标（按发布策略处理后）", "textarea"),
        ("tactics", "话术标签（可选）", "input"), ("first_seen", "遇到的时间（大致即可）", "input"),
        ("channel", "对方联系你的渠道", "dropdown"), ("script", "话术摘录（已脱敏，可选）", "textarea"),
        ("notes", "补充说明（可选）", "textarea"), ("confirm", "提交确认", "checkboxes"),
    ],
}


class IntakeError(ValueError):
    pass


# ---------------------------------------------------------------- 表单解析
def detect_template(body: Optional[str]) -> Optional[str]:
    heads = set(_sections(body or "").keys())
    for name, fields in FORMS.items():
        required = {f[1] for f in fields if f[2] != "checkboxes"} - {f[1] for f in fields if "可选" in f[1] or "仅" in f[1]}
        if required and required <= heads:
            return name
    return None


def _sections(body: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    cur = None
    buf: List[str] = []
    for line in str(body).replace("\r\n", "\n").split("\n"):
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if cur is not None:
                out.setdefault(cur, "\n".join(buf).strip())
            cur, buf = m.group(1), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.setdefault(cur, "\n".join(buf).strip())
    return out


def _strip_fence(s: str) -> str:
    """render: text 的字段会被包进 ``` 代码块。"""
    m = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n?```", s.strip(), re.S)
    return m.group(1) if m else s


def parse_form(body: Optional[str], template: str) -> dict:
    """把 issue 表单正文解析成 {id: 值}；与 issue-ops/parser（带模板时）的输出形状一致：
    input/textarea -> str（未填为 ""），dropdown -> list[str]，checkboxes -> {"selected": [...], "unselected": [...]}。"""
    secs = _sections(body or "")
    out: dict = {}
    for fid, label, kind in FORMS[template]:
        raw = secs.get(label, "")
        if raw.strip() == "_No response_":
            raw = ""
        if kind == "dropdown":
            out[fid] = [x.strip() for x in raw.split(", ") if x.strip()] if raw else []
        elif kind == "checkboxes":
            sel, unsel = [], []
            for line in raw.split("\n"):
                m = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", line)
                if m:
                    (sel if m.group(1).lower() == "x" else unsel).append(m.group(2).strip())
            out[fid] = {"selected": sel, "unselected": unsel}
        else:
            out[fid] = _strip_fence(raw).strip()
    return out


# ---------------------------------------------------------------- 单值规范化 + 脱敏
def _clean_line(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]", "", s)  # 零宽/双向控制字符
    s = re.sub(r"^\s*(?:[-*•]|\d+[.、)])\s+", "", s).strip()
    if len(s) >= 2 and s[0] == s[-1] == "`":
        s = s[1:-1].strip()
    return s


def _digits(s: str) -> str:
    return re.sub(r"[^0-9]", "", s)


def issuer_of_masked(masked: str) -> Optional[dict]:
    """PCI 打码值只有前 6 位与总长度：按前缀（≤6 位）和长度查 BIN 表。"""
    m = re.match(r"^([0-9]{6})\*+[0-9]{4}$", masked)
    if not m:
        return None
    length = len(masked)
    fallback = None
    for n in range(6, 2, -1):
        opts = cardbin.BINS.get(m.group(1)[:n])
        if not opts:
            continue
        for o in opts:
            if o[2] == length:
                return cardbin._info(m.group(1)[:n], o, length)
        if fallback is None:
            fallback = cardbin._info(m.group(1)[:n], opts[0], length)
    return fallback


def normalize_value(type_: str, raw: str, platform: Optional[str] = None) -> dict:
    """-> {ok, value(公开值), key(去重键), extra{}, reason, raw_sensitive(原文含未打码的敏感信息)}。不返回原文。"""
    s = _clean_line(raw)
    if not s:
        return {"ok": False, "reason": "空值"}
    if len(s) > MAX_VALUE_LEN:
        return {"ok": False, "reason": f"超过 {MAX_VALUE_LEN} 字"}
    if type_ == "phone":
        d = _digits(s)
        if len(d) == 13 and d.startswith("86"):
            d = d[2:]
        if not (5 <= len(d) <= 12) or re.search(r"[A-Za-z]", s):
            return {"ok": False, "reason": "不像电话号码"}
        return {"ok": True, "value": d, "key": d, "extra": {}}
    if type_ == "crypto_wallet":
        cand = [e for e in extract(s) if e["type"] in CHAIN_OF and e["value"] == s]
        if not cand:
            return {"ok": False, "reason": "不像 TRON / EVM / BTC 地址"}
        return {"ok": True, "value": s, "key": wallet_key(s), "extra": {"chain": CHAIN_OF[cand[0]["type"]]},
                "check": cand[0]["type"]}
    if type_ == "url":
        u = re.sub(r"^hxxp", "http", s, flags=re.I).replace("[.]", ".").replace("(.)", ".")
        u = re.sub(r"[.,;:!?'\"）)\]。，；！？、]+$", "", u)
        host = host_of(u)
        if not host or re.search(r"\s", u):
            return {"ok": False, "reason": "不像网址或域名"}
        if u.startswith("//"):
            u = u[2:]
        key = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u.lower()).rstrip("/")
        return {"ok": True, "value": u, "key": key, "extra": {}, "check": "url"}
    if type_ in ("app", "script"):
        ents = extract_sensitive(s)
        v = redact_text(s, ents)
        limit = 60 if type_ == "app" else MAX_TEXT_LEN
        if len(v) > limit:
            v = v[:limit] + "…"
        if type_ == "script" and not (v.startswith('"') and v.endswith('"')):
            v = '"' + v.strip('"“”') + '"'
        return {"ok": True, "value": v, "key": re.sub(r"\s+", "", v.strip('"“”')).lower(), "extra": {},
                "raw_sensitive": bool(ents)}
    if type_ == "bank_card":
        compact = re.sub(r"[\s-]", "", s)
        if "*" in compact:
            if BANK_CARD_MASKED.match(compact):
                v = compact
            elif re.fullmatch(r"[0-9]{4}\*+[0-9]{4}", compact):
                return {"ok": False, "reason": "旧的“前 4 后 4”格式无法推断 BIN，请改为前 6 后 4（如 622202*********3445）"}
            else:
                return {"ok": False, "reason": "银行卡打码格式不符合 PCI（前 6 后 4）"}
            raw_sensitive = False
        else:
            d = _digits(compact)
            if not (8 <= len(d) <= 19) or len(d) != len(compact):
                return {"ok": False, "reason": "不像银行卡号"}
            v = mask_bank_card(d)
            raw_sensitive = True
        extra = {}
        info = issuer_of_masked(v)
        if info:
            extra = {"issuer": info["bank"], "cardType": info["cardTypeName"]}
        return {"ok": True, "value": v, "key": v, "extra": extra, "raw_sensitive": raw_sensitive}
    if type_ == "name":
        if "*" in s:
            if s.startswith("*") or re.search(r"[0-9]", s) or len(s) > 12:
                return {"ok": False, "reason": "姓名打码格式应为 王**"}
            return {"ok": True, "value": s, "key": s, "extra": {}}
        if len(s) > 12 or re.search(r"[0-9@]", s):
            return {"ok": False, "reason": "不像姓名"}
        return {"ok": True, "value": mask_name(s), "key": mask_name(s), "extra": {}, "raw_sensitive": True}
    if type_ == "account":
        if "*" in s:
            if re.search(r"[0-9]{7,}", s) or s.count("*") < 2:
                return {"ok": False, "reason": "账号打码不足"}
            return {"ok": True, "value": s, "key": s, "extra": {}}
        v = mask(PLATFORM_TYPE.get(platform or "", "wechat"), s)
        return {"ok": True, "value": v, "key": v, "extra": {}, "raw_sensitive": True}
    if type_ == "id_card":
        return {"ok": False, "reason": "身份证号常属于被冒用的普通人，不接受自动收录，请联系维护者"}
    return {"ok": False, "reason": "未知类型"}


# ---------------------------------------------------------------- 表单 -> 提交
_INDICATOR_LINE = re.compile(r"^\s*[-*]\s*(?P<label>[^：:`]+?)\s*[：:]\s*`(?P<value>[^`]+)`(?P<rest>.*)$")


def _paren(rest: str) -> List[str]:
    return [x.strip() for x in re.findall(r"（([^（）]+)）", rest or "")]


def submission_from_form(form: dict, template: str) -> dict:
    """-> {items:[{type, raw, bank, chain}], scenario, source, tactics, firstSeen(raw), channel, script, notes, confirmed, errors}"""
    errors: List[str] = []
    items: List[dict] = []
    if template == "intel-intake.yml":
        tlabel = (form.get("type") or [""])[0]
        t = TYPE_BY_LABEL.get(tlabel)
        if not t:
            errors.append("未选择情报类型")
        lines = [x for x in str(form.get("value") or "").split("\n") if x.strip()]
        if t == "script" and not lines and form.get("script"):
            lines = [form["script"]]
        for x in lines:
            items.append({"type": t, "raw": x, "bank": form.get("bank") or "", "platform": (form.get("platform") or [""])[0]})
        source = SOURCE_BY_LABEL.get((form.get("source") or [""])[0], "community")
        script = form.get("script") if t != "script" else ""
    else:
        for line in str(form.get("indicators") or "").split("\n"):
            if not line.strip():
                continue
            m = _INDICATOR_LINE.match(line)
            if not m:
                errors.append("有一行情报指标无法识别（应为 `- 类型：`值``）")
                continue
            t = TYPE_BY_LABEL.get(m.group("label").strip())
            if not t:
                errors.append(f"未知情报类型：{_md_text(m.group('label').strip()[:20])}")
                continue
            ps = _paren(m.group("rest"))
            item = {"type": t, "raw": m.group("value"), "bank": "", "platform": ""}
            if t == "bank_card" and ps and not ps[0].startswith("BIN"):
                item["bank"] = ps[0]
            if t == "crypto_wallet" and ps:
                item["bank"] = ps[0]
            items.append(item)
        source = "community"
        script = form.get("script") or ""
    if len(items) > MAX_VALUES:
        errors.append(f"一次最多 {MAX_VALUES} 条，只处理前 {MAX_VALUES} 条")
        items = items[:MAX_VALUES]
    conf = form.get("confirm") or {}
    confirmed = bool(conf.get("selected")) and not conf.get("unselected")
    return {
        "items": items, "scenario": SCENARIO_BY_LABEL.get((form.get("scenario") or [""])[0], "other"),
        "source": source, "tactics": str(form.get("tactics") or ""), "firstSeen": str(form.get("first_seen") or ""),
        "channel": list(form.get("channel") or []), "script": script or "", "notes": str(form.get("notes") or ""),
        "confirmed": confirmed, "errors": errors,
    }


def _known_tactics() -> set:
    return {t["id"] for t in load("tactics")["tactics"]}


def _parse_day(s: str, issue_day: str) -> Tuple[str, Optional[str]]:
    m = re.search(r"(20[0-9]{2})[-/.年]([0-9]{1,2})[-/.月]([0-9]{1,2})", s or "")
    if m:
        try:
            d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            if d <= issue_day:
                return d, None
            return issue_day, "遇到的时间晚于提交时间，已改用提交日期"
        except ValueError:
            pass
    return issue_day, "遇到的时间无法识别（应为 YYYY-MM-DD），已改用提交日期"


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------- 主流程
def process(lib: dict, body: Optional[str], issue: dict, *, check: Optional[Callable[[str, str], dict]] = None) -> dict:
    """lib: 当前 intel.json；body: issue 正文；issue: {number, created_at, html_url}；
    check(kind, value) -> blocklist 结果（kind = url / crypto_tron / crypto_eth / crypto_btc），None 表示不比对。

    返回 {template, rows, notices, changed, library, raw_sensitive, confirmed}。rows/notices 只含公开值。"""
    number = int(issue["number"])
    issue_day = str(issue.get("created_at") or "")[:10] or _dt.date.today().isoformat()
    template = detect_template(body)
    res = {"template": template, "rows": [], "notices": [], "changed": False, "library": lib,
           "raw_sensitive": False, "confirmed": False, "number": number}
    if not template:
        res["notices"].append("没有识别出情报提交模板的字段。请使用「情报提交」模板新建 issue，不要删改字段标题。")
        return res
    sub = submission_from_form(parse_form(body, template), template)
    res["confirmed"] = sub["confirmed"]
    res["notices"] += sub["errors"]
    if not sub["confirmed"]:
        res["notices"].append("提交确认没有全部勾选，暂不生成 PR。勾选后编辑 issue 即可重新处理。")
        return res
    first_seen, warn = _parse_day(sub["firstSeen"], issue_day)
    if warn:
        res["notices"].append(warn)
    known = _known_tactics()
    given = [t for t in re.split(r"[\s,，、;；]+", sub["tactics"]) if t]
    tactics = [t for t in given if t in known]
    if len(tactics) < len(given):
        res["notices"].append(f"忽略了 {len(given) - len(tactics)} 个未知的话术标签（见 site/assets/core/tactics.json）")
    tag = f"gh-issue-{number}"

    # 话术片段与补充说明：再脱敏一次，并截断
    note_parts = [f"社区提交（GitHub #{number}）。"]
    if sub["channel"]:
        note_parts.append("渠道：" + "、".join(_short(c, 12) for c in sub["channel"][:5]) + "。")
    for label, text in (("话术摘录", sub["script"]), ("补充", sub["notes"])):
        if text.strip():
            ents = extract_sensitive(text)
            if ents:
                res["raw_sensitive"] = True
            note_parts.append(f"{label}：" + _short(redact_text(text, ents), 160) + "。")
    notes = "".join(note_parts)

    new_lib = json.loads(json.dumps(lib))
    entries = new_lib.setdefault("entries", [])
    index = {}
    for e in entries:
        k = _entry_key(e)
        if k:
            index.setdefault(k, e)
    year = issue_day[:4]
    seq = 0
    seen_keys = set()
    for it in sub["items"]:
        row = {"type": it["type"], "label": LABEL_BY_TYPE.get(it["type"], it["type"])}
        n = normalize_value(it["type"], it["raw"], it.get("platform"))
        if n.get("raw_sensitive"):
            res["raw_sensitive"] = True
        if not n["ok"]:
            row.update(status="invalid", reason=n["reason"])
            res["rows"].append(row)
            continue
        row["value"] = n["value"]
        key = (it["type"], n["key"])
        if key in seen_keys:
            row.update(status="skip", reason="与本 issue 中的另一条重复")
            res["rows"].append(row)
            continue
        seen_keys.add(key)
        extra = dict(n["extra"])
        if it["type"] == "bank_card" and it.get("bank"):
            extra["bank"] = _short(redact_text(it["bank"], extract_sensitive(it["bank"])), 20)
        bl = None
        if check and n.get("check"):
            try:
                bl = check(n["check"], n["value"])
            except Exception:  # 比对失败不影响收录
                bl = {"status": "unavailable"}
        row["blocklist"] = _bl_text(bl)
        hit = bool(bl and bl.get("status") == "hit")
        old = index.get(key)
        if old is not None:
            row["id"] = old.get("id")
            if old.get("example"):
                row.update(status="example", reason="与示例数据相同（示例数据是虚构的）")
            elif old.get("status") != "active":
                row.update(status="held", reason="该条目处于申诉/下架状态，需维护者人工处理")
            elif tag in (old.get("tags") or []):
                row.update(status="dup-same", reason="本 issue 已计入过该条目")
            else:
                old["reports"] = int(old.get("reports") or 1) + 1
                if first_seen > (old.get("lastSeen") or old.get("firstSeen") or ""):
                    old["lastSeen"] = first_seen
                if first_seen < (old.get("firstSeen") or first_seen):
                    old["firstSeen"] = first_seen
                old["tags"] = sorted(set(old.get("tags") or []) | {tag})
                if hit and old.get("confidence") == "low":
                    old["confidence"] = "medium"
                row.update(status="dup", reason=f"已存在，举报次数 +1（现为 {old['reports']}）")
                res["changed"] = True
            res["rows"].append(row)
            continue
        seq += 1
        e = {"id": f"DS-{year}-{number:04d}-{seq}", "example": False, "type": it["type"], "value": n["value"]}
        e.update({k: v for k, v in extra.items() if v})
        e.update({"scenario": sub["scenario"], "tactics": tactics, "firstSeen": first_seen, "reports": 1,
                  "source": sub["source"], "confidence": "medium" if hit else "low", "status": "active",
                  "tags": [tag], "notes": notes})
        if not tactics:
            del e["tactics"]
        errs = validate_entry(e)
        if errs:
            row.update(status="invalid", reason="；".join(errs))
            res["rows"].append(row)
            continue
        entries.append(e)
        index[key] = e
        row.update(status="added", id=e["id"])
        res["rows"].append(row)
        res["changed"] = True
    if res["changed"]:
        new_lib["updatedAt"] = max(str(new_lib.get("updatedAt") or ""), issue_day)
        res["library"] = new_lib
    return res


def _entry_key(e: dict) -> Optional[tuple]:
    t, v = e.get("type"), str(e.get("value") or "")
    if not t or not v:
        return None
    if t == "phone":
        return (t, _digits(v))
    if t == "crypto_wallet":
        return (t, wallet_key(v))
    if t == "url":
        return (t, re.sub(r"^[a-z][a-z0-9+.-]*://", "", v.lower()).rstrip("/"))
    if t in ("app", "script"):
        return (t, re.sub(r"\s+", "", v.strip('"“”')).lower())
    return (t, v)


def validate_entry(e: dict) -> List[str]:
    """与 site/assets/js/intel.js 的 validateEntry() 规则一致。"""
    errs = []
    for k in ("id", "type", "value", "scenario", "firstSeen", "source", "status"):
        if e.get(k) in (None, ""):
            errs.append(f"缺少字段 {k}")
    if e.get("type") not in LABEL_BY_TYPE:
        errs.append("未知类型")
    if e.get("firstSeen") and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", e["firstSeen"]):
        errs.append("firstSeen 须为 YYYY-MM-DD")
    if e.get("type") in MASKED_TYPES:
        v = str(e.get("value") or "")
        if re.search(r"[0-9]{7,}", v):
            errs.append("打码类型的 value 含有 7 位以上连续数字，疑似未脱敏")
        if e["type"] == "name" and "*" not in v:
            errs.append("姓名须打码")
        if e["type"] == "bank_card" and not BANK_CARD_MASKED.match(v):
            errs.append("银行卡须按 PCI 格式打码")
    return errs


def _bl_text(bl: Optional[dict]) -> str:
    if not bl:
        return "—"
    st = bl.get("status")
    if st == "hit":
        how = "（父域名命中）" if bl.get("how") == "parent" else ""
        return "命中公开黑名单：" + "、".join(bl.get("sources") or []) + how
    if st == "clean":
        return "未命中"
    if st == "unavailable":
        return "黑名单暂不可用"
    return "—"


# ---------------------------------------------------------------- 输出
def build_files(lib: dict) -> Dict[str, str]:
    """intel.json 及其生成文件（与仓库里提交的格式逐字节一致）。"""
    files = {"intel.json": json.dumps(lib, ensure_ascii=False, indent=2)}
    files["intel.stix.json"] = stix.dumps(stix.convert(lib, use_stix2=False))
    files.update(feeds.build(lib))
    return files


def _md_text(s) -> str:
    """评论/PR 里的文本：转义 Markdown/HTML，打断 @提及 与 #引用。"""
    s = str(s)
    s = s.replace("\\", "\\\\")
    for ch in "`*_[]<>|~":
        s = s.replace(ch, "\\" + ch)
    s = s.replace("@", "@\u200b").replace("#", "#\u200b")
    return re.sub(r"[\r\n]+", " ", s)


def _md_code(s) -> str:
    s = re.sub(r"[\r\n]+", " ", str(s)).replace("`", "ʼ")
    return "`` " + s + " ``" if s else "—"


STATUS_TEXT = {"added": "新增", "dup": "重复，已合并", "dup-same": "重复，已计入", "example": "未收录",
               "held": "需人工处理", "invalid": "未收录", "skip": "跳过"}


def _table(rows: List[dict]) -> List[str]:
    out = ["| # | 类型 | 公开值 | 结果 | 黑名单比对 |", "|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        val = r.get("value")
        if r.get("type") == "bank_card" and val:
            val = format_card_groups(val)
        res = STATUS_TEXT.get(r["status"], r["status"])
        if r.get("id"):
            res += " " + _md_code(r["id"])
        if r.get("reason"):
            res += "：" + _md_text(r["reason"])
        out.append(f"| {i} | {_md_text(r['label'])} | {_md_code(val) if val else '（不回显）'} | {res} | {_md_text(r.get('blocklist', '—'))} |")
    return out


def render_comment(res: dict) -> str:
    lines = [MARKER, "**DeepSuck 情报提交机器人**（自动生成，只显示按发布策略处理后的公开值）", ""]
    if res["rows"]:
        lines += _table(res["rows"]) + [""]
    for n in res["notices"]:
        lines.append("- " + _md_text(n))
    if res["raw_sensitive"]:
        lines += ["", "> **请注意**：你提交的内容里有未打码的敏感信息（如银行卡号、姓名、个人账号或话术里的号码）。PR 和本评论都只用打码后的值，"
                  "但 issue 原文仍然公开可见。请**编辑本 issue 删掉原文**（改成打码值，如 `622202*********3445`、`王**`）；"
                  "维护者也可以在 issue 的编辑历史里删除旧版本，必要时隐藏或删除这个 issue。"]
    if res["changed"]:
        lines += ["", "已生成待审核的 PR（链接见下）。**PR 不会自动合并**，维护者审核通过后才会收录。"]
    elif res["confirmed"]:
        lines += ["", "本次没有需要写入情报库的变更，未生成 PR。"]
    lines += ["", "情报仅供参考，不能作为认定依据。已经转账或正在被骗请立即拨打 110。"]
    return "\n".join(lines) + "\n"


def render_pr(res: dict) -> str:
    n = res["number"]
    lines = [f"由情报提交 issue #{n} 自动生成（{res['template']}）。", "",
             "**维护者审核清单**（本 PR 不会自动合并）：", "",
             "- [ ] 值确实来自诈骗方，不是受害人或被冒用者的信息",
             "- [ ] 打码类条目（银行卡/姓名/账号）只含打码值；issue 原文如含未打码信息，已提醒提交者编辑或已隐藏",
             "- [ ] 场景、话术标签、来源与可信度合理", "",
             "变更（只列公开值）：", ""]
    lines += _table(res["rows"])
    lines += ["", "生成文件：`site/data/intel.json`、`intel.stix.json`、`intel.csv`、`intel.rss`（`python -m deepsuck.intake` 生成）。", "",
              f"Closes #{n}"]
    return "\n".join(lines) + "\n"


def secret_fragments(body: Optional[str], template: Optional[str]) -> List[str]:
    """issue 中打码类原值的“指纹”（≥7 位数字串、未打码的姓名/账号原文），用于输出前的泄露检查。只在内存中使用。"""
    frags: List[str] = []
    if not template:
        return frags
    sub = submission_from_form(parse_form(body, template), template)
    texts = [it["raw"] for it in sub["items"] if it["type"] in MASKED_TYPES]
    for t in texts:
        c = _clean_line(t)
        if "*" in c:
            continue
        d = _digits(c)
        if len(d) >= 7:
            frags.append(d)
        elif len(c) >= 2:
            frags.append(c)
    for text in (sub["script"], sub["notes"], *[it["raw"] for it in sub["items"] if it["type"] in ("app", "script")]):
        for e in extract_sensitive(text or ""):
            v = str(e.get("value") or "")
            d = _digits(v)
            if e["type"] in ("bank_card", "id_card", "phone") and len(d) >= 7:
                frags.append(d)
            elif e["type"] in ("name", "wechat", "qq", "alipay", "email") and len(v) >= 2:
                frags.append(v)
    return sorted(set(frags), key=len, reverse=True)


def leak_check(outputs: Dict[str, str], frags: List[str]) -> List[str]:
    """返回泄露的输出名（不返回片段本身）。数字片段在去掉分隔符的文本里查。"""
    bad = []
    for name, text in outputs.items():
        flat = re.sub(r"[\s\-]", "", text)
        for f in frags:
            if (f.isdigit() and f in flat) or (not f.isdigit() and f in text):
                bad.append(name)
                break
    return bad


def run(lib: dict, body: Optional[str], issue: dict, check=None) -> dict:
    """process + 渲染 + 泄露检查。返回 {changed, files, pr_md, comment_md, summary}。"""
    res = process(lib, body, issue, check=check)
    guard_failed = False
    try:
        files = build_files(res["library"]) if res["changed"] else {}
    except feeds.FeedError:  # 订阅源的打码校验兜底
        files, guard_failed = {}, True
    comment = render_comment(res)
    pr = render_pr(res) if res["changed"] else ""
    outputs = dict(files, **{"comment.md": comment, "pr.md": pr})
    public = {re.sub(r"[\s\-]", "", str(r.get("value") or "")) for r in res["rows"]
              if r.get("type") in ("phone", "url", "crypto_wallet") and r.get("value")}
    frags = [f for f in secret_fragments(body, res["template"]) if not any(f in p for p in public)]
    baseline = dict(build_files(lib), **{"comment.md": "", "pr.md": ""})
    leaked = [n for n in leak_check(outputs, frags) if not leak_check({n: baseline.get(n, "")}, frags)]
    if guard_failed:
        leaked = leaked or ["files"]
    if leaked:
        res["changed"] = False
        files, pr = {}, ""
        res["notices"].append("输出前的泄露检查没有通过，已中止生成 PR，请维护者人工处理。")
        comment = render_comment(dict(res, rows=[dict(r, value=None) for r in res["rows"]]))
    summary = {"template": res["template"], "changed": res["changed"], "raw_sensitive": res["raw_sensitive"],
               "rows": [{k: r.get(k) for k in ("type", "status", "id")} for r in res["rows"]], "leak_blocked": bool(leaked)}
    return {"changed": res["changed"], "files": files, "pr_md": pr, "comment_md": comment, "summary": summary}


def _blocklist_check(offline: bool):
    if offline:
        return None
    from .blocklist import Client
    c = Client()
    return lambda kind, value: c.check(kind, value)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DeepSuck 情报提交 issue -> intel.json PR")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("process")
    p.add_argument("--event", required=True, help="GitHub 事件 JSON（GITHUB_EVENT_PATH）")
    p.add_argument("--repo", default=".", help="仓库根目录")
    p.add_argument("--out", required=True, help="输出目录")
    p.add_argument("--offline", action="store_true", help="不做黑名单比对（不联网）")
    a = ap.parse_args(argv)
    ev = json.loads(Path(a.event).read_text(encoding="utf-8"))
    issue = ev.get("issue") or {}
    if "pull_request" in issue:
        raise IntakeError("不处理 PR")
    lib_path = Path(a.repo) / "site" / "data" / "intel.json"
    lib = json.loads(lib_path.read_text(encoding="utf-8"))
    out = run(lib, issue.get("body") or "", {"number": issue.get("number"), "created_at": issue.get("created_at")},
              check=_blocklist_check(a.offline))
    od = Path(a.out)
    (od / "files").mkdir(parents=True, exist_ok=True)
    for name, text in out["files"].items():
        with open(od / "files" / name, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    (od / "comment.md").write_text(out["comment_md"], encoding="utf-8")
    (od / "pr.md").write_text(out["pr_md"], encoding="utf-8")
    (od / "summary.json").write_text(json.dumps(out["summary"], ensure_ascii=False, indent=1), encoding="utf-8")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if out['changed'] else 'false'}\n")
    s = out["summary"]
    print(f"intake: template={s['template']} changed={s['changed']} rows={[(r['type'], r['status']) for r in s['rows']]}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
