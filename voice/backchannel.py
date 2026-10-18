"""短口头语（backchannel）：对方说完后先用预合成音频应一声"嗯……""啊？你说啥"。

- 选择规则（skip_reason）：对方这一回合的话很短、在催促、或是很短的追问时不说；规则只看文本，简单可测。
- 轮换（Backchannel）：每回合最多一条，随机挑选，和上一回合播过的那条不重复；只从已合成好的音频里挑。
- 音频缓存：按 音色/采样率/文本 缓存到 DATA_DIR/voice/fillers（未设 DATA_DIR 时用 ~/.cache/deepsuck/voice），
  并在进程内存里留一份；载入时裁掉首尾静音，保证播放即出声。

开关：DEEPSUCK_BACKCHANNEL（默认 1）。关掉后回到旧行为：停说 filler_delay_ms 后仍无 LLM 首 token 才插播填充音。
"""
from __future__ import annotations

import os
import random
import re
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

# 催促/确认对方在不在：这时候应该直接回话，不再"嗯……"拖一下
URGE_WORDS = ("快点", "快一点", "赶紧", "抓紧", "听到没", "听到了吗", "听见没", "听见了吗", "在吗", "在不在",
              "喂喂", "说话", "人呢", "怎么不说话", "能听到吗")
MIN_CHARS = 4          # 有效字数少于这个算"话很短"（"喂""对""好的"）
FOLLOWUP_MAX = 8       # 以问号/吗/呢结尾且有效字数不超过这个，算追问（"是不是？""对吧？"）
_CONTENT = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_Q_END = re.compile(r"(?:[?？]|[吗呢嘛])\s*[。.!！…]*\s*$")


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return (env.get("DEEPSUCK_BACKCHANNEL", "1") or "1").strip().lower() not in ("0", "false", "off", "no")


def skip_reason(text: str) -> Optional[str]:
    """不该应声时返回原因（short / urge / followup），否则 None。"""
    t = (text or "").strip()
    n = len(_CONTENT.findall(t))
    if n < MIN_CHARS:
        return "short"
    if any(w in t for w in URGE_WORDS):
        return "urge"
    if n <= FOLLOWUP_MAX and _Q_END.search(t):
        return "followup"
    return None


class Backchannel:
    """一通电话一个实例。IntelProcessor 拿到转写时 note()，FillerProcessor 在回合结束时 take()。"""

    def __init__(self, available: Callable[[], Iterable[str]], rng: Callable[[], float] = random.random):
        self.available = available
        self.rng = rng
        self.last: Optional[str] = None   # 上一次真正播出的那条
        self.played = 0
        self.skipped = 0
        self.reset()

    def reset(self):
        """新的用户回合开始。"""
        self._texts: list = []
        self._line: Optional[str] = None
        self._reason: Optional[str] = None
        self._taken = False

    def _pick(self) -> Optional[str]:
        keys = sorted(set(self.available()))
        if self.last in keys and len(keys) > 1:
            keys.remove(self.last)
        if not keys:
            return None
        return keys[int(self.rng() * len(keys)) % len(keys)]

    def note(self, text: str) -> Optional[str]:
        """记下本回合的一段转写，返回本回合打算说的口头语（None = 不说）。同一回合内挑中的那条不变。
        上一回合已结束（take/discard 过）时自动开始新回合——不依赖 UserStartedSpeakingFrame 的先后
        （用转写触发回合开始时，开始帧会晚于转写）。Pipecat 默认的回合结束策略要等到转写，所以转写总在结束前。"""
        if self._taken:
            self.reset()
        self._texts.append(text or "")
        self._reason = skip_reason("".join(self._texts))
        if self._reason is None and self._line is None:
            self._line = self._pick()
        return None if self._reason else self._line

    def take(self) -> Optional[str]:
        """回合结束时取出要播的口头语并记为已播（每回合只取一次）；还没收到转写时也照常挑一条。"""
        if self._taken:
            return None
        self._taken = True
        if self._reason:
            self.skipped += 1
            self._line = None
        else:
            if self._line is None:
                self._line = self._pick()
            if self._line is not None and self._line not in set(self.available()):
                self._line = None
        if self._line is not None:
            self.last = self._line
            self.played += 1
        return self._line

    def discard(self):
        """回合结束但不播（机器人正在说话等）：结束本回合，不计入"上一条"。"""
        self._taken = True
        self._line = None


def cache_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    if env.get("DEEPSUCK_FILLER_CACHE_DIR"):
        return Path(env["DEEPSUCK_FILLER_CACHE_DIR"])
    if env.get("DATA_DIR"):
        return Path(env["DATA_DIR"]) / "voice" / "fillers"
    return Path(env.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "deepsuck" / "voice"


def trim_silence(pcm: bytes, sample_rate: int, *, threshold: int = 500, keep_ms: int = 20) -> bytes:
    """裁掉 16-bit 单声道 PCM 首尾低于阈值的静音（CosyVoice 合成结果开头常带 300ms 左右静音），两端各留 keep_ms。"""
    import numpy as np

    if len(pcm) < 4:
        return pcm
    a = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
    loud = np.flatnonzero(np.abs(a.astype(np.int32)) >= threshold)
    if loud.size == 0:
        return b""
    pad = int(sample_rate * keep_ms / 1000)
    lo, hi = max(0, int(loud[0]) - pad), min(a.size, int(loud[-1]) + 1 + pad)
    return a[lo:hi].tobytes()
