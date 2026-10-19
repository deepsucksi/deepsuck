"""#185 共用字表 site/assets/core/name_stopchars.json 的格式检查（与 tests/name_stopchars.test.js 一致）。"""
from deepsuck.core import load


def test_name_stopchars_format():
    s = load("name_stopchars")
    assert s["schema"] == "deepsuck.core.name_stopchars/v1"
    assert "用途" in s["comment"]
    chars = [r["char"] for r in s["chars"]]
    assert len(chars) == len(set(chars))
    surnames = load("extractors")["nameRules"]["surnames"]
    for r in s["chars"]:
        assert len(r["char"]) == 1 and "\u4e00" <= r["char"] <= "\u9fa5"
        assert r["char"] not in surnames
        assert r["negatives"] and all(r["char"] in t for t in r["negatives"])
    for c in "对是嗯好行哦有没只":
        assert c in chars
