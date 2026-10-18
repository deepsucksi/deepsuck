"""公开订阅源 intel.csv / intel.rss。"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from deepsuck import feeds

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "site" / "data"
LIB = json.loads((DATA / "intel.json").read_text(encoding="utf-8"))


def test_committed_feeds_are_up_to_date():
    """改了 intel.json 后请运行：cd python && python -m deepsuck.feeds ../site/data/intel.json --out-dir ../site/data"""
    for name, text in feeds.build(LIB).items():
        assert (DATA / name).read_bytes().decode("utf-8") == text, name


def _lib_with_states():
    lib = json.loads(json.dumps(LIB))
    lib["entries"][0]["status"] = "disputed"
    lib["entries"][1]["status"] = "removed"
    return lib


def test_disputed_and_removed_are_not_published():
    lib = _lib_with_states()
    out = feeds.build(lib)
    for e in lib["entries"][:2]:
        for text in out.values():
            assert e["id"] not in text and e["value"] not in text
    items = ET.fromstring(out["intel.rss"].encode("utf-8")).findall("./channel/item")
    assert len(items) == len(lib["entries"]) - 2
    assert out["intel.csv"].count("\r\n") == len(lib["entries"]) - 2 + 1


def test_masked_values_only_and_guard():
    out = feeds.build(LIB)
    assert "622202*********0001" in out["intel.csv"] and "622202*********0001" in out["intel.rss"]
    bad = json.loads(json.dumps(LIB))
    bad["entries"].append({"id": "DS-X", "type": "bank_card", "value": "6222020200112233445", "scenario": "refund",
                           "firstSeen": "2026-10-01", "source": "community", "status": "active"})
    with pytest.raises(feeds.FeedError):
        feeds.build(bad)


def test_rss_is_valid_rss2_and_escapes():
    lib = json.loads(json.dumps(LIB))
    lib["entries"][0]["notes"] = "<script>alert(1)</script> & \x07"
    rss = feeds.build(lib)["intel.rss"]
    root = ET.fromstring(rss.encode("utf-8"))
    assert root.tag == "rss" and root.get("version") == "2.0"
    ch = root.find("channel")
    for tag in ("title", "link", "description", "lastBuildDate"):
        assert ch.find(tag) is not None
    for it in ch.findall("item"):
        for tag in ("title", "link", "guid", "pubDate", "description"):
            assert it.find(tag) is not None and it.find(tag).text
    assert "<script>" not in rss and "&lt;script&gt;" in rss


def test_csv_formula_injection_escaped():
    lib = json.loads(json.dumps(LIB))
    lib["entries"][0]["notes"] = "=HYPERLINK(\"http://x\")"
    assert "'=HYPERLINK" in feeds.build(lib)["intel.csv"]
