"""银行卡 PCI DSS 打码：不同长度（Python 端；与 JS 的逐项一致性由 tests/fixtures/redact.json 保证）。"""
import re

import pytest

from deepsuck import mask
from deepsuck.redact import mask_bank_card

SRC = "6222021234567890123"


@pytest.mark.parametrize("n", [16, 17, 18, 19])
def test_standard_lengths_keep_first6_last4(n):
    d = SRC[:n]
    m = mask_bank_card(d)
    assert m == d[:6] + "*" * (n - 10) + d[-4:]
    assert not re.search(r"[0-9]{7,}", m)


@pytest.mark.parametrize("n", range(8, 16))
def test_short_lengths_keep_last4_only(n):
    m = mask_bank_card(SRC[:n])
    assert m == "*" * (n - 4) + SRC[:n][-4:]
    assert m.count("*") >= n / 2


def test_separators_and_tiny():
    assert mask("bank_card", "6222 0212 3456 7890 128") == "622202*********0128"
    assert mask("bank_card", "6222-0212-3456-7890-128") == "622202*********0128"
    assert mask_bank_card("6222021") == "*******"
    assert mask_bank_card("") == ""
