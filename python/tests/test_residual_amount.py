"""#222 后续：打码姓名后面紧跟数字 / 金额词时不当残名。用例与 tests/residual_amount.test.js 共用。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.refs import speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/residual_amount.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_speak_masked(case):
    assert speak_masked(case["text"]) == case["speak"]
