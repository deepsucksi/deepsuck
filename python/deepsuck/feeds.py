"""公开订阅源：由 site/data/intel.json 生成 intel.csv 与 intel.rss（RSS 2.0）。

- 只输出 status == "active" 的条目；申诉中（disputed）与已下架（removed）的条目不输出。
- 只含公开字段（与情报页“下载 CSV”的列一致，见 site/assets/js/intel.js 的 CSV_COLS），value 用库里已按发布策略处理的值
  （银行卡为 PCI 打码值，姓名/账号已打码）；打码类条目若未通过打码校验，整次生成失败而不是输出。
- 输出是确定的（只依赖 intel.json），可提交进仓库并由测试检查是否最新。

用法：python -m deepsuck.feeds ../site/data/intel.json --out-dir ../site/data
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlencode
from xml.sax.saxutils import escape

SITE = "https://deepsuck.si"
CSV_COLS = ["id", "example", "type", "value", "chain", "bank", "issuer", "cardType", "scenario", "tactics",
            "firstSeen", "lastSeen", "reports", "source", "confidence", "status", "notes"]
MASKED_TYPES = ("bank_card", "account", "name", "id_card")
BANK_CARD_MASKED = re.compile(r"^(?:[0-9]{6}\*{6,9}[0-9]{4}|\*{4,11}[0-9]{4})$")
LABELS = {
    "phone": "诈骗电话", "crypto_wallet": "加密钱包地址", "url": "诈骗网址/域名", "app": "APP/平台名称",
    "script": "话术/手法", "bank_card": "收款银行卡", "account": "支付宝/微信/QQ 等账号", "name": "收款户名/姓名",
    "id_card": "身份证号",
}
# XML 1.0 不允许的控制字符
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


class FeedError(ValueError):
    pass


def public_entries(lib: dict) -> List[dict]:
    out = []
    for e in lib.get("entries") or []:
        if e.get("status", "active") != "active":
            continue
        t = e.get("type")
        v = str(e.get("value") or "")
        if t in MASKED_TYPES:
            if re.search(r"[0-9]{7,}", v) or (t == "bank_card" and not BANK_CARD_MASKED.match(v)) \
                    or (t == "name" and "*" not in v):
                raise FeedError(f"{e.get('id')}: 打码类条目未按发布策略打码，拒绝生成订阅源")
        out.append(e)
    return out


def _csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        v = "true" if v else "false"
    if isinstance(v, list):
        v = "|".join(str(x) for x in v)
    v = str(v)
    if re.match(r"^[=+\-@]", v):
        v = "'" + v  # 防 CSV 公式注入（与 intel.js 一致）
    return '"' + v.replace('"', '""') + '"' if re.search(r'[",\n\r]', v) else v


def to_csv(entries: Iterable[dict]) -> str:
    """与 site/assets/js/intel.js 的 toCSV() 逐字节一致：UTF-8 BOM + CRLF。"""
    lines = [",".join(CSV_COLS)]
    for e in entries:
        lines.append(",".join(_csv_cell(e.get(c)) for c in CSV_COLS))
    return "\ufeff" + "\r\n".join(lines) + "\r\n"


def _rfc822(day: str) -> str:
    d = _dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    return d.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _x(s) -> str:
    return escape(_XML_BAD.sub("", str(s)))


def _title(e: dict) -> str:
    label = LABELS.get(e.get("type"), e.get("type"))
    v = str(e.get("value") or "")
    if e.get("type") == "script" and len(v) > 40:
        v = v[:40] + "…"
    extra = [x for x in (e.get("chain"), e.get("issuer") or e.get("bank"), e.get("cardType")) if x]
    return f"{label}：{v}" + ("（" + " · ".join(extra) + "）" if extra else "") + ("［示例］" if e.get("example") else "")


def _description(e: dict) -> str:
    parts = [f"类型：{LABELS.get(e.get('type'), e.get('type'))}", f"公开值：{e.get('value')}"]
    for k, name in (("chain", "链"), ("bank", "开户行"), ("issuer", "发卡行（BIN 推断）"), ("cardType", "卡种"),
                    ("scenario", "场景"), ("firstSeen", "首次出现"), ("lastSeen", "最近出现"), ("reports", "举报次数"),
                    ("source", "来源"), ("confidence", "可信度")):
        if e.get(k) not in (None, ""):
            parts.append(f"{name}：{e[k]}")
    if e.get("tactics"):
        parts.append("话术标签：" + ", ".join(e["tactics"]))
    if e.get("notes"):
        parts.append("说明：" + e["notes"])
    parts.append("情报仅供参考，不能作为认定依据。")
    return "\n".join(parts)


def _link(e: dict) -> str:
    """情报页按类型 + 关键字筛选到该条目（页面暂不支持按 id 定位）。"""
    q = {"type": e.get("type") or ""}
    if e.get("type") != "script":
        q["q"] = str(e.get("value") or "")
    return f"{SITE}/intel.html?" + urlencode(q)


def to_rss(lib: dict, entries: List[dict]) -> str:
    items = sorted(entries, key=lambda e: (e.get("lastSeen") or e.get("firstSeen") or "", e.get("id") or ""), reverse=True)
    updated = lib.get("updatedAt") or max((e.get("firstSeen") for e in entries), default="2026-01-01")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{_x(lib.get('title') or 'DeepSuck 公开诈骗情报库')}</title>",
        f"<link>{SITE}/intel.html</link>",
        f'<atom:link href="{SITE}/data/intel.rss" rel="self" type="application/rss+xml"/>',
        "<description>DeepSuck 公开诈骗情报库订阅源：只含已公开（active）条目，银行卡、姓名、个人账号均为打码值。"
        "情报仅供参考，不能作为认定依据。</description>",
        "<language>zh-cn</language>",
        f"<copyright>{_x(lib.get('license') or 'Apache-2.0')}</copyright>",
        f"<lastBuildDate>{_rfc822(updated)}</lastBuildDate>",
        "<generator>deepsuck.feeds</generator>",
    ]
    for e in items:
        eid = str(e.get("id") or "")
        day = e.get("lastSeen") or e.get("firstSeen") or updated
        out += [
            "<item>",
            f"<title>{_x(_title(e))}</title>",
            f"<link>{_x(_link(e))}</link>",
            f'<guid isPermaLink="false">deepsuck-intel:{_x(eid)}</guid>',
            f"<pubDate>{_rfc822(day)}</pubDate>",
            f"<category>{_x(e.get('type'))}</category>",
        ]
        if e.get("scenario"):
            out.append(f"<category>{_x('scenario:' + str(e['scenario']))}</category>")
        out += [f"<description>{_x(_description(e))}</description>", "</item>"]
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def build(lib: dict) -> dict:
    """返回 {文件名: 文本}。"""
    entries = public_entries(lib)
    return {"intel.csv": to_csv(entries), "intel.rss": to_rss(lib, entries)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DeepSuck 情报库 -> intel.csv / intel.rss")
    ap.add_argument("input", help="intel.json")
    ap.add_argument("--out-dir", required=True, help="输出目录（通常是 site/data）")
    a = ap.parse_args(argv)
    lib = json.loads(Path(a.input).read_text(encoding="utf-8"))
    for name, text in build(lib).items():
        p = Path(a.out_dir) / name
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"wrote {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
