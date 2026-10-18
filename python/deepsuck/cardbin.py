"""银行卡 BIN 本地查询（与 site/assets/js/cardbin.js 等价）。

数据：site/assets/core/cardbin.json，来自 hexindai/bcbc（MIT），由 scripts/fetch-cardbin.js 生成。
只按卡号前缀判断发卡行与卡种，不联网、卡号不外传；BIN 表并非官方注册表，结果仅供参考。
用法：python -m deepsuck.cardbin <卡号>   （只输出发卡行信息，不回显卡号）
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional

from .core import load

_C = load("cardbin")
BINS = _C["bins"]
BANKS = _C["banks"]
TYPES = _C["types"]
SOURCE = _C["source"]


def _info(bin_: str, opt: list, length: int) -> dict:
    return {
        "bin": bin_, "bankCode": opt[0], "bank": BANKS.get(opt[0], opt[0]), "cardType": opt[1],
        "cardTypeName": TYPES.get(opt[1], opt[1]), "length": opt[2], "lengthOk": opt[2] == length,
    }


def lookup(card_no: Optional[str]) -> Optional[dict]:
    """lookup(card_no) -> {bin, bankCode, bank, cardType, cardTypeName, length, lengthOk} | None"""
    d = re.sub(r"[^0-9]", "", str(card_no or ""))
    if len(d) < 12:
        return None
    fallback = None
    for n in range(min(10, len(d)), 2, -1):
        p = d[:n]
        opts = BINS.get(p)
        if not opts:
            continue
        for o in opts:
            if o[2] == len(d):
                return _info(p, o, len(d))
        if fallback is None:
            fallback = _info(p, opts[0], len(d))
    return fallback


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法：python -m deepsuck.cardbin <卡号>", file=sys.stderr)
        return 2
    r = lookup(argv[0])
    out = {k: v for k, v in (r or {}).items() if k != "bin"}  # 不回显卡号前缀
    print(json.dumps(out or None, ensure_ascii=False))
    print(f"数据：{SOURCE['name']}（{SOURCE['license']}）{SOURCE['homepage']}；仅供参考，非官方注册表。", file=sys.stderr)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(main())
