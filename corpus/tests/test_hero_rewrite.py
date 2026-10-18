import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_hero_rewrite", ROOT / "corpus/examples/build_hero_rewrite.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

DATA = json.loads(B.OUT.read_text(encoding="utf-8"))
MASKED = re.compile(r"\d[\d*]*\*+[\d*]*\d|\d{3}\*+\d{4}")


def test_json_is_up_to_date_and_deterministic():
    assert B.dump(B.build()) == B.OUT.read_text(encoding="utf-8")
    assert B.dump(B.build()) == B.dump(B.build())


def test_before_is_fixed_baseline():
    """改写前取自固定基准文件（首页原版），不读 hero-chat.js 的当前内容。"""
    base = B.load_baseline()
    assert [s["title"] for s in base] == ["冒充公检法 · 王阿姨", "刷单返利 · 小林", "冒充领导 · 李大爷"]
    assert base == [s["before"] for s in DATA["scripts"]]
    meta = json.loads(B.BASELINE.read_text(encoding="utf-8"))
    assert meta["source_commit"] == B.BASELINE_REV and meta["source_file"] == "site/assets/js/hero-chat.js"


def test_baseline_matches_git_history_when_available():
    import subprocess
    try:
        src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{B.BASELINE_REV}:site/assets/js/hero-chat.js"],
                                      text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git history not available (shallow checkout)")
    assert B.parse_scripts_js(src) == B.load_baseline()


def test_current_hero_chat_field_names():
    """只检查当前 hero-chat.js SCRIPTS 的字段名（内容会随网站更新而变，不做比较）。"""
    hero = B.parse_hero_js()
    assert hero
    assert {k for sc in hero for k in sc} <= {"title", "source", "lines"}
    assert {k for sc in hero for ln in sc["lines"] for k in ln} <= B.LINE_KEYS


def test_parser_handles_both_quote_styles():
    src = "var SCRIPTS = [\n    { title: '甲 · 乙', lines: [ { r: 'a\"b' }, {\"s\": \"c'd\", \"w\": 3} ] }\n  ];"
    assert B.parse_scripts_js(src) == [{"title": "甲 · 乙", "lines": [{"r": 'a"b'}, {"s": "c'd", "w": 3}]}]


def test_after_matches_scripts_structure():
    """after 段严格按 hero-chat.js SCRIPTS：title / source / lines；r 或 s 二选一，可选 t/i/w。"""
    base_line_keys = {k for sc in B.load_baseline() for ln in sc["lines"] for k in ln}
    assert base_line_keys == B.LINE_KEYS  # 原版 SCRIPTS 的真实字段名
    for s in DATA["scripts"]:
        after = s["after"]
        assert list(after) == ["title", "source", "lines"]
        assert re.fullmatch(r"[^·]+ · [^·]+", after["title"])
        kind, name = after["title"].split(" · ")
        assert kind == s["before"]["title"].split(" · ")[0]
        assert name == B.P_NAMES[s["persona"]]
        assert B.validate_script(after) == []
        assert 4 <= len(after["lines"]) <= 6
        for ln in after["lines"]:
            assert set(ln) <= {"r", "s", "t", "i", "w"} and (("r" in ln) != ("s" in ln))
            text = ln.get("r") or ln.get("s")
            assert 0 < len(text) <= 40, text
            if "w" in ln:
                assert isinstance(ln["w"], int) and ln["w"] > 0
        # 骗子、人设交替，骗子先说
        assert ["r" if "r" in ln else "s" for ln in after["lines"]] == ["r", "s"] * (len(after["lines"]) // 2)


def test_source_matches_corpus_scripts():
    yaml = pytest.importorskip("yaml")
    for s in DATA["scripts"]:
        raw = yaml.safe_load((ROOT / "corpus/scripts" / f"{s['script']}.yaml").read_text(encoding="utf-8"))["source"]
        assert "公开反诈宣传" in raw and s["after"]["source"] == "据公开反诈宣传改写"
        assert s["rewritten"]["source"] == s["after"]["source"]


def test_intel_is_masked():
    for s in DATA["scripts"]:
        for ln in s["after"]["lines"]:
            if "i" not in ln:
                continue
            assert B.intel_problems(ln["i"]) == [], ln["i"]
            for item in ln["i"].split("·"):
                item = item.strip()
                if item.startswith(("银行卡", "电话", "户名", "网址")):
                    assert "*" in item, item
    assert B.intel_problems("银行卡 6222021234567890") and B.intel_problems("户名 王伟")


def test_validator_rejects_bad_scripts():
    good = DATA["scripts"][0]["after"]
    assert B.validate_script(good) == []
    too_long = {**good, "lines": [{"r": "长" * 41}] + good["lines"][1:]}
    assert any("chars" in e for e in B.validate_script(too_long))
    both = {**good, "lines": [{"r": "a", "s": "b"}] + good["lines"][1:]}
    assert B.validate_script(both)
    few = {**good, "lines": good["lines"][:3]}
    assert B.validate_script(few)
    many = {**good, "lines": good["lines"] + good["lines"][:1]}
    assert B.validate_script(many)
    no_source = {k: v for k, v in good.items() if k != "source"}
    assert B.validate_script(no_source)
    bad_title = {**good, "title": "周伯"}
    assert B.validate_script(bad_title)
    unmasked = {**good, "lines": [{**good["lines"][0], "i": "电话 13900112233"}] + good["lines"][1:]}
    assert any("unmasked" in e for e in B.validate_script(unmasked))


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


def test_persona_names_match_prompts():
    yaml = pytest.importorskip("yaml")
    for pid, name in B.P_NAMES.items():
        assert yaml.safe_load((ROOT / "personas/prompts" / f"{pid}.yaml").read_text(encoding="utf-8"))["name"] == name


def test_no_deliberate_typos_in_output_or_tables():
    from personas.humanize import confusion as C
    forms = {w for alts in list(C.HOMOPHONE_WORDS.values()) + list(C.HOMOPHONE_CHARS.values())
             + list(C.SHAPE_CHARS.values()) for w in alts}
    assert not forms & set(C.DELIBERATE)
    for s in DATA["scripts"]:
        for ln, raw in zip(s["after"]["lines"], s["rewritten"]["lines"]):
            text, src = ln.get("r") or ln.get("s"), raw.get("r") or raw.get("s")
            for w in ("神马", "孩纸", "好滴", "手鸡"):
                assert w not in text
            assert text.count("前") <= src.count("前")
