"""#164 校准脚本：合成 voice.llm_ab 文件 + 假客户端，不联网。"""
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load("discrimination_calib", "eval/discrimination_calib.py")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))


def _ab(tmp_path):
    rows = []
    for call, sc in enumerate(["police", "refund", "pig"]):
        for t in range(4):
            rows.append({"persona": "wang", "scenario": sc, "call": call, "turn": t,
                         "scammer": f"{sc} 第{t}句，请你马上转账到安全账户", "reply": f"啊？你说{t}啥，我听不清"})
    rows.append({"persona": "wang", "scenario": "nonexistent", "call": 9, "turn": 0, "scammer": "x", "reply": "y"})
    p = tmp_path / "ab.json"
    p.write_text(json.dumps({"rows": {"qwen3.7-flash": rows}}, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_calls_round_robin_and_dedup(tmp_path):
    p = _ab(tmp_path)
    calls = C.load_calls([p, p], max_calls=10)
    assert [c["scenario"] for c in calls] == ["pig", "police", "refund"]   # 去重、过滤未知场景
    assert all(len(c["lines"]) == len(c["good"]) == 4 for c in calls)


def test_groups_share_scammer_lines_and_judge_key_hides_group(tmp_path):
    calls = C.load_calls([_ab(tmp_path)])
    for g in C.GROUPS:
        reps = C.responder_replies(calls[0], g, 1000)
        assert len(reps) == 4 and all(isinstance(x, str) and x for x in reps)
        assert reps == C.responder_replies(calls[0], g, 1000)              # 确定性
    key, forms, pairs = C.judge_items(calls, C.GROUPS, 1000, per_group=6)
    assert pairs == 6 and len(forms["A"]) == 24 and len(key) == 24
    assert {k["condition"] for k in key.values()} == set(C.GROUPS)
    assert all(set(r) == {"id", "scammer", "reply"} for r in forms["A"])    # 评委看不到组别


def test_dry_run_estimates_without_client(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(C.J, "default_client_factory", lambda *a, **k: (lambda: (_ for _ in ()).throw(AssertionError())))
    rc = C.main(["--good-file", str(_ab(tmp_path)), "--judge-n", "6", "--ledger", str(tmp_path / "l.csv")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cost_cny" in out and not (tmp_path / "l.csv").exists()


def test_item_sample_seed_gives_different_items_per_seed(tmp_path):
    calls = C.load_calls([_ab(tmp_path)])

    def goods(seed, sample):
        key, forms, _ = C.judge_items(calls, C.GROUPS, seed, per_group=4, sample=sample)
        return sorted((r["scammer"], r["reply"]) for r in forms["A"] if key[r["id"]]["condition"] == "good")
    assert goods(1000, "head") == goods(1001, "head")          # 默认不变：题目不随 seed 变
    a, b = goods(1000, "seed"), goods(1001, "seed")
    assert len(a) == len(b) == 4 and a != b                     # 按 seed 抽样：两个 seed 评不同的题
    assert a == goods(1000, "seed")                             # 同 seed 可复现
