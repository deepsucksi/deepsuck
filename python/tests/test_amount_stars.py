"""#216：打码金额「****块钱」念量词说法、heard_refs 记 number。用例与 tests/amount_stars.test.js 共用。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.refs import heard_refs, speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/amount_stars.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_speak_masked_amount(case):
    assert speak_masked(case["text"]) == case["reply"]


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_heard_refs_amount(case):
    assert sorted(heard_refs([case["text"]])) == case["refs"]
