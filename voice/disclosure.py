"""开场 AI 告知语（网页和电话入口共用）。默认不播。

  VOICE_AI_DISCLOSURE=1             开启：在开场白之前先播一句告知语
  VOICE_AI_DISCLOSURE_TEXT=...      自定义文案（默认“本通话由智能助理接听。”）

旧变量 VOICE_TELEPHONY_DISCLOSURE 已停用（它默认开启且只对电话生效），设置了也会被忽略并记一条警告。
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from loguru import logger

DEFAULT_TEXT = "本通话由智能助理接听。"
_warned = False


def disclosure_text(env: Optional[Mapping[str, str]] = None) -> str:
    """应播的告知语；关闭时返回空串。"""
    global _warned
    env = os.environ if env is None else env
    if env.get("VOICE_TELEPHONY_DISCLOSURE") and not _warned:
        _warned = True
        logger.warning("VOICE_TELEPHONY_DISCLOSURE 已停用，请改用 VOICE_AI_DISCLOSURE=1 和 VOICE_AI_DISCLOSURE_TEXT")
    if env.get("VOICE_AI_DISCLOSURE", "0").strip().lower() not in ("1", "true", "yes", "on"):
        return ""
    return (env.get("VOICE_AI_DISCLOSURE_TEXT") or "").strip() or DEFAULT_TEXT
