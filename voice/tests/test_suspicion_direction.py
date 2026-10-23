"""#194：FOLLOW_UP_RULE 起疑只写方向、不给例句。用例 tests/fixtures/suspicion_direction.json 与 tests/suspicion_direction.test.js 共用。"""
import json
from pathlib import Path

import pytest

from voice import persona as P

ROOT = Path(__file__).resolve().parents[2]
F = json.loads((ROOT / "tests/fixtures/suspicion_direction.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("pid", F["personas"])
def test_follow_up_rule_has_direction_without_examples(pid):
    sp = P.system_prompt(pid, "refund", "generic", first_turn=False)
    for w in F["required"]:
        assert w in sp, (pid, w)
    for w in F["forbidden"]:
        assert w not in sp, (pid, w)


@pytest.mark.parametrize("pid", F["personas"])
def test_no_example_lines_on_first_turn_either(pid):
    sp = P.system_prompt(pid, "refund", "opening", first_turn=True)
    for w in F["forbidden"]:
        assert w not in sp, (pid, w)
