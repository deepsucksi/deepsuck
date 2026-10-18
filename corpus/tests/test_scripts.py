import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = sorted((ROOT / "corpus" / "scripts").glob("*.yaml"))
TACTICS = {t["id"] for t in json.loads((ROOT / "site/assets/core/tactics.json").read_text(encoding="utf-8"))["tactics"]}
SCENARIOS = {s["id"] for s in json.loads((ROOT / "site/assets/core/scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
INTEL = {"bank", "phone", "url", "app", "wechat", "qq", "wallet", "name"}
EXPECTED = {"impersonate_cs", "impersonate_police", "impersonate_boss", "pig_butchering", "task_rebate",
            "investment", "loan_credit"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
PHONE = re.compile(r"1[3-9]\d{9}")
LONG_DIGITS = re.compile(r"\d{6,}")


def load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from all_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from all_strings(v)


def test_all_categories_present():
    assert {p.stem for p in SCRIPTS} == EXPECTED


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.stem)
def test_schema(path):
    d = load(path)
    assert d["id"] == path.stem
    for k in ("name", "version", "targets", "summary", "source"):
        assert d.get(k), k
    rel = d["related"]
    assert rel["tactics"] and set(rel["tactics"]) <= TACTICS, set(rel["tactics"]) - TACTICS
    assert rel.get("scenario") is None or rel["scenario"] in SCENARIOS
    assert len(d["stages"]) >= 3
    ids = [s["id"] for s in d["stages"]]
    assert len(ids) == len(set(ids))
    for s in d["stages"]:
        assert s["name"] and s["goal"] and len(s["lines"]) >= 1
        assert all(isinstance(x, str) for x in s["lines"])
    assert len(d["keywords"]) >= 8 and all(isinstance(k, str) for k in d["keywords"])
    assert len(d["pressure_tactics"]) >= 3
    for t in d["pressure_tactics"]:
        assert t["id"] and t["name"] and t["desc"] and t["lines"]
    assert d["intel_exposed"] and set(d["intel_exposed"]) <= INTEL
    assert len(d["red_flags"]) >= 2
    assert len(d["examples"]) >= 3
    for ex in d["examples"]:
        assert ex["id"] and len(ex["turns"]) >= 2
        for t in ex["turns"]:
            assert t["role"] in ("scammer", "victim") and isinstance(t["text"], str) and t["text"]


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.stem)
def test_redaction_rules(path):
    d = load(path)
    for s in all_strings(d):
        assert not LONG_DIGITS.search(s), s
        assert not PHONE.search(s), s
        assert not EMOJI.search(s), s
        assert not re.search(r"https?://|www\.", s), s
        assert "*" not in s, s
    for s in all_strings({"stages": d["stages"], "examples": d["examples"], "pt": d["pressure_tactics"]}):
        for ph in re.findall(r"\{([^{}]*)\}", s):
            assert ph and len(ph) <= 6, ph


def test_example_ids_unique_across_files():
    ids = [ex["id"] for p in SCRIPTS for ex in load(p)["examples"]]
    assert len(ids) == len(set(ids))
