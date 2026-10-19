"""通话环境底噪：按人设给输出音频混一层低音量的家庭/街道/店铺环境声，整通电话循环播放。

用 Pipecat 自带的 SoundfileMixer（输出传输层在没有语音时也会把底噪单独推出去），
只作用于发给对方的音频，不进 ASR，也不影响打断判断（打断看的是对方的麦克风）。
素材和授权见 voice/assets/ambience/SOURCES.md。

环境变量：
- DEEPSUCK_AMBIENCE：默认 1（按人设选）；0/off 关闭；kitchen/street/living_room/shop 强制用某一段。
- DEEPSUCK_AMBIENCE_VOLUME：混音系数，默认 0.2（素材 -26 dBFS，混进去约 -40 dBFS）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np

DIR = Path(__file__).resolve().parent / "assets" / "ambience"
SOUNDS = {name: DIR / f"{name}.ogg" for name in ("kitchen", "street", "living_room", "shop")}
DEFAULT_SOUND = "kitchen"


def _load_core() -> dict:
    import json
    try:
        core = Path(__file__).resolve().parents[1] / "site" / "assets" / "core" / "personas.json"
        return json.loads(core.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _suggested(data: dict) -> dict:
    """personas.json 每个人设的 ambience（底噪名）。只采用 SOUNDS 里有素材的名字，其余退回默认底噪。"""
    return {p["id"]: p["ambience"] for p in data.get("personas", []) if p.get("ambience") in SOUNDS}


_CORE = _load_core()
# 现为 wang → kitchen、chen → living_room、lin → street、zheng → shop；王阿姨的厨房底噪是已批准的质量线，不要改
BY_PERSONA = _suggested(_CORE)
ALIASES = dict(_CORE.get("aliases") or {})  # personas.json 的 aliases（xiaochen / mom → chen，shop_owner → zheng）
DEFAULT_VOLUME = 0.2
_OFF = ("0", "off", "false", "no", "none", "")


def choose(persona_id: str, env: Optional[str] = None) -> Optional[str]:
    """返回要用的底噪名，None 表示不混。"""
    v = (os.environ.get("DEEPSUCK_AMBIENCE", "1") if env is None else env).strip().lower()
    if v in _OFF:
        return None
    if v in SOUNDS:
        return v
    pid = str(persona_id or "")
    return BY_PERSONA.get(ALIASES.get(pid, pid), DEFAULT_SOUND)


def volume() -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get("DEEPSUCK_AMBIENCE_VOLUME", DEFAULT_VOLUME))))
    except ValueError:
        return DEFAULT_VOLUME


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def make_mixer(persona_id: str, env: Optional[str] = None):
    """返回 Pipecat 输出混音器；关闭、素材缺失或依赖不可用时返回 None（通话照常，只是没有底噪）。"""
    name = choose(persona_id, env)
    if name is None or not SOUNDS[name].exists():
        return None
    try:
        import soundfile as sf
        from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer
    except ImportError:
        return None

    class AmbienceMixer(SoundfileMixer):
        """SoundfileMixer 要求素材采样率等于输出采样率；这里加载时自动重采样，电话 8k/16k 也能用。"""

        def _load_sound_file(self, sound_name: str, file_name: str):
            x, sr = sf.read(file_name, dtype="float64")
            if x.ndim > 1:
                x = x.mean(axis=1)
            y = _resample(x, sr, self._sample_rate)
            self._sounds[sound_name] = np.clip(y * 32767, -32768, 32767).astype(np.int16)

    return AmbienceMixer(sound_files={name: str(SOUNDS[name])}, default_sound=name, volume=volume(), loop=True)
