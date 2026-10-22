"""#163 复审：refs 出口（mask_names → redact_text → speak_masked）与 web（llm.js sanitizeReply，夹具 exitParity）逐项一致、不露姓名。"""
import re

import pytest

from deepsuck import extract_sensitive, redact_text
from deepsuck.refs import mask_names, speak_masked

from conftest import fixture

CASES = fixture("redact")["exitParity"]


def refs_exit(t):
    s = mask_names(t)
    return speak_masked(redact_text(s, extract_sensitive(s)))


@pytest.mark.parametrize("case", CASES, ids=[c["text"] for c in CASES])
def test_refs_exit_parity(case):
    out = refs_exit(case["text"])
    assert out == case["expected"], (case["text"], out)
    if case["expect"] == "mask":
        assert not re.search("[" + case["leak"] + "*＊]", out), (case["text"], out)
