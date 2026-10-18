"""把 DeepSuck 情报导出为 STIX 2.1 Bundle（供 OpenCTI / MISP / TAXII 等威胁情报平台导入）。

- 输入：公开情报库 site/data/intel.json（deepsuck.intel-library/v1），或沙盒「提交到情报库」生成的
  deepsuck.intel-submission/v1；
- phone / crypto_wallet / url / app 生成 Indicator，script 生成 Note；
- bank_card 只导出 PCI DSS 打码值（前 6 后 4，如 622202*********3445）：Indicator 的 pattern 用
  `[payment-card:card_number LIKE '622202_________3445']`（_ 匹配一位被打码的数字），附 BIN 推断的发卡行与卡种；
  不符合打码格式的值（例如误填的完整卡号）一律不导出；
- account / name / id_card 是打码值，不能用于匹配、又可能属于被冒用的普通人，一律不导出；
- 只导出 status=active 的条目（disputed / removed 不导出）；
- 每个场景（refund / police / ...）是一个 Attack Pattern，Indicator 以 `indicates` 关系指向它；
- ID 用 uuid5 生成、时间取自条目日期，同一份输入总是得到同一份输出（便于 diff 与增量导入）；
- 自定义可观测类型沿用 OpenCTI 的命名：`phone-number:value`、`cryptocurrency-wallet:value`；
- 数据许可：库导出的 Bundle 附一个 statement 类型的 marking-definition（CC BY 4.0，署名「DeepSuck (deepsuck.si)」，
  见根目录 DATA_LICENSE），identity 与其余全部对象的 object_marking_refs 都引用它（与 TLP:WHITE 并列）；
  沙盒提交（deepsuck.intel-submission/v1）的导出不加，提交者的数据收录进库后才按库的许可发布；
- 安装了 stix2（`pip install stix2`，OASIS 官方库）时，用它解析、校验并序列化全部对象；未安装时退回纯标准库，输出字段一致。

用法：
  python -m deepsuck.stix site/data/intel.json -o site/data/intel.stix.json
  python -m deepsuck.stix 提交.json                    # 输出到 stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import datalicense as DL
from .core import load

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://deepsuck.si/stix")
IDENTITY_ID = "identity--" + str(uuid.UUID(bytes=uuid.uuid5(NS, "identity:deepsuck").bytes, version=4))
EXT_ID = "extension-definition--" + str(uuid.UUID(bytes=uuid.uuid5(NS, "extension:deepsuck-intel/v1").bytes, version=4))
EXT_PROPS = ["x_deepsuck_scenario", "x_deepsuck_source", "x_deepsuck_reports", "x_deepsuck_chain", "x_deepsuck_example",
             "x_deepsuck_bank", "x_deepsuck_issuer", "x_deepsuck_card_type"]
CARD_MASKED = re.compile(r"^[0-9]{6}\*{6,9}[0-9]{4}$")  # 与 intel.js 的 PCI 格式校验一致（只导出 16–19 位的前 6 后 4 形式）
IDENTITY_CREATED = "2026-10-01T00:00:00.000Z"
# TLP:WHITE（= TLP 2.0 的 TLP:CLEAR），STIX 2.1 规范预定义的 marking-definition
TLP_WHITE = {
    "type": "marking-definition", "spec_version": "2.1",
    "id": "marking-definition--613f2e26-407d-48c7-9eca-b8e91df99dc9",
    "created": "2017-01-20T00:00:00.000Z", "definition_type": "tlp", "name": "TLP:WHITE",
    "definition": {"tlp": "white"},
}
# 数据许可（CC BY 4.0）：STIX 2.1 的 statement 标记（规范 7.2.1.3），ID 确定性生成
LICENSE_MARKING = {
    "type": "marking-definition", "spec_version": "2.1",
    "id": "marking-definition--" + str(uuid.UUID(bytes=uuid.uuid5(NS, "marking:data-license:" + DL.LICENSE_ID).bytes, version=4)),
    "created": IDENTITY_CREATED, "created_by_ref": IDENTITY_ID,
    "name": f"DeepSuck data license: {DL.LICENSE_NAME}",
    "definition_type": "statement",
    "definition": {"statement": f"{DL.NOTICE_EN} {DL.NOTICE_ZH} 见 {DL.LICENSE_FILE_URL}"},
}
FULL_TYPES = ("phone", "crypto_wallet", "url", "app")
INDICATOR_TYPES = FULL_TYPES + ("bank_card",)
CONFIDENCE = {"example": 0, "low": 15, "medium": 50, "high": 85}
LABEL = {"phone": "诈骗电话", "crypto_wallet": "加密钱包地址", "url": "诈骗网址/域名", "app": "APP/平台名称", "bank_card": "收款银行卡"}


def _v4(key: str) -> str:
    """确定性的 UUIDv4 形式 ID：取 uuid5 的散列位，把版本位改成 4（规范要求 SDO/SRO 用 UUIDv4，同时保持可复现）。"""
    return str(uuid.UUID(bytes=uuid.uuid5(NS, key).bytes, version=4))


def _sid(kind: str, key: str) -> str:
    return f"{kind}--{_v4(kind + ':' + key)}"


def _ts(day: Optional[str], ms: bool = True) -> str:
    """'2026-10-01' -> '2026-10-01T00:00:00.000Z'（ms=False 时不带毫秒）。"""
    if not day:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = f"{day[:10]}T00:00:00"
    return base + (".000Z" if ms else "Z")


def _q(v: str) -> str:
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def pattern_of(entry: dict) -> Optional[str]:
    t, v = entry.get("type"), str(entry.get("value") or "").strip()
    if not v:
        return None
    if t == "phone":
        return f"[phone-number:value = {_q(v)}]"
    if t == "crypto_wallet":
        return f"[cryptocurrency-wallet:value = {_q(v)}]"
    if t == "url":
        if "://" in v:
            return f"[url:value = {_q(v)}]"
        host, _, path = v.partition("/")
        return f"[url:value = {_q('http://' + v)}]" if path else f"[domain-name:value = {_q(host.lower())}]"
    if t == "app":
        return f"[software:name = {_q(v)}]"
    if t == "bank_card":
        if not CARD_MASKED.match(v):
            return None  # 只接受 PCI 打码值，绝不导出完整卡号
        return f"[payment-card:card_number LIKE {_q(v.replace('*', '_'))}]"
    return None


def _identity() -> dict:
    return {
        "type": "identity", "spec_version": "2.1", "id": IDENTITY_ID,
        "created": IDENTITY_CREATED, "modified": IDENTITY_CREATED,
        "name": "DeepSuck", "identity_class": "organization",
        "description": "开源 AI 反诈“拖住”机器人项目的公开诈骗情报库（https://deepsuck.si）。情报仅供参考，不能作为认定依据。",
        "contact_information": "https://github.com/deepsucksi/deepsuck",
    }


def _extension() -> dict:
    return {
        "type": "extension-definition", "spec_version": "2.1", "id": EXT_ID,
        "created": IDENTITY_CREATED, "modified": IDENTITY_CREATED, "created_by_ref": IDENTITY_ID,
        "name": "DeepSuck intel properties",
        "description": "x_deepsuck_scenario 场景 id；x_deepsuck_source 来源（example/sandbox/community/honeypot/public-report）；x_deepsuck_reports 举报次数；x_deepsuck_chain 钱包所在链；x_deepsuck_example 示例数据标记；x_deepsuck_bank 对方声称的开户行；x_deepsuck_issuer / x_deepsuck_card_type 由 BIN 推断的发卡行与卡种（仅供参考）。",
        "schema": "https://github.com/deepsucksi/deepsuck/blob/main/docs/INTEL.md",
        "version": "1.0.0", "extension_types": ["toplevel-property-extension"],
        "extension_properties": EXT_PROPS, "object_marking_refs": [TLP_WHITE["id"]],
    }


def _scenario_ap(sid: str) -> dict:
    sc = {s["id"]: s for s in load("scenarios")["scenarios"]}.get(sid)
    o = {
        "type": "attack-pattern", "spec_version": "2.1", "id": _sid("attack-pattern", "scenario:" + sid),
        "created": IDENTITY_CREATED, "modified": IDENTITY_CREATED, "created_by_ref": IDENTITY_ID,
        "name": sc["title"] if sc else sid,
        "external_references": [{"source_name": "deepsuck-scenario", "external_id": sid}],
        "object_marking_refs": [TLP_WHITE["id"]],
    }
    if sc and sc.get("desc"):
        o["description"] = sc["desc"]
    return o


def _common(e: dict) -> dict:
    o = {"created_by_ref": IDENTITY_ID, "object_marking_refs": [TLP_WHITE["id"]]}
    labels = list(e.get("tactics") or []) + list(e.get("tags") or [])
    if e.get("example"):
        labels.append("example")
    if labels:
        o["labels"] = labels
    if e.get("confidence") in CONFIDENCE:
        o["confidence"] = CONFIDENCE[e["confidence"]]
    if e.get("id"):
        o["external_references"] = [{"source_name": "deepsuck", "external_id": e["id"]}]
    custom = False
    for k, prop in (("scenario", "scenario"), ("source", "source"), ("reports", "reports"), ("chain", "chain"),
                    ("bank", "bank"), ("issuer", "issuer"), ("cardType", "card_type")):
        if e.get(k) is not None:
            o["x_deepsuck_" + prop] = e[k]
            custom = True
    if e.get("example"):
        o["x_deepsuck_example"] = True
        custom = True
    if custom:  # STIX 2.1 推荐：自定义顶层属性通过 extension-definition 声明
        o["extensions"] = {EXT_ID: {"extension_type": "toplevel-property-extension"}}
    return o


def apply_license(objs: List[dict]) -> List[dict]:
    """在 TLP 标记后插入数据许可标记，并让 identity 与全部带 object_marking_refs 的对象引用它。"""
    out: List[dict] = []
    for o in objs:
        if o["type"] == "marking-definition":
            out.append(o)
            if o["id"] == TLP_WHITE["id"]:
                out.append(LICENSE_MARKING)
            continue
        o = dict(o)
        refs = list(o.get("object_marking_refs") or ([TLP_WHITE["id"]] if o["type"] == "identity" else []))
        if refs and LICENSE_MARKING["id"] not in refs:
            refs.append(LICENSE_MARKING["id"])
            o["object_marking_refs"] = refs
        out.append(o)
    return out


def entries_to_objects(entries: List[dict], default_day: str) -> List[dict]:
    objs: List[dict] = []
    scen: Dict[str, dict] = {}
    for e in entries:
        if e.get("status", "active") != "active":
            continue
        t = e.get("type")
        first = e.get("firstSeen") or default_day
        last = e.get("lastSeen") or first
        key = e.get("id") or f"{t}:{e.get('value')}"
        sid = e.get("scenario")
        if sid and sid not in scen:
            scen[sid] = _scenario_ap(sid)
        if t in INDICATOR_TYPES:
            pat = pattern_of(e)
            if not pat:
                continue
            card = [x for x in (e.get("issuer") or e.get("bank"), e.get("cardType")) if x] if t == "bank_card" else []
            extra = "（" + " · ".join(card) + "）" if card else ""
            ind = {
                "type": "indicator", "spec_version": "2.1", "id": _sid("indicator", key),
                "created": _ts(first), "modified": _ts(last),
                "name": f"{LABEL[t]}：{e['value']}{extra}",
                "indicator_types": ["malicious-activity"],
                "pattern": pat, "pattern_type": "stix", "pattern_version": "2.1",
                "valid_from": _ts(first, ms=False),
            }
            if e.get("notes"):
                ind["description"] = e["notes"]
            ind.update(_common(e))
            objs.append(ind)
            if sid:
                objs.append({
                    "type": "relationship", "spec_version": "2.1", "id": _sid("relationship", key + "->" + sid),
                    "created": _ts(first), "modified": _ts(last), "relationship_type": "indicates",
                    "source_ref": ind["id"], "target_ref": scen[sid]["id"],
                    "created_by_ref": IDENTITY_ID, "object_marking_refs": [TLP_WHITE["id"]],
                })
        elif t == "script":
            note = {
                "type": "note", "spec_version": "2.1", "id": _sid("note", key),
                "created": _ts(first), "modified": _ts(last),
                "abstract": "诈骗话术/手法", "content": str(e.get("value") or "") + (("\n\n" + e["notes"]) if e.get("notes") else ""),
                "object_refs": [scen[sid]["id"]] if sid else [IDENTITY_ID],
            }
            note.update(_common(e))
            objs.append(note)
        # account / name / id_card：打码类型，不导出
    return [_identity(), TLP_WHITE, _extension()] + list(scen.values()) + objs


def library_to_objects(lib: dict) -> List[dict]:
    if lib.get("license") not in (None, DL.LICENSE_ID) or lib.get("attribution") not in (None, DL.ATTRIBUTION):
        raise ValueError(f"intel.json 的 license/attribution 应为 {DL.LICENSE_ID} / {DL.ATTRIBUTION}（见 DATA_LICENSE）")
    return apply_license(entries_to_objects(lib.get("entries") or [], lib.get("updatedAt")))


def submission_to_objects(sub: dict, day: Optional[str] = None) -> List[dict]:
    """deepsuck.intel-submission/v1 -> STIX 对象（沙盒导出，无条目 ID，按 类型+值 生成 ID）。"""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = []
    for i in sub.get("indicators") or []:
        if i.get("policy") != "full" and i.get("type") != "bank_card":
            continue
        entries.append({"type": i.get("type"), "value": i.get("value"), "scenario": sub.get("scenario"),
                        "tactics": sub.get("tactics") or [], "firstSeen": day, "source": "sandbox",
                        "reports": i.get("seen") or 1, "chain": i.get("chain"), "bank": i.get("bank"),
                        "issuer": i.get("issuer"), "cardType": i.get("cardType"), "status": "active"})
    return entries_to_objects(entries, day)


def to_bundle(objs: List[dict], use_stix2: Optional[bool] = None) -> dict:
    """组装 Bundle。安装了 stix2 时逐个对象用 stix2.parse 校验（含 pattern 语法）并由 stix2 序列化。"""
    bid = "bundle--" + _v4("bundle:" + ",".join(o["id"] + o.get("modified", "") for o in objs))
    if use_stix2 is not False:
        try:
            import stix2  # type: ignore
        except ImportError:
            if use_stix2:
                raise
            stix2 = None
        if stix2 is not None:
            parsed = [stix2.parse(o, allow_custom=True, version="2.1") for o in objs]
            b = stix2.v21.Bundle(objects=parsed, id=bid, allow_custom=True)
            return json.loads(b.serialize())
    return {"type": "bundle", "id": bid, "objects": objs}


def dumps(bundle: dict) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def convert(doc: dict, use_stix2: Optional[bool] = None) -> dict:
    schema = doc.get("schema")
    if schema == "deepsuck.intel-library/v1":
        return to_bundle(library_to_objects(doc), use_stix2)
    if schema == "deepsuck.intel-submission/v1":
        return to_bundle(submission_to_objects(doc), use_stix2)
    raise ValueError(f"不支持的 schema：{schema!r}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DeepSuck 情报 -> STIX 2.1 Bundle")
    ap.add_argument("input", help="intel.json（deepsuck.intel-library/v1）或提交 JSON（deepsuck.intel-submission/v1）")
    ap.add_argument("-o", "--out", help="输出文件（默认 stdout）")
    ap.add_argument("--no-stix2", action="store_true", help="不使用 stix2 库（纯标准库输出）")
    a = ap.parse_args(argv)
    with open(a.input, encoding="utf-8") as f:
        doc = json.load(f)
    bundle = convert(doc, use_stix2=False if a.no_stix2 else None)
    text = dumps(bundle)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        kinds: Dict[str, int] = {}
        for o in bundle["objects"]:
            kinds[o["type"]] = kinds.get(o["type"], 0) + 1
        print(f"wrote {a.out}: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())), file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
