"""评测费用台账与总预算护栏（eval/spend_ledger.py），以及换模型后的默认值与单价。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
import realism_judge as J  # noqa: E402

S = J.load_ledger()


def test_defaults_are_qwen38_flash():
    import llm_scammer
    assert J.MODEL == "qwen3.8-flash"
    assert llm_scammer.MODEL == "qwen3.8-flash"
    assert (J.PRICE_INPUT_PER_M, J.PRICE_OUTPUT_PER_M) == (0.8, 2.7)
    assert "qwen3.8-flash" in J.PRICE_SOURCE
    assert abs(J.cost_cny(1_000_000, 1_000_000) - 3.5) < 1e-9


def test_ledger_accumulates_and_caps(tmp_path):
    led = tmp_path / "eval-spend.csv"
    assert S.cap(3.0, "t", 10.0, led) == 3.0
    S.append("t", "x", "qwen3.8-flash", {"requests": 3, "prompt_tokens": 10, "completion_tokens": 2, "cost_cny": 8.5}, ledger=led)
    S.append("other", "x", "m", {"cost_cny": 9.0}, ledger=led)
    assert abs(S.spent("t", led) - 8.5) < 1e-9
    assert abs(S.cap(3.0, "t", 10.0, led) - 1.5) < 1e-9   # 总预算余额比单次上限更紧
    assert S.cap(3.0, None, 10.0, led) == 3.0              # 不用台账
    S.append("t", "x", "m", {"cost_cny": 1.5}, ledger=led)
    with pytest.raises(S.LedgerBudgetError):
        S.cap(3.0, "t", 10.0, led)
    assert led.read_text(encoding="utf-8").splitlines()[0].startswith("time,tag,script,model")


def test_total_budget_hard_limit(tmp_path):
    led = tmp_path / "l.csv"
    assert S.remaining("t", 50.0, led) == S.HARD_TOTAL_CNY   # 只能调低，不能调高


def test_scammer_cli_refuses_when_budget_used_up(tmp_path, capsys):
    import llm_scammer
    led = tmp_path / "l.csv"
    S.append("full", "x", "m", {"cost_cny": 10.0}, ledger=led)
    rc = llm_scammer.main(["--budget-tag", "full", "--ledger", str(led), "--seeds", "1", "--personas", "wang",
                           "--scenarios", "police"])
    assert rc == 2
    assert "已用完" in capsys.readouterr().err


def test_cached_tokens_column_and_migration(tmp_path):
    led = tmp_path / "old.csv"
    old = ("time,tag,script,model,requests,prompt_tokens,completion_tokens,cost_cny,note\n"
           "2026-10-19T14:10:00+08:00,t,x,qwen3.8-flash,2,56,10,0.000072,smoke ok\n")
    led.write_text(old, encoding="utf-8")
    S.append("t", "y", "qwen3.8-flash", {"requests": 1, "prompt_tokens": 2000, "completion_tokens": 10,
                                         "cached_tokens": 1536, "cost_cny": 0.0005}, ledger=led)
    import csv
    with open(led, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == S.FIELDS and "cached_tokens" in S.FIELDS
    assert rows[0]["cached_tokens"] == "" and rows[0]["note"] == "smoke ok" and rows[0]["cost_cny"] == "0.000072"
    assert rows[1]["cached_tokens"] == "1536"
    assert abs(S.spent("t", led) - 0.000572) < 1e-9   # 补列不改旧金额，累计照旧


def test_cached_price_from_official_page():
    assert J.PRICE_CACHED_INPUT_PER_M == 0.1 and J.BATCH_PRICE_FACTOR == 0.5
    assert abs(J.cost_cny(1_000_000, 0, 1_000_000) - 0.1) < 1e-9
    assert abs(J.cost_cny(1_000_000, 1_000_000, batch=True) - 1.75) < 1e-9
