"""#187：人设不得说成已经转账或答应去转。deepsuck.engine.hold_transfer 与 JS engine.holdTransfer 逐字一致。

用例 tests/fixtures/transfer_claim.json（与 tests/transfer_claim.test.js、voice/tests/test_transfer_claim.py 共用）。
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python")]

from deepsuck.engine import hold_transfer, transfer_claim  # noqa: E402
from deepsuck.personas import TRANSFER_CLAIM as TC  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/transfer_claim.json").read_text(encoding="utf-8"))
PJ = json.loads((ROOT / "site/assets/core/personas.json").read_text(encoding="utf-8"))


def any_claim(t: str) -> bool:
    s = re.sub(TC["quote"], "\ue010", t)
    return any(transfer_claim(x) for x in re.findall("[^" + re.escape(TC["split"]) + "]+", s))


@pytest.mark.parametrize("case", F["claim"], ids=lambda c: c["text"][:12])
def test_claim_rewritten_same_as_js(case):
    out = hold_transfer(case["text"])
    assert out == case["expected"]
    assert out != case["text"] and any(x in out for x in TC["stall"])
    assert not any_claim(out)
    assert hold_transfer(out) == out


@pytest.mark.parametrize("text", F["keep"], ids=lambda t: t[:12])
def test_keep_unchanged(text):
    assert hold_transfer(text) == text


def test_approved_lines_untouched():
    bad, n = [], 0

    def walk(o, path):
        nonlocal n
        if isinstance(o, str):
            n += 1
            if hold_transfer(o) != o:
                bad.append(path)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, dict):
            for k, v in o.items():
                if k != "when":
                    walk(v, f"{path}.{k}")

    for p in PJ["personas"]:
        walk(p, p["id"])
    assert n > 1000 and not bad, bad


def test_empty_and_plain():
    assert hold_transfer("") == "" and hold_transfer(None) == ""
    assert hold_transfer("你说慢点。") == "你说慢点。"
