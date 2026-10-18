"""site/assets/core/scam_scripts.json：schema 校验 + 内容规则（脱敏、覆盖、来源、与 corpus/scripts 命名一致）。"""
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "site" / "assets" / "core"
DATA = json.loads((CORE / "scam_scripts.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((CORE / "scam_scripts.schema.json").read_text(encoding="utf-8"))
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
PHASES = ["opening", "trust", "pressure", "request", "payout"]


def test_schema_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    jsonschema.validate(DATA, SCHEMA)


def test_types_match_corpus_scripts():
    for t in DATA["types"]:
        y = yaml.safe_load((ROOT / t["corpusFile"]).read_text(encoding="utf-8"))
        assert y["id"] == t["id"]
        assert [s["id"] for s in t["stages"]] == [s["id"] for s in y["stages"]]
        assert {p["id"] for p in y["pressure_tactics"]} <= {p["id"] for p in t["pressureTactics"]}


def test_coverage_every_type_and_phase():
    seen = {(e["type"], e["phase"]) for e in DATA["entries"]}
    for t in DATA["types"]:
        for ph in PHASES:
            assert (t["id"], ph) in seen, (t["id"], ph)
    assert len({e["id"] for e in DATA["entries"]}) == len(DATA["entries"])


def test_entries_reference_valid_ids():
    types = {t["id"]: t for t in DATA["types"]}
    sources = {s["id"]: s for s in DATA["sources"]}
    from deepsuck.tactics import TACTICS
    tactic_ids = {t["id"] for t in TACTICS}
    for e in DATA["entries"]:
        t = types[e["type"]]
        assert e["id"].startswith(e["type"] + "-")
        assert e["stage"] in {s["id"] for s in t["stages"]}, e["id"]
        assert set(e["pressure"]) <= {p["id"] for p in t["pressureTactics"]}, e["id"]
        assert set(e["tactics"]) <= tactic_ids, e["id"]
        assert all(s in sources for s in e["sourceIds"]), e["id"]
        assert e["sourceLabel"] == DATA["sourceTypes"][e["sourceType"]]["label"]
        if e["sourceType"] == "dataset":
            assert all(u.startswith(sources[e["sourceIds"][0]]["url"]) for u in e["sourceUrls"])
        else:
            assert e["sourceUrls"] == [sources[s]["url"] for s in e["sourceIds"]], e["id"]
        # 标注为案例 / 通报 / 数据集的，第一个来源必须是对应类型的文档
        doc = sources[e["sourceIds"][0]]["docType"]
        want = {"court_case": {"court"}, "police_case": {"police_release"}, "police_bulletin": {"police_release"},
                "dataset": {"dataset"}}.get(e["sourceType"])
        if want:
            assert doc in want, e["id"]
        ph = set(re.findall(r"\{(.+?)\}", e["text"]))
        assert ph <= set(DATA["placeholders"]), e["id"]
        assert set(e["intel"]) == {DATA["placeholders"][p]["intel"] for p in ph if DATA["placeholders"][p]["intel"]}, e["id"]


def test_redaction_rules():
    for e in DATA["entries"]:
        s = e["text"]
        assert not re.search(r"\d{6,}", s), s
        assert not re.search(r"1[3-9]\d{9}", s), s
        assert not EMOJI.search(s), s
        assert not re.search(r"https?://|www\.", s, re.I), s
        assert "*" not in s, s
        assert not re.search(r"[A-Za-z0-9-]+\.(?:com|cn|net|top|vip|cc|xyz|org)\b", s), s
    for v in DATA["placeholders"].values():
        for host in re.findall(r"https?://([^/\s]+)", v["example"]):
            assert host.endswith(".example"), v
    blob = json.dumps(DATA, ensure_ascii=False)
    assert "DeepSeek" not in blob and not EMOJI.search(blob)


def test_licenses_declared():
    assert DATA["license"] == "CC-BY-4.0"
    lic = (ROOT / "DATA_LICENSE").read_text(encoding="utf-8")
    assert "scam_scripts.json" in lic
    taf = [s for s in DATA["sources"] if s["docType"] == "dataset"]
    assert taf and all(s["license"] == "Apache-2.0" for s in taf)
    for s in DATA["sources"]:
        assert s["license"] and s["usage"]


def test_typo_table_in_sync_with_personas_confusion():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_typo_keywords.py"), "--check"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
