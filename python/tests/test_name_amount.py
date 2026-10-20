"""#220：名字后面紧跟数字 / 金额词时金额不被吃掉。用例与 tests/name_amount.test.js 共用。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.extractors import extract_sensitive  # noqa: E402
from deepsuck.redact import redact_text  # noqa: E402
from deepsuck.refs import heard_refs, mask_names, speak_masked  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/name_amount.json").read_text(encoding="utf-8"))


def _reply(t):
    s = mask_names(t)
    return speak_masked(redact_text(s, extract_sensitive(s)))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_reply(case):
    out = _reply(case["text"])
    assert out == case["reply"]
    if "name" in case["refs"]:
        assert not any(x in out for x in "李张王")


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_heard_refs(case):
    assert sorted(heard_refs([case["text"]])) == case["refs"]
