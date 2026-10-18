"""personas.humanize：真人化后处理（零依赖，Python ≥ 3.9）。"""
from .core import BASE_RATES, MODES, OPS, PUNCT_STYLES, Humanizer, Result, digit_safe_positions, han_count, humanize, protected_mask
from .profiles import PERSONA_PROFILES, PROFILES, resolve

__all__ = ["BASE_RATES", "MODES", "OPS", "PUNCT_STYLES", "PERSONA_PROFILES", "PROFILES", "Humanizer", "Result",
           "digit_safe_positions", "han_count", "humanize", "protected_mask", "resolve"]
