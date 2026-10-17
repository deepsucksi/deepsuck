"""DeepSuck Python core — 与浏览器端 JS 实现共用 site/assets/core/*.json 规则。

非官方项目，与 DeepSeek 无关 · Apache-2.0
"""
from .normalize import normalize
from .redact import mask, redact_text
from .extractors import extract, extract_sensitive, luhn
from .tactics import classify, risk_score
from .engine import Session

__version__ = "0.3.0"
__all__ = [
    "normalize", "mask", "redact_text", "extract", "extract_sensitive", "luhn",
    "classify", "risk_score", "Session", "__version__",
]
