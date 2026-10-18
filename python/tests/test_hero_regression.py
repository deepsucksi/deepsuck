"""回归：首页示例对话（corpus/examples/hero_rewrite.json，由语料与人设维护、会随时更新）。

动态读取该文件，只依赖 scripts[].after.lines 里的 r（骗子）/ s（人设）/ i（打码情报）三个字段，
不硬编码句子、条数或类型。检查：
  1. 每条带 i 的骗子台词：i 里的每个打码情报都出现在台词里；把打码值还原成一个虚构完整值后，
     提取器能识别出对应类型，且按同一打码规则得到的打码值与 i 一致；人设真人化噪声下仍能识别；
  2. 骗子台词能被话术分类器识别出至少一种话术；把“账”换成“帐”等异体字、或经 personas.humanize 真人化后，识别结果基本不变；
  3. 人设台词不含任何未打码的敏感值。
"""
import json
import re
import sys
from pathlib import Path

import pytest

from deepsuck.extractors import LABELS, extract
from deepsuck.normalize import luhn
from deepsuck.redact import mask
from deepsuck.tactics import classify

ROOT = Path(__file__).resolve().parents[2]
HERO = ROOT / "corpus" / "examples" / "hero_rewrite.json"
sys.path.insert(0, str(ROOT))
from personas.humanize import Humanizer  # noqa: E402

# i 标签 → 提取器类型：先按 core 的 LABELS 模糊匹配，再用常见简称兜底
ALIAS = {"APP": "app_name", "平台": "app_name", "银行卡": "bank_card", "卡号": "bank_card", "户名": "name", "收款人": "name", "电话": "phone", "手机": "phone",
         "手机号": "phone", "网址": "url", "链接": "url", "微信": "wechat", "QQ": "qq", "钱包": "crypto_tron"}


def label_type(label):
    for t, l in LABELS.items():
        if label == l or (len(label) >= 2 and label in l):
            return t
    return ALIAS.get(label)


def lines():
    data = json.loads(HERO.read_text(encoding="utf-8"))
    out = []
    for s in data.get("scripts", []):
        for ln in (s.get("after") or {}).get("lines", []):
            out.append({k: ln[k] for k in ("r", "s", "i") if k in ln})
    return out


def intel_items(i):
    for part in re.split(r"\s*·\s*", i):
        m = re.match(r"^(\S+)\s+(\S+)$", part.strip())
        if m:
            yield m.group(1), m.group(2)


def demask(t, masked):
    """把打码值还原成一个虚构完整值（只用于测试）；不支持的类型返回 None。"""
    if t == "name":
        return masked.replace("*", "某")
    if t == "phone":
        return masked.replace("*", "0")
    if t == "url":
        return masked.replace("*", "a")
    if t == "app_name":
        return masked
    if t == "bank_card":
        for d in "0123456789":
            v = masked.replace("*", d, 1).replace("*", "0")
            if luhn(v):
                return v
        return masked.replace("*", "0")
    return None


R_LINES = [l for l in lines() if "r" in l]
I_LINES = [l for l in R_LINES if l.get("i")]
S_LINES = [l for l in lines() if "s" in l]


def test_file_has_content():
    assert R_LINES and I_LINES and S_LINES


def _restore(text, items):
    out, want = text, []
    for label, masked in items:
        t = label_type(label)
        assert t, f"无法识别情报标签：{label}"
        assert masked in text, f"台词里没有打码值 {masked}：{text}"
        v = demask(t, masked)
        if v is None:
            continue
        out = out.replace(masked, v, 1)
        want.append((t, masked))
    return out, want


def _found(text, want):
    got = {(e["type"], e["masked"]) for e in extract(text)}
    return [w for w in want if w not in got]


@pytest.mark.parametrize("ln", I_LINES, ids=lambda l: l["r"][:20])
def test_masked_intel_recognized(ln):
    text, want = _restore(ln["r"], list(intel_items(ln["i"])))
    assert want, ln
    for t, masked in want:
        if t != "app_name":  # APP 名不是敏感值，不打码
            assert mask(t, demask(t, masked)) == masked
    assert _found(text, want) == [], text


def test_masked_intel_recognized_under_humanize_noise():
    total = miss = 0
    for ln in I_LINES:
        text, want = _restore(ln["r"], list(intel_items(ln["i"])))
        for seed in range(20):
            for mode in ("chat", "voice"):
                noisy = Humanizer(0.6, seed, mode=mode)(text)
                total += len(want)
                miss += len(_found(noisy, want))
    assert total and miss / total <= 0.02, (miss, total)


def test_scammer_lines_tactics_recognized_and_stable():
    base = {l["r"]: {t["id"] for t in classify(l["r"])} for l in R_LINES}
    assert sum(1 for v in base.values() if v) / len(base) >= 0.6, base
    # 异体字：账 → 帐 / 賬，戶 → 户 之类不应改变识别结果
    for r, ids in base.items():
        for a, b in (("账", "帐"), ("户", "戶"), ("账", "賬")):
            if a in r:
                assert {t["id"] for t in classify(r.replace(a, b))} == ids, r
    # 人设真人化噪声：话术识别召回不低于 90%
    hit = tot = 0
    for r, ids in base.items():
        if not ids:
            continue
        for seed in range(20):
            got = {t["id"] for t in classify(Humanizer(0.6, seed, mode="chat")(r))}
            tot += len(ids)
            hit += len(ids & got)
    assert tot and hit / tot >= 0.9, (hit, tot)


def test_persona_lines_leak_nothing():
    for ln in S_LINES:
        for e in extract(ln["s"]):
            if e.get("sensitive"):
                assert "*" in e["masked"] and e["value"] == e["masked"] or e["type"] == "name", (ln["s"], e)
