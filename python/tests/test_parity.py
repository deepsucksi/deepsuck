"""Python 实现必须与 tests/fixtures/*.json（由 JS 实现生成的金标准）逐项一致。"""
import pytest

from conftest import fixture
from deepsuck import classify, extract, mask, normalize, redact_text, risk_score
from deepsuck.core import js_to_py, utf16_len
from deepsuck.engine import Session
from deepsuck.rng import mulberry32

REDACT = fixture("redact")["cases"]
NORM = fixture("normalize")["cases"]
EXTRACT = fixture("extract")["cases"]
TACT = fixture("tactics")
SESS = fixture("sessions")["cases"]


def test_rng_matches_js():
    r = mulberry32(42)
    assert [round(r() * 1e9) for _ in range(3)] == [601103752, 448290559, 852465793]


def test_js_regex_translation():
    assert js_to_py(r"(?<![\dA-Za-z])\d{4}") == "(?<![0-9A-Za-z])[0-9]{4}"
    assert js_to_py(r"(?<![@\w.-])") == "(?<![@A-Za-z0-9_.-])"
    assert js_to_py(r"\/") == "/"


@pytest.mark.parametrize("case", REDACT, ids=lambda c: f"{c['type']}:{c['input']}")
def test_redact(case):
    assert mask(case["type"], case["input"]) == case["expected"]


@pytest.mark.parametrize("case", NORM, ids=lambda c: c["text"][:24])
def test_normalize(case):
    n = normalize(case["text"])
    assert n.text == case["expected"]
    assert n.changed == case["changed"]


@pytest.mark.parametrize("case", EXTRACT, ids=lambda c: c["text"][:24])
def test_extract(case):
    text = case["text"]
    got = extract(text)
    bmp = utf16_len(text) == len(text)
    exp = case["entities"]
    assert [(e["type"], e["value"], e["masked"]) for e in got] == [(e["type"], e["value"], e["masked"]) for e in exp]
    for g, e in zip(got, exp):
        assert g["sensitive"] == e["sensitive"]
        assert g["meta"] == e["meta"]
        assert g.get("raw") == e.get("raw")
        assert g.get("obfuscated") == e.get("obfuscated")
        if bmp:
            assert (g["start"], g["end"]) == (e["start"], e["end"])
    assert redact_text(text, got) == case["redacted"]


@pytest.mark.parametrize("case", TACT["cases"], ids=lambda c: c["text"][:24])
def test_classify(case):
    assert [{"id": t["id"], "match": t["match"]} for t in classify(case["text"])] == case["expected"]


@pytest.mark.parametrize("case", TACT["risk"], ids=str)
def test_risk(case):
    assert risk_score(case["counts"]) == case["expected"]


@pytest.mark.parametrize("case", SESS, ids=lambda c: f"{c['scenario']}-{c['persona']}-{c['seed']}")
def test_session_replay(case):
    s = Session(case["scenario"], case["persona"], rng=mulberry32(case["seed"]), now=lambda: 1760000000000)
    turns = [{"role": "bot", "text": s.opening()["text"], "intent": "opening"}]
    for line in case["lines"]:
        a = s.ingest(line)
        m = s.rule_reply(a)
        turns.append({"role": "scammer", "text": a["redacted"], "tactics": [t["id"] for t in a["tactics"]]})
        turns.append({"role": "bot", "text": m["text"], "intent": m["intent"]})
    assert turns == case["turns"]
    assert s.intel_list() == case["intel"]
    st = s.stats()
    assert {k: st[k] for k in ("estimatedScammerSeconds", "intelCount", "riskScore")} == case["stats"]


GROUPS = fixture("redact")["groups"]


@pytest.mark.parametrize("case", GROUPS, ids=lambda c: c["input"] or "empty")
def test_card_groups_parity(case):
    from deepsuck.redact import format_card_groups
    assert format_card_groups(case["input"]) == case["expected"]
