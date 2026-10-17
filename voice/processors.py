"""语音管线里的 DeepSuck 处理器：

- GuardTextFilter：TTS 前的输出守卫（去 Markdown/括号动作、脱敏、抹长数字串）。
- IntelProcessor：对骗子语音转写做实时情报抽取 + 话术识别 + 黑名单比对，按规则引擎选出本轮策略
  并改写 LLM 系统提示词；插播拖延填充音；rule 模式下直接用规则引擎回复（不调用大模型）。
- BotTextTap：收集大模型整句回复，记入会话并推送到浏览器面板。

浏览器面板通过 notify(dict) 回调收消息（SmallWebRTC 数据通道 app message）。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.base_text_filter import BaseTextFilter

from .persona import FILLERS, guard_output, speakable, system_prompt

Notify = Callable[[dict], Awaitable[None]]

GOAL_LABEL = {"bank": "收款银行卡号", "wallet": "加密钱包地址", "phone": "联系电话", "url": "网址/下载链接", "name": "收款人姓名"}


async def _noop(_msg: dict) -> None:
    return None


class GuardTextFilter(BaseTextFilter):
    async def update_settings(self, settings):  # 无可调参数
        return None

    async def filter(self, text: str) -> str:
        return speakable(text)

    async def handle_interruption(self):
        return None

    async def reset_interruption(self):
        return None


class IntelProcessor(FrameProcessor):
    """放在 STT 之后、用户上下文聚合器之前。"""

    def __init__(self, session, *, context=None, notify: Optional[Notify] = None, mode: str = "llm",
                 fillers: Optional[Dict[str, bytes]] = None, filler_rate: int = 16000,
                 filler_prob: float = 0.6, blocklist=None, rng=None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.context = context
        self.notify = notify or _noop
        self.mode = mode
        self.fillers = fillers or {}
        self.filler_rate = filler_rate
        self.filler_prob = filler_prob
        self.blocklist = blocklist
        self.rng = rng or random.random
        self.intent = "opening"
        self._bl_tasks: List[asyncio.Task] = []

    # ---- 对外 ----
    def snapshot(self) -> dict:
        return {"type": "state", "intel": self.session.intel_list(), "tactics": self.session.tactic_list(),
                "stats": self.session.stats(), "intent": self.intent}

    def update_prompt(self) -> str:
        missing = [GOAL_LABEL.get(g, g) for g in self.session.missing_goals()]
        sp = system_prompt(self.session.persona["id"], self.session.scenario["id"], self.intent, missing)
        if self.context is not None:
            msgs = list(self.context.get_messages())
            rest = msgs[1:] if msgs and msgs[0].get("role") == "system" else msgs
            self.context.set_messages([{"role": "system", "content": sp}] + rest)
        return sp

    def pick_filler(self) -> Optional[bytes]:
        if not self.fillers or self.rng() >= self.filler_prob:
            return None
        keys = sorted(self.fillers)
        return self.fillers[keys[int(self.rng() * len(keys)) % len(keys)]]

    # ---- 管线 ----
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            await self.notify({"type": "interim", "text": guard_output(frame.text)})
            await self.push_frame(frame, direction)
            return
        if not (isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM):
            await self.push_frame(frame, direction)
            return
        text = (frame.text or "").strip()
        if not text:
            return
        a = self.session.ingest(text)
        if self.mode == "rule":
            msg = self.session.rule_reply(a)  # 规则引擎直接出回复，不调用大模型
            self.intent = msg["intent"]
        else:
            self.intent = self.session.fresh_intent(self.session.choose_intent(a))
            self.session.last_intent = self.intent
        await self.notify({"type": "scammer", "text": a["redacted"], "turn": a["turn"],
                           "tactics": [{"id": t["id"], "label": t["label"]} for t in a["tactics"]],
                           "newIntel": a["newIntel"], "intent": self.intent})
        if a["newIntel"] and self.blocklist is not None:
            self._bl_tasks.append(asyncio.create_task(self._check_blocklist()))

        filler = self.pick_filler()
        if filler:
            await self.push_frame(OutputAudioRawFrame(audio=filler, sample_rate=self.filler_rate, num_channels=1))

        if self.mode == "rule":
            await self.notify({"type": "bot", "text": msg["text"], "intent": msg["intent"]})
            await self.notify(self.snapshot())
            await self.push_frame(TTSSpeakFrame(msg["text"]))
            return
        await self.notify(self.snapshot())
        self.update_prompt()
        # 与网页版一致：只把脱敏后的文本交给大模型（卡号等原值只留在本进程内存）
        frame.text = a["redacted"]
        await self.push_frame(frame, direction)

    async def _check_blocklist(self):
        try:
            await asyncio.to_thread(self.blocklist.annotate_session, self.session)
            await self.notify(self.snapshot())
        except Exception as e:  # 黑名单只是加分项，失败不影响通话
            logger.warning(f"blocklist check failed: {e}")


class BotTextTap(FrameProcessor):
    """放在 LLM 之后：整句收齐后记入会话、推给面板。"""

    def __init__(self, intel: IntelProcessor, **kwargs):
        super().__init__(**kwargs)
        self.intel = intel
        self._buf: List[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buf = []
        elif isinstance(frame, LLMTextFrame):
            self._buf.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame) and self._buf:
            text = guard_output("".join(self._buf))
            self._buf = []
            if text:
                msg = self.intel.session.record_bot(text, self.intel.intent)
                await self.intel.notify({"type": "bot", "text": msg["text"], "intent": msg["intent"]})
                await self.intel.notify(self.intel.snapshot())
        await self.push_frame(frame, direction)


async def synth_fillers(persona_id: str, voice: str, sample_rate: int, synth=None, cache_dir=None) -> Dict[str, bytes]:
    """开场前把该人设的填充音合成好（每条一次 TTS 调用，缓存到 ~/.cache/deepsuck/voice）。失败则返回已有部分。"""
    from . import dashscope_ws as ds

    synth = synth or ds.synthesize
    out: Dict[str, bytes] = {}
    cdir = cache_dir or (Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "deepsuck" / "voice")
    for line in FILLERS.get(persona_id, []):
        f = Path(cdir) / f"{voice}-{sample_rate}-{hashlib.sha1(line.encode()).hexdigest()[:12]}.pcm"
        if f.exists():
            out[line] = f.read_bytes()
            continue
        try:
            buf = bytearray()
            async for chunk in synth(line, voice=voice, sample_rate=sample_rate):
                buf.extend(chunk)
            out[line] = bytes(buf)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(out[line])
        except Exception as e:
            logger.warning(f"filler synth failed ({line}): {e}")
            break
    return out
