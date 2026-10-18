"""STIX 2.1 导出：确定性、发布策略（打码类不导出）、与 site/data/intel.stix.json 同步；装了 stix2 时用官方库校验。"""
import json
import re
from pathlib import Path

import pytest

from deepsuck import stix

ROOT = Path(__file__).resolve().parents[2]
LIB = json.loads((ROOT / "site" / "data" / "intel.json").read_text(encoding="utf-8"))


def test_library_bundle_is_in_sync():
    """改了 intel.json 后请运行：cd python && python -m deepsuck.stix ../site/data/intel.json -o ../site/data/intel.stix.json"""
    got = stix.dumps(stix.convert(LIB, use_stix2=False))
    assert (ROOT / "site" / "data" / "intel.stix.json").read_text(encoding="utf-8") == got


def test_policy_masked_types_never_exported():
    b = stix.convert(LIB, use_stix2=False)
    text = json.dumps(b, ensure_ascii=False)
    masked = [e for e in LIB["entries"] if e["type"] in ("account", "name", "id_card")]
    assert masked
    for e in masked:
        assert e["value"] not in text
        assert e["id"] not in text
    kinds = [o["type"] for o in b["objects"]]
    full = [e for e in LIB["entries"] if e["type"] in stix.INDICATOR_TYPES and e["status"] == "active"]
    assert kinds.count("indicator") == len(full)
    assert kinds.count("note") == sum(e["type"] == "script" for e in LIB["entries"])


def test_bank_cards_exported_with_pci_mask_only():
    b = stix.convert(LIB, use_stix2=False)
    cards = [o for o in b["objects"] if o["type"] == "indicator" and "payment-card" in o["pattern"]]
    lib_cards = [e for e in LIB["entries"] if e["type"] == "bank_card"]
    assert len(cards) == len(lib_cards) == 2
    for o in cards:
        num = o["pattern"].split("'")[1]
        assert re.fullmatch(r"[0-9]{6}_{6,9}[0-9]{4}", num)
        assert o["x_deepsuck_issuer"] and o["x_deepsuck_card_type"]
        assert not re.search(r"[0-9]{7,}", json.dumps(o, ensure_ascii=False))
    # 完整卡号或旧格式绝不导出
    assert stix.pattern_of({"type": "bank_card", "value": "6222020200112233445"}) is None
    assert stix.pattern_of({"type": "bank_card", "value": "622202*********0001"}) == "[payment-card:card_number LIKE '622202_________0001']"
    assert stix.pattern_of({"type": "name", "value": "王**"}) is None
    assert stix.pattern_of({"type": "bank_card", "value": "622202******2233"}) == "[payment-card:card_number LIKE '622202______2233']"


def test_inactive_entries_skipped_and_deterministic():
    lib = json.loads(json.dumps(LIB))
    lib["entries"][0]["status"] = "disputed"
    a = stix.convert(lib, use_stix2=False)
    assert a == stix.convert(lib, use_stix2=False)
    assert lib["entries"][0]["value"] not in json.dumps(a)
    for o in a["objects"]:
        if o["type"] != "marking-definition":
            assert o["id"].split("--")[1][14] == "4"  # UUIDv4 形式


def test_patterns():
    assert stix.pattern_of({"type": "phone", "value": "10000000001"}) == "[phone-number:value = '10000000001']"
    assert stix.pattern_of({"type": "url", "value": "evil-demo.example"}) == "[domain-name:value = 'evil-demo.example']"
    assert stix.pattern_of({"type": "url", "value": "evil-demo.example/dl"}) == "[url:value = 'http://evil-demo.example/dl']"
    assert stix.pattern_of({"type": "app", "value": "a'b\\c"}) == "[software:name = 'a\\'b\\\\c']"
    assert stix.pattern_of({"type": "bank_card", "value": "6222 **** **** 0001"}) is None


def test_submission():
    sub = {"schema": "deepsuck.intel-submission/v1", "scenario": "police", "tactics": ["authority"], "indicators": [
        {"type": "phone", "value": "10000000009", "policy": "full", "seen": 2},
        {"type": "bank_card", "value": "622202*********9999", "policy": "masked", "seen": 1, "issuer": "中国工商银行", "cardType": "借记卡"},
        {"type": "account", "value": "ke******26", "policy": "masked", "seen": 1},
        {"type": "crypto_wallet", "value": "TDemoExampleAddrDoNotUse0000000009", "policy": "full", "chain": "TRON", "seen": 1}]}
    b = stix.convert(sub, use_stix2=False)
    text = json.dumps(b, ensure_ascii=False)
    assert "ke******26" not in text
    assert "622202_________9999" in text
    assert sum(o["type"] == "indicator" for o in b["objects"]) == 3
    with pytest.raises(ValueError):
        stix.convert({"schema": "nope"})


def test_stix2_library_roundtrip():
    stix2 = pytest.importorskip("stix2")
    assert stix.convert(LIB, use_stix2=True) == stix.convert(LIB, use_stix2=False)
    b = stix2.parse(json.dumps(stix.convert(LIB, use_stix2=True)), allow_custom=True, version="2.1")
    assert len(b.objects) > 10
