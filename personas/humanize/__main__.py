"""命令行：python -m personas.humanize "你说的是哪个银行？" --intensity 0.5 --seed 1 [--profile retiree]"""
from __future__ import annotations

import argparse
import json
import sys

from . import PROFILES, Humanizer
from .confusion import DIALECT


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m personas.humanize", description="真人化后处理")
    ap.add_argument("text", nargs="?", help="要处理的文本；省略时从标准输入逐行读取")
    ap.add_argument("--intensity", type=float, default=None, help="0–1，默认 0.3 或预设值")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--mode", choices=["chat", "voice"], default=None)
    ap.add_argument("--dialect", choices=sorted(DIALECT), default=None)
    ap.add_argument("--profile", choices=sorted(PROFILES), default=None)
    ap.add_argument("--context", default=None, help="对方上一条消息（用于重复确认）")
    ap.add_argument("-n", type=int, default=1, help="同一条文本生成几个变体")
    ap.add_argument("--json", action="store_true", help="输出 JSON（含生效的操作）")
    a = ap.parse_args(argv)
    h = Humanizer(a.intensity, a.seed, mode=a.mode, dialect=a.dialect, profile=a.profile)
    lines = [a.text] if a.text is not None else [x.rstrip("\n") for x in sys.stdin]
    for line in lines:
        for _ in range(a.n):
            r = h.apply(line, a.context)
            print(json.dumps({"text": r.text, "ops": r.ops}, ensure_ascii=False) if a.json else r.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
