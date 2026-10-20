"""#222 P0：姓名语境里的真名抽成 name 并打码。用例与 tests/name_context.test.js 共用。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "python")]

from deepsuck.extractors import extract_sensitive, find_name_context  # noqa: E402
from deepsuck.redact import redact_text  # noqa: E402

F = json.loads((ROOT / "tests/fixtures/name_context.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_names(case):
    assert [e["value"] for e in extract_sensitive(case["text"]) if e["type"] == "name"] == case["names"]


@pytest.mark.parametrize("case", F["cases"], ids=lambda c: c["id"])
def test_redacted(case):
    assert redact_text(case["text"], extract_sensitive(case["text"])) == case["redacted"]


def test_find_name_context():
    assert [(e["value"], e["start"], e["lead"]) for e in find_name_context("我叫张三，转给李四")] == [("张三", 2, "我叫"), ("李四", 7, "转给")]
    assert find_name_context("我是王阿姨，是王牌吗") == []
