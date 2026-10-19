"""通话留存：默认只保存脱敏后的文字记录，不保存任何原始音频。

- 文字记录：通话结束时写 Session.report()（与网页版导出同一格式）。转写和机器人回复进入会话时
  已经脱敏（Session.ingest / record_bot）；落盘前这里再对每条文字直接调用仓库共享的
  deepsuck.redact.redact_text(text, extract_sensitive(text))（见 docs/INTEL.md「脱敏接口」），
  voice/ 不另写任何脱敏规则。卡号等原值只在进程内存里，不会写进记录。
- 原始音频：仅当 KEEP_AUDIO=1 时保存（对方一路、机器人一路，各一个 WAV），
  保留 KEEP_AUDIO_DAYS 天，最多 7 天（超过按 7 处理）。
- 清理：服务启动时和之后每小时删除过期文件。KEEP_AUDIO 关掉后，之前留下的音频照样按期删除。

环境变量：
  DATA_DIR                    数据根目录（与预算账本共用）；未设时用 ~/.local/share/deepsuck
  VOICE_TRANSCRIPTS=1         是否保存脱敏文字记录（默认 1；0 关闭）
  VOICE_TRANSCRIPT_DAYS=30    文字记录保留天数（默认 30；0 表示不自动删除）
  KEEP_AUDIO=0                是否保存原始音频（默认 0）
  KEEP_AUDIO_DAYS=7           音频保留天数，1–7，超过按 7 处理
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional

from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

AUDIO_MAX_DAYS = 7
DEFAULT_TRANSCRIPT_DAYS = 30
CLEANUP_INTERVAL_SECS = 3600
_TZ = timezone(timedelta(hours=8))
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def data_root(env: Optional[Mapping[str, str]] = None) -> Path:
    base = _env(env).get("DATA_DIR") or str(Path.home() / ".local" / "share" / "deepsuck")
    return Path(base) / "voice"


def audio_dir(env=None) -> Path:
    return data_root(env) / "audio"


def transcript_dir(env=None) -> Path:
    return data_root(env) / "transcripts"


def keep_audio(env=None) -> bool:
    return _env(env).get("KEEP_AUDIO", "0").strip() == "1"


def audio_days(env=None) -> int:
    """音频保留天数：默认 7，夹在 1–7 之间；无法解析按 7。"""
    raw = _env(env).get("KEEP_AUDIO_DAYS", "").strip()
    try:
        d = int(float(raw)) if raw else AUDIO_MAX_DAYS
    except ValueError:
        d = AUDIO_MAX_DAYS
    return max(1, min(AUDIO_MAX_DAYS, d))


def transcripts_enabled(env=None) -> bool:
    return _env(env).get("VOICE_TRANSCRIPTS", "1").strip() != "0"


def transcript_days(env=None) -> int:
    raw = _env(env).get("VOICE_TRANSCRIPT_DAYS", "").strip()
    try:
        return max(0, int(float(raw))) if raw else DEFAULT_TRANSCRIPT_DAYS
    except ValueError:
        return DEFAULT_TRANSCRIPT_DAYS


def _stamp(now: Optional[float] = None) -> str:
    return datetime.fromtimestamp(now or time.time(), _TZ).strftime("%Y%m%d-%H%M%S")


def _safe(call_id: str) -> str:
    return _SAFE_ID.sub("_", str(call_id))[:64] or "call"


def _private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def save_transcript(session, call_id: str, channel: str, env=None, now: Optional[float] = None) -> Optional[Path]:
    """写脱敏文字记录（Session.report()）。关闭或会话为空时返回 None。"""
    if not transcripts_enabled(env) or not getattr(session, "messages", None):
        return None
    from deepsuck.extractors import extract_sensitive
    from deepsuck.redact import redact_dialog_segments, redact_text

    report = session.report()
    msgs = report.get("transcript", [])
    for m in msgs:
        t = m.get("text") or ""
        m["text"] = redact_text(t, extract_sensitive(t))
    # #92 / #120：验证码被 ASR 切成几段、或一方问验证码另一方报数字时连起来再判断；卡号片段、人设侧连续数字兜底
    for m, t in zip(msgs, redact_dialog_segments([m["text"] for m in msgs], [m.get("role") for m in msgs])):
        m["text"] = t
    report["channel"] = channel  # web / phone
    path = transcript_dir(env) / f"{_stamp(now)}-{channel}-{_safe(call_id)}.json"
    try:
        _private_write(path, json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as e:
        logger.warning(f"保存文字记录失败: {e}")
        return None
    return path


class AudioRecorder:
    """把一通电话两路音频分别写成 WAV（对方 *-in.wav，机器人 *-out.wav）。按首帧采样率建文件，
    之后采样率不同的帧丢弃（只记一次警告）。"""

    def __init__(self, call_id: str, env=None, now: Optional[float] = None):
        base = audio_dir(env) / f"{_stamp(now)}-{_safe(call_id)}"
        self.paths = {"in": base.with_name(base.name + "-in.wav"), "out": base.with_name(base.name + "-out.wav")}
        self._w: Dict[str, wave.Wave_write] = {}
        self._rate: Dict[str, int] = {}
        self._warned = set()
        self.closed = False

    def write(self, side: str, pcm: bytes, sample_rate: int, num_channels: int = 1) -> None:
        if self.closed or not pcm:
            return
        w = self._w.get(side)
        if w is None:
            p = self.paths[side]
            p.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            w = wave.open(os.fdopen(fd, "wb"), "wb")
            w.setnchannels(num_channels)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            self._w[side], self._rate[side] = w, sample_rate
        elif sample_rate != self._rate[side]:
            if side not in self._warned:
                self._warned.add(side)
                logger.warning(f"录音 {side} 采样率变化 {self._rate[side]}→{sample_rate}，丢弃不同采样率的帧")
            return
        w.writeframes(pcm)

    def close(self) -> None:
        self.closed = True
        for w in self._w.values():
            try:
                w.close()
            except Exception:
                pass
        self._w.clear()


class AudioTap(FrameProcessor):
    """管线里的录音点：side="in" 放在 transport.input() 之后，side="out" 放在 transport.output() 之前。"""

    def __init__(self, recorder: AudioRecorder, side: str, **kwargs):
        super().__init__(**kwargs)
        self.recorder, self.side = recorder, side

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if self.side == "in" and isinstance(frame, InputAudioRawFrame):
                self.recorder.write("in", frame.audio, frame.sample_rate, frame.num_channels)
            elif self.side == "out" and isinstance(frame, OutputAudioRawFrame):
                self.recorder.write("out", frame.audio, frame.sample_rate, frame.num_channels)
        await self.push_frame(frame, direction)


def recorder_for(call_id: str, env=None) -> Optional[AudioRecorder]:
    return AudioRecorder(call_id, env) if keep_audio(env) else None


def cleanup(env=None, now: Optional[float] = None) -> int:
    """删除过期的音频和文字记录，返回删除的文件数。按文件修改时间判断。"""
    now = now or time.time()
    removed = 0
    plans = [(audio_dir(env), audio_days(env), (".wav",))]
    td = transcript_days(env)
    if td > 0:
        plans.append((transcript_dir(env), td, (".json",)))
    for d, days, exts in plans:
        if not d.is_dir():
            continue
        cutoff = now - days * 86400
        for p in d.iterdir():
            try:
                if p.is_file() and p.suffix in exts and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError as e:
                logger.warning(f"清理 {p.name} 失败: {e}")
    if removed:
        logger.info(f"通话留存清理：删除 {removed} 个过期文件")
    return removed


async def cleanup_loop(interval: float = CLEANUP_INTERVAL_SECS, env=None) -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup, env)
        except Exception as e:
            logger.warning(f"通话留存清理失败: {e}")
        await asyncio.sleep(interval)


def describe(env=None) -> dict:
    """启动日志用：当前留存策略（不含任何内容）。"""
    return {"transcripts": transcripts_enabled(env), "transcriptDays": transcript_days(env),
            "keepAudio": keep_audio(env), "audioDays": audio_days(env), "dir": str(data_root(env))}
