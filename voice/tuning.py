"""延迟与打断相关的可调参数。网页（web）和电话（phone）各一套默认值，均可用环境变量覆盖。

环境变量名：网页 DEEPSUCK_LAT_<字段名大写>，电话 DEEPSUCK_PHONE_LAT_<字段名大写>，
例如 DEEPSUCK_LAT_FILLER_DELAY_MS=700、DEEPSUCK_PHONE_LAT_VAD_CONFIDENCE=0.8。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from typing import Mapping, Optional


@dataclass(frozen=True)
class LatencyProfile:
    name: str
    # ASR：句末静音多少毫秒判为一句结束（Paraformer max_sentence_silence，服务端默认约 800）
    asr_max_silence_ms: int
    # Silero VAD
    vad_confidence: float
    vad_start_secs: float
    vad_stop_secs: float
    vad_min_volume: float
    # 机器人说话时，用户至少说出几个有效汉字（去掉“嗯/对/好”等应答词）才算打断
    interrupt_min_chars: int
    # 用户停说后多少毫秒仍没有 LLM 首 token 就播填充语；<=0 关闭
    filler_delay_ms: int
    # 流式合成：一个分句至少攒几个字再送 TTS（遇到逗号等子句标点时）
    tts_clause_min_chars: int


WEB = LatencyProfile(name="web", asr_max_silence_ms=450, vad_confidence=0.75, vad_start_secs=0.3,
                     vad_stop_secs=0.2, vad_min_volume=0.6, interrupt_min_chars=2,
                     filler_delay_ms=650, tts_clause_min_chars=6)

# 电话线路：8k 窄带、底噪和回声更重，VAD 更保守、打断门槛更高、断句静音稍长
PHONE = LatencyProfile(name="phone", asr_max_silence_ms=500, vad_confidence=0.8, vad_start_secs=0.3,
                       vad_stop_secs=0.3, vad_min_volume=0.5, interrupt_min_chars=3,
                       filler_delay_ms=650, tts_clause_min_chars=6)

_DEFAULTS = {"web": WEB, "phone": PHONE}
_PREFIX = {"web": "DEEPSUCK_LAT_", "phone": "DEEPSUCK_PHONE_LAT_"}


def get_profile(name: str = "web", env: Optional[Mapping[str, str]] = None) -> LatencyProfile:
    """取一套参数并应用环境变量覆盖；无法解析的值忽略并保留默认。"""
    if name not in _DEFAULTS:
        raise ValueError(f"unknown latency profile: {name}")
    env = os.environ if env is None else env
    base = _DEFAULTS[name]
    over = {}
    for f in fields(base):
        if f.name == "name":
            continue
        raw = env.get(_PREFIX[name] + f.name.upper())
        if raw is None or raw == "":
            continue
        typ = type(getattr(base, f.name))
        try:
            over[f.name] = typ(float(raw)) if typ is int else typ(raw)
        except ValueError:
            continue
    return replace(base, **over)


def vad_params(p: LatencyProfile):
    from pipecat.audio.vad.vad_analyzer import VADParams

    return VADParams(confidence=p.vad_confidence, start_secs=p.vad_start_secs,
                     stop_secs=p.vad_stop_secs, min_volume=p.vad_min_volume)
