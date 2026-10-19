"""#194：deepsuck.llmfilter 与 site/assets/js/llm.js sanitizeReply 共用用例 tests/fixtures/llm_sanitize.json。"""
import json
from pathlib import Path

from deepsuck.llmfilter import fix_quotes, llm_pipeline, sanitize_reply

FIX = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/llm_sanitize.json").read_text(encoding="utf-8"))


def test_cases():
    for c in FIX["cases"]:
        assert sanitize_reply(c["text"]) == c["expected"], c["text"]
        assert sanitize_reply(sanitize_reply(c["text"])) == c["twice"], c["text"]


def test_pipeline():
    for c in FIX["pipeline"]:
        assert llm_pipeline(c["text"], c["recent"], c["persona"]) == c["expected"], c["text"]


def test_fix_quotes():
    assert fix_quotes("你说“退款”啊") == "你说“退款”啊"
    assert fix_quotes("单边”") == "单边"
