"""语音管线里的 DeepSuck 处理器：

- GuardTextFilter：TTS 前的输出守卫（去 Markdown/括号动作、脱敏、抹长数字串）。
- IntelProcessor：对骗子语音转写做实时情报抽取 + 话术识别 + 黑名单比对，按规则引擎选出本轮策略
  并改写 LLM 系统提示词；插播拖延填充音；rule 模式下直接用规则引擎回复（不调用大模型）。
- FillerProcessor：放在 LLM 之后，用户停说后一段时间仍无 LLM 首 token 才插播填充音，首 token 到了就取消。
- BotTextTap：收集大模型整句回复，记入会话并推送到浏览器面板。

浏览器面板通过 notify(dict) 回调收消息（SmallWebRTC 数据通道 app message）。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.base_text_filter import BaseTextFilter

from .persona import (FILLERS, GOAL_TOPIC, gate_intent, guard_output, heard_scenes, session_topics, speakable, system_prompt,
                      unmask)

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


class FillerProcessor(FrameProcessor):
    """口头语 / 填充音。两种模式：

    短口头语（传入 backchannel，DEEPSUCK_BACKCHANNEL=1，默认）：用户回合结束（UserStoppedSpeakingFrame）后
    backchannel_delay_ms（默认 0）就播一条预合成的口头语，由 Backchannel 按规则决定说不说、说哪条；
    不再等 LLM 慢不慢。机器人还在说话时不插；被打断（InterruptionFrame）时输出队列里的口头语会随之清掉。

    按延迟触发（不传 backchannel，旧行为）：

    播放时刻 = max(真实停说时刻 + delay_ms, 用户回合判定结束)，且到那时仍没有 LLM 首 token / TTS 音频。
    - 用户回合开始（UserStartedSpeakingFrame）后待命；
    - VAD 判定停说（VADUserStoppedSpeakingFrame）开始计时，计时从真实停说时刻算起（扣掉 VAD 的 stop_secs）；
    - 计时到了但回合还没判定结束（可能只是句中停顿），先挂起，等 UserStoppedSpeakingFrame 再播；
      期间用户又开口（VADUserStartedSpeakingFrame）就作废，避免在对方话说一半时插嘴；
    - LLM 首 token、TTS 开始/出声、机器人开口都会取消；每个用户回合最多一次，机器人说话时不插。
    """

    def __init__(self, fillers: Optional[Dict[str, bytes]] = None, *, sample_rate: int = 16000,
                 delay_ms: int = 650, notify: Optional[Notify] = None, clock=time.monotonic,
                 backchannel=None, backchannel_delay_ms: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.fillers = fillers if fillers is not None else {}
        self.backchannel = backchannel
        self.backchannel_delay_ms = max(0, int(backchannel_delay_ms))
        self._key: Optional[str] = None
        self.sample_rate = sample_rate
        self.delay_ms = delay_ms
        self.notify = notify or _noop
        self.clock = clock
        self.played = 0
        self.cancelled = 0
        self._armed = False
        self._turn_ended = False
        self._pending = False
        self._stop_at: Optional[float] = None
        self._bot_speaking = False
        self._timer: Optional[asyncio.Task] = None
        self._last_key: Optional[str] = None

    def _pick(self) -> Optional[str]:
        keys = sorted(k for k, v in self.fillers.items() if v)
        if not keys:
            return None
        if self._last_key in keys and len(keys) > 1:
            i = keys.index(self._last_key)
            keys = keys[i + 1:] + keys[:i]
        self._last_key = keys[0]
        return keys[0]

    def _cancel(self, disarm: bool = False):
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
            self.cancelled += 1
        self._timer = None
        self._pending = False
        if disarm:
            self._armed = False

    def _start_timer(self):
        self._cancel()
        if self.delay_ms <= 0 or not self._armed or self._bot_speaking:
            return
        elapsed = 0.0 if self._stop_at is None else max(0.0, self.clock() - self._stop_at)
        self._timer = asyncio.create_task(self._wait(max(0.0, self.delay_ms / 1000.0 - elapsed)))

    async def _backchannel(self):
        self._cancel()
        if not self._armed or self._bot_speaking:
            self.backchannel.discard()
            return
        key = self.backchannel.take()
        if key is None or not self.fillers.get(key):
            self._armed = False
            return
        self._key = key
        if self.backchannel_delay_ms <= 0:
            await self._play()
        else:
            self._timer = asyncio.create_task(self._wait(self.backchannel_delay_ms / 1000.0))

    async def _wait(self, wait: float):
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        self._timer = None
        if self._turn_ended:
            await self._play()
        else:
            self._pending = True

    async def _play(self):
        self._pending = False
        if not self._armed or self._bot_speaking:
            return
        key, self._key = (self._key or self._pick()), None
        if key is None or not self.fillers.get(key):
            return
        self._armed = False  # 每回合一次
        self.played += 1
        logger.debug(f"filler: {key}" + ("（口头语）" if self.backchannel is not None
                                         else f"（停说 {self.delay_ms}ms 后仍无首 token）"))
        await self.notify({"type": "filler", "text": key})
        await self.push_frame(OutputAudioRawFrame(audio=self.fillers[key], sample_rate=self.sample_rate,
                                                  num_channels=1))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            self._cancel()
            self._armed, self._turn_ended, self._stop_at = True, False, None
        elif self.backchannel is not None and isinstance(frame, UserStoppedSpeakingFrame):
            self._turn_ended = True
            await self._backchannel()
        elif self.backchannel is not None and isinstance(frame, (VADUserStartedSpeakingFrame,
                                                                 VADUserStoppedSpeakingFrame)):
            pass  # 短口头语只看回合结束，不看 VAD 停顿
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self._cancel()
            self._stop_at = None
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            if self._armed:
                self._stop_at = self.clock() - max(0.0, getattr(frame, "stop_secs", 0.0) or 0.0)
                self._start_timer()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._armed:
                self._turn_ended = True
                if self._pending:
                    await self._play()
                elif self._timer is None:
                    self._start_timer()
        elif isinstance(frame, (LLMTextFrame, TTSSpeakFrame, TTSStartedFrame, TTSAudioRawFrame)):
            self._cancel(disarm=True)
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._cancel(disarm=True)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, InterruptionFrame):
            self._cancel()
        await self.push_frame(frame, direction)

    async def cleanup(self):
        self._cancel(disarm=True)
        await super().cleanup()


class IntelProcessor(FrameProcessor):
    """放在 STT 之后、用户上下文聚合器之前。"""

    def __init__(self, session, *, context=None, notify: Optional[Notify] = None, mode: str = "llm",
                 fillers: Optional[Dict[str, bytes]] = None, filler_rate: int = 16000,
                 filler_prob: float = 0.6, blocklist=None, rng=None, backchannel=None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self.backchannel = backchannel  # voice.backchannel.Backchannel：转写到了就决定本回合说不说口头语
        self.said_first = ""            # 本回合打算先说的口头语，写进系统提示词，免得正式回复开头再"嗯"
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
        self.meter = None        # voice.guard.Ticket（LLM token 记账）
        self.on_heard = None     # 回调：听到骗子说话（看门狗用来判断静默）
        self.closing = False     # 护栏触发挂断后不再处理新转写（不再调用大模型）
        self.prompt_sha = ""     # 本轮系统提示词的短哈希（通话追踪记录用）
        # 意图门控：只接对方已经说过的话（rule 模式经 Session.intent_gate 生效，llm 模式在下面直接调用）
        session.intent_gate = lambda intent: gate_intent(intent, session)

    # ---- 对外 ----
    def snapshot(self) -> dict:
        return {"type": "state", "intel": self.session.intel_list(), "tactics": self.session.tactic_list(),
                "stats": self.session.stats(), "intent": self.intent}

    def update_prompt(self) -> str:
        topics = session_topics(self.session)
        # 只提对方已经提到、但还没拿到的情报；对方没提过的（例如杀猪盘里还没说平台）不进提示词
        missing = [GOAL_LABEL.get(g, g) for g in self.session.missing_goals() if GOAL_TOPIC.get(g) in topics]
        first = sum(1 for m in getattr(self.session, "messages", []) if m.get("role") == "scammer") <= 1
        sp = system_prompt(self.session.persona["id"], self.session.scenario["id"], self.intent, missing,
                           said_first=self.said_first, topics=topics, first_turn=first,
                           scenes=heard_scenes(self.session))
        self.prompt_sha = hashlib.sha1(sp.encode("utf-8")).hexdigest()[:8]
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
        if isinstance(frame, (InterimTranscriptionFrame, TranscriptionFrame)) and self.on_heard:
            self.on_heard()
        if isinstance(frame, InterimTranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            await self.notify({"type": "interim", "text": guard_output(frame.text)})
            await self.push_frame(frame, direction)
            return
        if not (isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM):
            await self.push_frame(frame, direction)
            return
        if self.closing:
            return
        text = (frame.text or "").strip()
        if not text:
            return
        a = self.session.ingest(text)
        if self.backchannel is not None:
            self.said_first = self.backchannel.note(a["redacted"]) or ""
        if self.mode == "rule":
            msg = self.session.rule_reply(a)  # 规则引擎直接出回复，不调用大模型
            self.intent = msg["intent"]
        else:
            self.intent = gate_intent(self.session.fresh_intent(self.session.choose_intent(a)), self.session)
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
        # 打码值（130****8600）改成“尾号8600”再给模型，免得模型照着念出星号
        frame.text = unmask(a["redacted"])
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
        if isinstance(frame, MetricsFrame) and self.intel.meter is not None:
            for d in frame.data or []:
                v = getattr(d, "value", None)
                if v is not None and hasattr(v, "prompt_tokens") and hasattr(v, "completion_tokens"):
                    self.intel.meter.llm(int(v.prompt_tokens or 0), int(v.completion_tokens or 0))
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


_MEM: Dict[tuple, bytes] = {}  # (缓存目录, 音色, 采样率, 文本) -> 已裁静音的 PCM，进程内共享


async def synth_fillers(persona_id: str, voice, sample_rate: int, synth=None, cache_dir=None,
                        meter=None, out: Optional[Dict[str, bytes]] = None,
                        cached_only: bool = False) -> Dict[str, bytes]:
    """把该人设的口头语合成好（每条一次 TTS 调用）。缓存：进程内存 + 磁盘（DATA_DIR/voice/fillers，见
    voice.backchannel.cache_dir），按 音色/采样率/文本 区分，载入时裁掉首尾静音。失败则返回已有部分（优雅降级：没合成好的不播）。
    out：就地填充的字典（通话中后台补齐时，处理器持有同一个字典，合成好一条就能用一条）。
    cached_only：只读缓存、不调用 TTS（开场不等待）。"""
    from . import dashscope_ws as ds
    from .backchannel import cache_dir as default_cache_dir, trim_silence

    synth = synth or ds.synthesize
    out = {} if out is None else out
    # voice 可以是音色名，也可以是 VoiceSpec（设计音色要带模型和指令；缓存键区分指令开关）
    extra = {}
    if isinstance(voice, ds.VoiceSpec):
        extra = {"model": voice.model}
        if voice.instruction:
            extra["instruction"] = voice.instruction
        if voice.rate != 1.0:
            extra["rate"] = voice.rate
        voice_name, voice = voice.voice, voice.cache_tag
    else:
        voice_name = voice
    cdir = Path(cache_dir) if cache_dir else default_cache_dir()
    for line in FILLERS.get(persona_id, []):
        mk = (str(cdir), voice, sample_rate, line)
        if mk in _MEM:
            out[line] = _MEM[mk]
            continue
        f = cdir / f"{voice}-{sample_rate}-{hashlib.sha1(line.encode()).hexdigest()[:12]}.pcm"
        try:
            if f.exists():
                pcm = trim_silence(f.read_bytes(), sample_rate)
                if pcm:
                    out[line] = _MEM[mk] = pcm
                    continue
        except OSError as e:
            logger.warning(f"filler cache read failed ({f.name}): {e}")
        if cached_only:
            continue
        try:
            buf = bytearray()
            if meter is not None:
                meter.tts(len(line))
            async for chunk in synth(line, voice=voice_name, sample_rate=sample_rate, **extra):
                buf.extend(chunk)
            pcm = trim_silence(bytes(buf), sample_rate)
            if not pcm:
                raise RuntimeError("empty audio")
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(bytes(buf))
            except OSError as e:  # 磁盘不可写也照样用内存里的
                logger.warning(f"filler cache write failed: {e}")
            out[line] = _MEM[mk] = pcm
        except Exception as e:
            logger.warning(f"filler synth failed ({line}): {e}")
            break
    return out


def fillers_missing(persona_id: str, voice, sample_rate: int, have: Dict[str, bytes]) -> bool:
    return any(line not in have for line in FILLERS.get(persona_id, []))
