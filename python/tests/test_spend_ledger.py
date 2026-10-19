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
