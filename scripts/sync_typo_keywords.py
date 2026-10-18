#!/usr/bin/env python3
"""从 personas/humanize/confusion.py（语料与人设维护的混淆表，只读）生成提取器 / 分类器用的关键词错别字归一化表，
写入 site/assets/core/extractors.json 的 obfuscation.typoKeywords（错写 → 正写，等长，JS 与 Python 共用）；
同样的方法给跨回合拼接的屏蔽词（stitch.blockBefore / blockAfter 里的“房间、工号、订单号…”）生成 stitch.blockTypos
（“房问号”“工好”这类手写错字仍能挡住拼接），只在拼接器判断屏蔽词时使用，不参与通用规范化。

不另写一套混淆表：同音整词（HOMOPHONE_WORDS、COMMON_WORDS、PLACE_WORDS）、同音单字（HOMOPHONE_CHARS）、形近字（SHAPE_CHARS、
手写档的 HANDWRITING_CHARS）全部来自 personas（数据在 site/assets/core/personas.json 的 humanize.confusion）。
词表 = 提取器规则里的中文关键词 + tactics.json 话术规则里的纯中文字面词。只收：
  - 与正写等长（保证规范化前后位置一一对应，脱敏区间不变）；
  - 错写本身不是词表里的另一个词；同一个错写对应多个正写时丢弃。
用法：python3 scripts/sync_typo_keywords.py [--check]
Apache-2.0
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from personas.humanize import confusion as C  # noqa: E402

CORE = ROOT / "site" / "assets" / "core"
CJK_WORD = re.compile(r"^[\u4e00-\u9fa5]{2,8}$")
# 虚词/代词之间的单字混淆（的/得/地、在/再…）在两字词上太容易误伤正常句子（“中的”→“中得”），不收
PARTICLES = set("的得地在再那哪吗嘛么吧把他她以已")


def literals(pattern: str):
    """取正则里 | 分隔的、纯中文的字面量分支（去掉分组括号），复杂分支直接忽略。"""
    out = []
    for part in re.split(r"[|()]", pattern.replace("(?:", "(")):
        part = part.strip()
        if CJK_WORD.match(part):
            out.append(part)
    return out


def vocabulary() -> list:
    ex = json.loads((CORE / "extractors.json").read_text(encoding="utf-8"))
    tac = json.loads((CORE / "tactics.json").read_text(encoding="utf-8"))
    words = set()
    for p in ex["patterns"].values():
        words.update(literals(p["source"]))
    words.update(w for w in ex["banks"] + ex["channels"] + ex["obfuscation"]["spaceInsideKeywords"] if CJK_WORD.match(w))
    words.update(["卡号", "银行卡", "账号", "账户", "电话", "手机", "号码", "手机号", "钱包", "地址", "网址", "验证码", "收款", "转账", "身份证", "下载"])
    for t in tac["tactics"]:
        words.update(literals(t["pattern"]))
    return sorted(words)


def block_vocabulary() -> list:
    ex = json.loads((CORE / "extractors.json").read_text(encoding="utf-8"))
    st = ex.get("stitch") or {}
    words = set()
    for k in ("blockBefore", "blockAfter"):
        words.update(literals(st.get(k, "")))
    return sorted(words)


def build(vocab=None) -> dict:
    vocab = vocabulary() if vocab is None else vocab
    vs = set(vocab)
    cand: dict = {}
    for v in vocab:
        for w, alts in list(C.HOMOPHONE_WORDS.items()) + list(C.COMMON_WORDS.items()) + list(C.PLACE_WORDS.items()):
            if w in v:
                for a in alts:
                    if len(a) == len(w):
                        cand.setdefault(v.replace(w, a), set()).add(v)
        for i, ch in enumerate(v):
            for a in list(C.HOMOPHONE_CHARS.get(ch, ())) + list(C.SHAPE_CHARS.get(ch, ())) + list(C.HANDWRITING_CHARS.get(ch, ())):
                if len(a) == 1 and not (len(v) <= 2 and (ch in PARTICLES or a in PARTICLES)):
                    cand.setdefault(v[:i] + a + v[i + 1:], set()).add(v)
    out = {}
    for bad, goods in sorted(cand.items()):
        if bad in vs or len(goods) != 1:
            continue
        good = next(iter(goods))
        if bad != good and len(bad) == len(good):
            out[bad] = good
    return out


def main(argv=None) -> int:
    check = "--check" in (argv or sys.argv[1:])
    path = CORE / "extractors.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    table = build()
    block = build(block_vocabulary())
    cur = data["obfuscation"].get("typoKeywords", {}).get("map")
    cur_block = (data.get("stitch") or {}).get("blockTypos", {}).get("map")
    if check:
        if cur != table or cur_block != block:
            print("typoKeywords / blockTypos 过期：运行 python3 scripts/sync_typo_keywords.py && npm run build:core && npm run fixtures", file=sys.stderr)
            return 1
        return 0
    data["stitch"]["blockTypos"] = {
        "comment": "拼接屏蔽词的错别字变体（错写 → 正写，等长）。由 scripts/sync_typo_keywords.py 从 personas 混淆表生成，请勿手改；只在判断 blockBefore / blockAfter 时替换。",
        "map": block,
    }
    data["obfuscation"]["typoKeywords"] = {
        "comment": "关键词错别字归一化（错写 → 正写，等长）。由 scripts/sync_typo_keywords.py 从 personas/humanize/confusion.py 生成，请勿手改。",
        "map": table,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"typoKeywords: {len(table)} 条，blockTypos: {len(block)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
