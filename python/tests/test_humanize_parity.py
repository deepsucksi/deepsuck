"""personas.humanize（Python）与 site/assets/js/humanize.js 逐字一致：tests/fixtures/humanize.json 由 JS 生成。"""
import sys
from pathlib import Path

import pytest

from conftest import fixture

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personas.humanize import Humanizer  # noqa: E402

CASES = fixture("humanize")["cases"]
KW = {"typoPer100": "typo_per_100", "punctStyle": "punct_style", "maxTypos": "max_typos", "shapeTypos": "shape_typos"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['config']}-{c['seed']}")
def test_humanize_matches_js(case):
    kw = {KW.get(k, k): v for k, v in case["config"].items()}
    h = Humanizer(seed=case["seed"], **kw)
    for t in case["turns"]:
        r = h.apply(t["input"], t["context"], t.get("intent"))
        assert (r.text, r.ops) == (t["text"], t["ops"]), t["input"]
    assert h.typo_map == case["typoMap"]
