import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_hero_rewrite", ROOT / "corpus/examples/build_hero_rewrite.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

DATA = json.loads(B.OUT.read_text(encoding="utf-8"))
MASKED = re.compile(r"\d[\d*]*\*+[\d*]*\d|\d{3}\*+\d{4}")


def test_json_is_up_to_date_and_deterministic():
    assert B.dump(B.build()) == B.OUT.read_text(encoding="utf-8")
    assert B.dump(B.build()) == B.dump(B.build())


def test_before_matches_current_hero_chat():
    hero = B.parse_hero_js()
    assert [s["title"] for s in hero] == [s["before"]["title"] for s in DATA["scripts"]]
    assert hero == [s["before"] for s in DATA["scripts"]]


def test_after_is_drop_in_format():
    allowed = {"r", "s", "t", "i", "w"}
    for s in DATA["scripts"]:
        after = s["after"]
        assert set(after) == {"title", "lines"} and after["title"].endswith(s["after"]["title"].split(" · ")[-1])
        assert len(after["lines"]) >= 4
        for ln in after["lines"]:
            assert set(ln) <= allowed and (("r" in ln) != ("s" in ln))
            assert isinstance(ln.get("w", 0), int)
        # 骗子、人设交替，骗子先说
        assert ["r" if "r" in ln else "s" for ln in after["lines"]] == ["r", "s"] * (len(after["lines"]) // 2)


def test_humanize_touched_enough_lines_overall():
    changed = sum(ln_a != ln_r for s in DATA["scripts"] for ln_a, ln_r in zip(s["after"]["lines"], s["rewritten"]["lines"]))
    assert changed >= 6


def test_both_sides_rewritten_and_humanized():
    for s in DATA["scripts"]:
        before = [ln.get("r") or ln.get("s") for ln in s["before"]["lines"]]
        rewritten = [ln.get("r") or ln.get("s") for ln in s["rewritten"]["lines"]]
        after = [ln.get("r") or ln.get("s") for ln in s["after"]["lines"]]
        assert not set(rewritten) & set(before)
        assert any("r" in ln and ln["r"] not in before for ln in s["rewritten"]["lines"])
        assert sum(a != b for a, b in zip(after, rewritten)) >= 1
        assert s["persona"] in ("retiree", "mom", "graduate", "shop_owner")
        assert (ROOT / "corpus/scripts" / f"{s['script']}.yaml").exists()


def test_intel_values_preserved_and_no_new_numbers():
    for s in DATA["scripts"]:
        orig = set(MASKED.findall(json.dumps(s["before"], ensure_ascii=False)))
        for ln in s["after"]["lines"]:
            text = ln.get("r") or ln.get("s")
            for m in MASKED.findall(text):
                assert m in orig, m
            assert not re.search(r"(?<![\d*])\d{6,}(?![\d*])", text), text
            if ln.get("i"):
                for m in MASKED.findall(ln["i"]):
                    assert m in text, (m, text)
        before_intel = set(MASKED.findall(" ".join(ln.get("i", "") for ln in s["before"]["lines"])))
        after_intel = set(MASKED.findall(" ".join(ln.get("i", "") for ln in s["after"]["lines"])))
        assert before_intel <= after_intel


def test_realism_doc_section_matches():
    doc = (ROOT / "docs/REALISM.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- hero-rewrite:begin[^>]*-->\n(.*?)<!-- hero-rewrite:end -->", doc, re.S)
    assert m
    assert m.group(1).strip() == B.markdown(DATA).strip()
    assert "## 一、文字打字特征" in doc and "## 二、语音说话特征" in doc and "## 三、对比" in doc


def test_check_mode():
    assert B.main(["--check"]) == 0
