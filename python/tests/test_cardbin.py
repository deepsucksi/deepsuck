"""银行卡 BIN 查询：Python 与 JS（tests/fixtures/cardbin.json 金标准）一致。"""
import pytest

from conftest import fixture
from deepsuck import cardbin, extract

CASES = fixture("cardbin")["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["input"] or "empty")
def test_lookup_parity(case):
    assert cardbin.lookup(case["input"]) == case["expected"]


def test_extract_issuer_has_no_bin_digits():
    e = next(x for x in extract("卡号6222020200112233445") if x["type"] == "bank_card")
    assert e["meta"]["issuer"]["bank"] == "中国工商银行"
    assert "622202" not in repr(e["meta"])


def test_cli_does_not_echo_number(capsys):
    assert cardbin.main(["6222020200112233445"]) == 0
    out = capsys.readouterr()
    assert "622202" not in out.out and "6222020200112233445" not in out.out
    assert "中国工商银行" in out.out
