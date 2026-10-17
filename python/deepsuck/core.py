"""加载共享规则数据 site/assets/core/*.json，并把 JS 正则源码转成 Python re。

查找顺序：环境变量 DEEPSUCK_CORE_DIR → 仓库内 site/assets/core（源码运行）→ 包内 _core/（打包安装时复制）。
"""
from __future__ import annotations

import functools
import json
import os
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def core_dir() -> Path:
    env = os.environ.get("DEEPSUCK_CORE_DIR")
    candidates = [Path(env)] if env else []
    candidates += [_HERE.parent.parent / "site" / "assets" / "core", _HERE / "_core"]
    for c in candidates:
        if (c / "extractors.json").is_file():
            return c
    raise FileNotFoundError("找不到 core/*.json，请设置 DEEPSUCK_CORE_DIR")


@functools.lru_cache(maxsize=None)
def load(name: str) -> dict:
    with open(core_dir() / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


_W = "A-Za-z0-9_"


def js_to_py(source: str) -> str:
    r"""把 JS 正则源码转成语义一致的 Python 源码。

    JS（无 u 标志）中 \d / \w 只匹配 ASCII，而 Python str 模式默认匹配 Unicode，
    所以显式改写为 [0-9] / [A-Za-z0-9_]（字符类内部直接展开）。\s 两边都是 Unicode 空白，保持不变。
    """
    out = []
    i, n, in_class = 0, len(source), False
    while i < n:
        c = source[i]
        if c == "\\" and i + 1 < n:
            nx = source[i + 1]
            if nx == "d":
                out.append("0-9" if in_class else "[0-9]")
            elif nx == "D":
                out.append("[^0-9]" if not in_class else "\\D")
            elif nx == "w":
                out.append(_W if in_class else f"[{_W}]")
            elif nx == "W":
                out.append(f"[^{_W}]" if not in_class else "\\W")
            elif nx == "/":
                out.append("/")
            else:
                out.append(source[i:i + 2])
            i += 2
            continue
        if c == "[" and not in_class:
            in_class = True
            out.append(c)
            # 字符类开头的 ] 或 ^] 在 JS 中含义不同，这里不使用，忽略
        elif c == "]" and in_class:
            in_class = False
            out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def compile_js(source: str, flags: str = "") -> re.Pattern:
    f = 0
    if "i" in flags:
        f |= re.IGNORECASE
    if "m" in flags:
        f |= re.MULTILINE
    if "s" in flags:
        f |= re.DOTALL
    return re.compile(js_to_py(source), f)


def utf16_len(s: str) -> int:
    """JS 字符串长度（UTF-16 码元数）。"""
    return len(s.encode("utf-16-le")) // 2
