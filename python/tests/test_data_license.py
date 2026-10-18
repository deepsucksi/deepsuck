"""情报数据许可（CC BY 4.0，署名 DeepSuck (deepsuck.si)）在 intel.json / schema / RSS / STIX / CSV / DATA_LICENSE 中一致。"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from deepsuck import datalicense as DL
from deepsuck import feeds, stix

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "site" / "data"
LIB = json.loads((DATA / "intel.json").read_text(encoding="utf-8"))


def test_constants():
    assert DL.LICENSE_ID == "CC-BY-4.0"
    assert DL.ATTRIBUTION == "DeepSuck (deepsuck.si)"
    assert DL.LICENSE_URL == "https://creativecommons.org/licenses/by/4.0/legalcode"


def test_library_declares_license():
    assert LIB["license"] == DL.LICENSE_ID
    assert LIB["licenseUrl"] == DL.LICENSE_URL
    assert LIB["attribution"] == DL.ATTRIBUTION


def test_library_matches_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((DATA / "intel.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(LIB)
    for k in ("license", "licenseUrl", "attribution"):
        assert k in schema["required"]
        bad = dict(LIB)
        bad[k] = "Apache-2.0"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(bad)


def test_rss_copyright():
    rss = (DATA / "intel.rss").read_text(encoding="utf-8")
    ch = ET.fromstring(rss.encode("utf-8")).find("channel")
    cp = ch.find("copyright").text
    assert "CC BY 4.0" in cp and DL.ATTRIBUTION in cp and DL.LICENSE_URL in cp
    assert "CC BY 4.0" in ch.find("description").text


def test_csv_has_no_comment_line():
    csv = (DATA / "intel.csv").read_bytes().decode("utf-8")
    assert csv.startswith("\ufeff" + ",".join(feeds.CSV_COLS) + "\r\n")


def test_stix_license_marking_on_every_object():
    b = json.loads((DATA / "intel.stix.json").read_text(encoding="utf-8"))
    mid = stix.LICENSE_MARKING["id"]
    marks = [o for o in b["objects"] if o["id"] == mid]
    assert len(marks) == 1
    m = marks[0]
    assert m["definition_type"] == "statement"
    st = m["definition"]["statement"]
    assert "CC BY 4.0" in st and DL.ATTRIBUTION in st and DL.LICENSE_URL in st
    others = [o for o in b["objects"] if o["type"] != "marking-definition"]
    assert any(o["type"] == "identity" for o in others)
    for o in others:
        assert mid in o.get("object_marking_refs", []), o["id"]
        assert stix.TLP_WHITE["id"] in o["object_marking_refs"], o["id"]


def test_submission_export_has_no_library_license():
    sub = {"schema": "deepsuck.intel-submission/v1", "scenario": "police", "indicators": [
        {"type": "phone", "value": "10000000009", "policy": "full", "seen": 1}]}
    assert stix.LICENSE_MARKING["id"] not in json.dumps(stix.convert(sub, use_stix2=False))


def test_generators_reject_mismatched_license():
    bad = dict(LIB, license="Apache-2.0")
    with pytest.raises(feeds.FeedError):
        feeds.build(bad)
    with pytest.raises(ValueError):
        stix.convert(bad, use_stix2=False)


def test_data_license_file():
    text = (ROOT / "DATA_LICENSE").read_text(encoding="utf-8")
    assert DL.ATTRIBUTION in text and DL.LICENSE_URL in text and "Apache-2.0" in text
    for f in ("site/data/intel.json", "site/data/intel.csv", "site/data/intel.rss", "site/data/intel.stix.json"):
        assert f in text
    assert "Attribution 4.0 International" in text and "Section 3 -- License Conditions." in text
