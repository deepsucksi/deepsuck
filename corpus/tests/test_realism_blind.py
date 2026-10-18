import csv
import importlib.util
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("realism_blind", ROOT / "eval/realism_blind.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def test_default_source_is_corpus_scripts():
    lines = R.load_corpus_scripts()
    assert len(lines) > 100
    assert {x["type"] for x in lines} == {p.stem for p in (ROOT / "corpus/scripts").glob("*.yaml")}
    assert R.make(10, seed=1)["meta"]["scammer_source"] == "corpus/scripts"


def test_make_is_deterministic_and_counterbalanced():
    a, b = R.make(30, seed=7), R.make(30, seed=7)
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)
    assert R.make(30, seed=8)["forms"] != a["forms"]
    key = a["key"]
    for form in "AB":
        pairs = [key[r["id"]]["pair"] for r in a["forms"][form]]
        assert sorted(pairs) == list(range(30))  # 每个句对在每份表只出现一次
    for p in range(30):
        conds = {key[q]["form"]: key[q]["condition"] for q in key if key[q]["pair"] == p}
        assert set(conds.values()) == {"raw", "humanized"}  # A、B 两份表里条件相反


def test_forms_do_not_leak_condition_and_are_masked(tmp_path):
    data = R.make(40, seed=3)
    R.write_make(data, tmp_path)
    for form in "AB":
        with open(tmp_path / f"form-{form}.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert list(rows[0]) == ["id", "scammer", "reply", "human", "bot", "unreadable", "note"]
        for r in rows:
            assert "{" not in r["scammer"] and "}" not in r["scammer"]
            assert not re.search(r"(?<![\d*])\d{6,}(?![\d*])", r["scammer"] + r["reply"])
            assert not re.match(r"[AB]\d{3}$", r["reply"])
    assert (tmp_path / "key.json").exists() and (tmp_path / "README.txt").exists()


def test_humanized_reply_comes_from_raw_with_recorded_seed():
    from personas.humanize import Humanizer
    data = R.make(20, seed=2)
    for p in data["pairs"]:
        assert p["raw"] in R.persona_replies(p["persona"])
        again = Humanizer(profile=p["persona"], seed=p["humanize_seed"]).apply(p["raw"], context=p["scammer"]).text
        assert again == p["humanized"]


def test_scammer_file_formats(tmp_path):
    analyst = {"schema": "deepsuck.core.scam-scripts/v1", "entries": [
        {"id": "x-001", "type": "impersonate_cs", "phase": "opening", "text": "您好，这边是{机构}售后。",
         "sourceLabel": "据公安部公开通报改写"},
        {"id": "x-002", "type": "loan_credit", "stage": "cashout", "text": "解冻金转到 {银行卡}，户名 {户名}。",
         "sourceLabel": "据官方反诈宣传手册改写"}]}
    f1 = tmp_path / "scam_scripts.json"
    f1.write_text(json.dumps(analyst, ensure_ascii=False), encoding="utf-8")
    lines = R.load_scammer_file(f1)
    assert [x["id"] for x in lines] == ["x-001", "x-002"]
    assert lines[0]["stage"] == "opening" and lines[1]["source"] == "据官方反诈宣传手册改写"
    data = R.make(4, seed=1, scammer_file=f1)
    assert {p["scammer_id"] for p in data["pairs"]} <= {"x-001", "x-002"}
    assert all("622202*********3445" in p["scammer"] or "某平台" in p["scammer"] for p in data["pairs"])
    f2 = tmp_path / "lines.jsonl"
    f2.write_text('"在吗？"\n{"r": "我是你王总"}\n', encoding="utf-8")
    assert [x["text"] for x in R.load_scammer_file(f2)] == ["在吗？", "我是你王总"]
    f3 = tmp_path / "empty.json"
    f3.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        R.load_scammer_file(f3)


def test_human_replies_in_both_forms(tmp_path):
    f = tmp_path / "human.jsonl"
    f.write_text('{"persona": "mom", "reply": "等下哈娃醒了", "scammer": "转到{银行卡}"}\n', encoding="utf-8")
    data = R.make(6, seed=1, human_file=f)
    hum = [q for q, k in data["key"].items() if k["condition"] == "human"]
    assert sorted(data["key"][q]["form"] for q in hum) == ["A", "B"]


def test_score_metrics():
    key = {
        "A001": {"condition": "raw", "pair": 0}, "B001": {"condition": "humanized", "pair": 0},
        "A002": {"condition": "humanized", "pair": 1}, "B002": {"condition": "raw", "pair": 1},
    }
    ratings = [
        {"id": "A001", "rater": "r1", "human": 2, "bot": 1, "unreadable": 0},
        {"id": "A001", "rater": "r2", "human": 1, "bot": 1, "unreadable": 0},
        {"id": "A002", "rater": "r1", "human": 4, "bot": 0, "unreadable": 1},
        {"id": "A002", "rater": "r2", "human": 5, "bot": 0, "unreadable": 0},
        {"id": "B001", "rater": "r3", "human": 4, "bot": 0, "unreadable": 0},
        {"id": "B002", "rater": "r3", "human": 3, "bot": 1, "unreadable": 0},
        {"id": "ZZZ", "rater": "r3", "human": 3, "bot": 1, "unreadable": 0},
    ]
    res = R.score(key, ratings)
    raw, hum = res["conditions"]["raw"], res["conditions"]["humanized"]
    assert raw["n"] == 3 and hum["n"] == 3
    assert raw["human_mean"] == 2.0 and hum["human_mean"] == pytest.approx(4.333, abs=1e-3)
    assert raw["detected_rate"] == 1.0 and hum["detected_rate"] == 0.0
    assert hum["unreadable_rate"] == pytest.approx(0.333, abs=1e-3)
    assert res["detected_diff_humanized_minus_raw"]["mean"] == -1.0
    assert res["pairwise_agreement"] == 1.0 and res["raters"] == 3 and res["ratings"] == 7


def test_cli_roundtrip(tmp_path):
    assert R.main(["make", "--n", "8", "--seed", "4", "--out-dir", str(tmp_path)]) == 0
    with open(tmp_path / "form-A.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = tmp_path / "rated-alice.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for k, r in enumerate(rows):
            w.writerow({**r, "human": 3 + k % 2, "bot": k % 2})
    res_path = tmp_path / "res.json"
    assert R.main(["score", "--key", str(tmp_path / "key.json"), str(out), "--json", str(res_path)]) == 0
    res = json.loads(res_path.read_text(encoding="utf-8"))
    assert res["score"]["ratings"] == 8 and set(res["auto"]) == {"raw", "humanized"}
