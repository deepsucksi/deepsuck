"""personas.humanize：真人化后处理（零依赖，Python ≥ 3.9）。"""
from .core import BASE_RATES, MODES, OPS, Humanizer, Result, humanize
from .profiles import PROFILES

__all__ = ["BASE_RATES", "MODES", "OPS", "PROFILES", "Humanizer", "Result", "humanize"]
