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
import re
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
    LLMContextFrame,
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

from .callredact import (CallRedactor, REDACT_FAIL_PLACEHOLDER, TTS_REDACT_FAIL_SPEAK,
                         redact_digit_fragments, redact_line, redact_line_checked)
from .persona import (FILLERS, GOAL_TOPIC, drop_unsaid, gate_intent, guard_output, heard_refs, heard_scenes, prompt_parts, session_topics,
                      speakable, system_prompt, unmask)
from .persona import NAME_PHRASE, drop_given_after_split, split_lead_refs  # noqa: E402  #215 拆字解释：已批说法「那个名字」；分段星号

Notify = Callable[[dict], Awaitable[None]]

_STAR_ONLY = re.compile(r"^[\s*＊。，,、.…!！?？]*[*＊][\s*＊。，,、.…!！?？]*$")
_NUM_CTX = re.compile(r"[0-9０-９]|码|号|卡|位|开头|账户|账号")


GOAL_LABEL = {"bank": "收款银行卡号", "wallet": "加密钱包地址", "phone": "联系电话", "url": "网址/下载链接", "name": "收款人姓名"}


# #169：历史窗口。上下文里（不含第一轮）超过 HISTORY_TRIM_AT 轮时，整块丢掉最老的 HISTORY_DROP 轮（一次丢一块，
# 两次截断之间前缀不变，能吃前缀缓存）。接电话那一声和对方第一段话（自我介绍）连同人设的第一条回复固定保留。
# 情报、缺项、话题、场景、称呼都从 session 算（session.messages 不截），按通话打码名单在 CallRedactor 里，都不受影响；
# 人设在被丢掉的几轮里说过的关键事实（哪家银行、多少钱、用过的借口）摘出来，放进每轮可变部分。
HISTORY_TRIM_AT = 12
HISTORY_DROP = 4
FACTS_MAX = 6
_FACT = re.compile(r"银行|[工农建招交中]行|邮储|信用社|支付宝|微信|余额|存款|工资|退休金|"
                   r"[0-9零一二两三四五六七八九十百千万]+\s*(?:块|元|万|千)|"
                   r"在外面|没带|找不到|没电|信号|开会|上班|下班|店里|医院|老伴|孩子|宝宝|老公|儿子|女儿|忘了|记不清|不在家|在家")
_ARABIC = re.compile(r"[0-9０-９]{2,}")
_FIRST_SENT = re.compile(r"[^。？！?!；;\n]+[。？！?!；;…]*")


def persona_facts(text: str, redactor=None) -> list:
    """人设一条回复里带关键事实的句子（已按通话打码、去掉阿拉伯数字串，每句不超过 30 字）。"""
    t = str(text or "")
    if redactor is not None:
        t = redactor.apply(t)
    t = _ARABIC.sub("几", unmask(t))
    out = []
    for m in _FIRST_SENT.finditer(t):
        x = m.group(0).strip().strip("…").strip()
        if x and _FACT.search(x) and "*" not in x and "＊" not in x:
            out.append(x[:30])
    return out


def window_history(rest: list, trim_at: int = HISTORY_TRIM_AT, drop: int = HISTORY_DROP):
    """rest：不含 system 的上下文消息。返回 (保留的消息, 丢掉的消息)。按 user 消息分轮；第一条 user 之前的
    （接电话那一声）和第一轮（对方自我介绍 + 人设第一条回复）固定保留；其余超过 trim_at 轮时整块丢最老的 drop 轮。"""
    starts = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    if len(starts) <= 1:
        return list(rest), []
    head = rest[:starts[1]]
    body = rest[starts[1]:]
    bstarts = [i - starts[1] for i in starts[1:]] + [len(body)]
    rounds = [body[bstarts[k]:bstarts[k + 1]] for k in range(len(bstarts) - 1)]
    dropped = []
    while len(rounds) + 1 > trim_at:
        for r in rounds[:drop]:
            dropped += r
        rounds = rounds[drop:]
    return list(head) + [m for r in rounds for m in r], dropped


async def _noop(_msg: dict) -> None:
    return None


class GuardTextFilter(BaseTextFilter):
    """送 TTS 前的输出守卫。redactor：本通电话的 CallRedactor（#140），模型复述了已提取的姓名/号码也先打码。

    #261：每段经 redact_line_checked 探测失败（与转写同一套 fail-closed），再 CallRedactor / drop_unsaid / speakable；
    脱敏失败或只剩 *** 占位时念 TTS_REDACT_FAIL_SPEAK 完整兜底句，绝不把 *** 送进合成。
    """

    def __init__(self, redactor: Optional[CallRedactor] = None, refs: Optional[Callable[[], set]] = None):
        self.redactor = redactor
        self.refs = refs  # #184：IntelProcessor.heard_refs；对方没报过的代称换成直说（drop_unsaid）。None 不处理
        self._last = ""
        self._prev_raw = ""

    async def update_settings(self, settings):  # 无可调参数
        return None

    def _speak_fail(self) -> str:
        self._last = TTS_REDACT_FAIL_SPEAK
        return TTS_REDACT_FAIL_SPEAK

    async def filter(self, text: str) -> str:
        try:
            prev, self._prev_raw = self._prev_raw, text
            text = drop_given_after_split(prev, text)  # #215：上一句以拆字报姓结尾时，这一句开头的名不念
            if not (text or "").strip():
                return ""
            # #261：脱敏失败 / 纯 *** 占位 → 念完整兜底句（日志占位仍是 ***，不把星号送进合成）
            # redact_line_checked 只取失败标志；成功时仍走原 CallRedactor + speakable，避免与 drop_name_explain 双重处理
            _, failed = redact_line_checked(text)
            if failed or text.strip() == REDACT_FAIL_PLACEHOLDER or _STAR_ONLY.match(text or ""):
                return self._speak_fail()
            text = self.redactor.apply(text) if self.redactor is not None else text
            if (text or "").strip() == REDACT_FAIL_PLACEHOLDER or _STAR_ONLY.match(text or ""):
                return self._speak_fail()
            # #184：对方没报过的代称换成直说。顺序（#219，负责人已确认）：drop_unsaid 先过，然后 speakable。
            # 这时打码值还是星号，所以 drop_unsaid 只换模型自己写的代称；如果放在 speakable 之后，会把打码换出来的
            # 「那个名字」「那个号」（unmask / _unmask_names / drop_name_explain 的占位）改成光秃秃的「名字」
            # （「户名***」→「户名名字」，见 #219，用例 voice/tests/test_unsaid_placeholder.py）。不要改回。
            if self.refs is not None:
                text = drop_unsaid(text, self.refs())
            out = speakable(text)
            # speakable 把残留星号收成停顿；若整段被收成空 / 纯停顿，仍走兜底，避免念出无意义的「……」
            if not out.strip() or not re.sub(r"[\s.\u3002\u2026\u00b7]+", "", out):
                return self._speak_fail()
            # #215：TTS 按分句送，「收款人是弓长张，伟大的伟对吧」被切成两句，各自换成「那个名字」；
            # 上一句以「那个名字」结尾、这一句又以它开头时去掉这一个，合起来仍是「收款人是那个名字对吧」
            if self._last.endswith(NAME_PHRASE) and out.startswith(NAME_PHRASE):
                out = out[len(NAME_PHRASE):].lstrip("，, ")
            if out:
                self._last = out
            return out
        except Exception as e:  # noqa: BLE001  #261：守卫链任何异常都不把原文 / *** 送进 TTS
            logger.warning("GuardTextFilter failed closed: {}", type(e).__name__)
            return self._speak_fail()

    async def handle_interruption(self):
        self._last = self._prev_raw = ""
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
                 filler_prob: float = 0.6, blocklist=None, rng=None, backchannel=None,
                 redactor: Optional[CallRedactor] = None, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        # #140：本通电话已提取的姓名、号码（原值只在内存），后面每段文本进模型、记会话前按各种说法再打码
        self.redactor = redactor if redactor is not None else CallRedactor()
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
        self.facts: List[str] = []   # #169：人设在已截掉的几轮里说过的关键事实（打码后），每轮放进可变部分
        self.dropped_rounds = 0      # #169：历史窗口累计丢掉的消息条数（追踪用）
        # #95：第一句说法示例按“本通随机值 + 对方第一句话”挑。对方开口常是同一句“喂，你好…”，只按原话挑会每通都一样
        self.opener_salt = os.urandom(4).hex()
        # 意图门控：只接对方已经说过的话（rule 模式经 Session.intent_gate 生效，llm 模式在下面直接调用）
        session.intent_gate = lambda intent: gate_intent(intent, session)

    # ---- 对外 ----
    def snapshot(self) -> dict:
        return {"type": "state", "intel": self.session.intel_list(), "tactics": self.session.tactic_list(),
                "stats": self.session.stats(), "intent": self.intent}

    def call_redact(self, a: dict, raw: Optional[str] = None) -> dict:
        """#140：按通话打码。先把本段新提取的情报记进集合，再把本段文本、会话里对方说过的话、模型上下文里的用户消息
        中已提取姓名/号码的各种说法（全名、去姓的名、拆字说法、号码换写法）打码。逐句规则漏掉的在这里补上。"""
        before = len(self.redactor)
        grew = self.redactor.learn(self.session) > before
        if not len(self.redactor):
            return a
        core_red = a.get("redacted", "")
        a["redacted"] = self.redactor.apply(core_red, raw=raw)  # #163：raw 用来把共享核心打成纯星号的单段解释读成“那个名字”
        for m in getattr(self.session, "messages", []) or []:
            if m.get("role") == "scammer" and isinstance(m.get("text"), str):
                m["text"] = a["redacted"] if m["text"] == core_red else self.redactor.apply(m["text"])
        if grew and self.context is not None:  # 新记下的名字可能在之前几段里已经说过（先报名、后报户名）
            msgs = list(self.context.get_messages())
            changed = False
            for m in msgs:
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    c = unmask(self.redactor.apply(m["content"]))
                    if c != m["content"]:
                        m["content"], changed = c, True
            if changed:
                self.context.set_messages(msgs)
        return a

    def line_redact(self, a: dict) -> dict:
        """#252：Session.ingest 的 redacted 先过 redact_line（与存盘 / trace / 回填同一个入口），会话里对应的那条一起改。"""
        old = a.get("redacted", "")
        new = redact_line(old)
        if new != old:
            a["redacted"] = new
            for m in reversed(getattr(self.session, "messages", []) or []):
                if m.get("role") == "scammer" and m.get("text") == old:
                    m["text"] = new
                    break
        return a

    def frag_redact(self, a: dict) -> dict:
        """#186：ASR 把号码切成几段时，本段和前几段对方的话连起来看，号码片段的数字打成 *（session 里对方的话一起回写）。
        情报提取已经在 session.ingest 里用原文做完，这里只改送出去的文字。"""
        msgs = getattr(self.session, "messages", None) or []
        idx = [i for i, m in enumerate(msgs) if m.get("role") == "scammer" and isinstance(m.get("text"), str)][-3:]
        if not idx:
            a["redacted"] = redact_digit_fragments([a.get("redacted", "")])[0]
            return a
        fixed = redact_digit_fragments([msgs[i]["text"] for i in idx])
        for i, t in zip(idx, fixed):
            msgs[i]["text"] = t
        a["redacted"] = redact_digit_fragments([msgs[i]["text"] for i in idx[:-1]] + [a.get("redacted", "")])[-1]
        return a

    def guard_context(self, context) -> bool:
        """#186：调大模型前最后一道：上下文里全部用户消息连起来再打一次号码片段，并补上按通话打码。
        已经推进用户聚合器、收不回来的前几段（「卡号是62220212。」）在这里改掉。返回是否改动。"""
        if context is None:
            return False
        msgs = list(context.get_messages())
        idx = [i for i, m in enumerate(msgs) if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if not idx:
            return False
        fixed = redact_digit_fragments([msgs[i]["content"] for i in idx])
        changed = False
        for k, (i, t) in enumerate(zip(idx, fixed)):
            t = unmask(self.redactor.apply(t), prev=fixed[k - 1] if k else "")  # #214 复审：分段开头的星号看上一段
            if t != msgs[i]["content"]:
                msgs[i] = {**msgs[i], "content": t}
                changed = True
        if changed:
            context.set_messages(msgs)
        return changed

    def have_labels(self) -> List[str]:
        """对方已经报过、已提取的情报种类（GOAL_LABEL 的名称），从 session.intel 算，和上下文截断无关。"""
        return [GOAL_LABEL[g] for g in GOAL_LABEL if self.session.have_goal(g)]

    def heard_refs(self) -> set:
        """#173：对方到现在报过的代称种类（"name" / "number" / "url" / "wallet"…）：对方的话里出现过的打码值（共享核心
        deepsuck.refs.heard_refs，与网页 llm.js 同一套）加上已提取的情报。从 session 算，和上下文截断无关。"""
        texts = [m.get("text", "") for m in getattr(self.session, "messages", []) or [] if m.get("role") == "scammer"]
        # #186 之后号码片段会单独成一段纯星号（「卡号是********。」「******。」）；共享核心按 #172 把没有号码提示的纯星号段
        # 读成名字。紧跟在号码段后面的纯星号段算号码（这一串都算），不交给 heard_refs 判断。
        keep, num, prev_num = [], False, False
        for t in texts:
            if _STAR_ONLY.match(t or "") and prev_num:
                num = True
                continue
            keep.append(t)
            prev_num = bool(_NUM_CTX.search(t or ""))
        keep, extra = split_lead_refs(keep)
        out = heard_refs(keep) | extra  # #214 复审：分段开头的星号按上一段结尾算（「卡号是」/「***，户名***」）
        if num:
            out.add("number")
        for goal, kind in (("bank", "number"), ("phone", "number"), ("name", "name"), ("url", "url"), ("wallet", "wallet")):
            if self.session.have_goal(goal):
                out.add(kind)
        return out

    def update_prompt(self) -> str:
        """#169：上下文排成 [固定部分 system] + 历史（窗口内）+ [本轮可变部分 system]，当前这段转写由聚合器接在最后。
        固定部分每轮基本不变，历史一次截一整块，所以前面一长段在相邻两轮之间相同，可以吃百炼的前缀缓存。"""
        topics = session_topics(self.session)
        # 只提对方已经提到、但还没拿到的情报；对方没提过的（例如杀猪盘里还没说平台）不进提示词
        missing = [GOAL_LABEL.get(g, g) for g in self.session.missing_goals() if GOAL_TOPIC.get(g) in topics]
        first = sum(1 for m in getattr(self.session, "messages", []) if m.get("role") == "scammer") <= 1
        heard = next((m.get("text", "") for m in getattr(self.session, "messages", []) if m.get("role") == "scammer"), "")
        rest = None
        if self.context is not None:
            msgs = list(self.context.get_messages())
            hist = [m for m in (msgs[1:] if msgs and msgs[0].get("role") == "system" else msgs) if m.get("role") != "system"]
            rest, dropped = window_history(hist)
            if dropped:
                self.dropped_rounds += len(dropped)
                for m in dropped:
                    if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                        self.facts += [x for x in persona_facts(m["content"], self.redactor) if x not in self.facts]
                self.facts = self.facts[-FACTS_MAX:]
        fixed, turn = prompt_parts(self.session.persona["id"], self.session.scenario["id"], self.intent, missing,
                                   said_first=self.said_first, topics=topics, first_turn=first,
                                   scenes=heard_scenes(self.session), opener_key=f"{self.opener_salt}|{heard}",
                                   have=self.have_labels(), facts=self.facts, refs=self.heard_refs())
        sp = fixed + "\n" + turn
        self.prompt_sha = hashlib.sha1(sp.encode("utf-8")).hexdigest()[:8]
        if self.context is not None:
            self.context.set_messages([{"role": "system", "content": fixed}] + rest + [{"role": "system", "content": turn}])
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
            await self.notify({"type": "interim", "text": guard_output(redact_line(frame.text))})  # #252
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
        a = self.line_redact(self.frag_redact(self.call_redact(self.session.ingest(text), raw=text)))  # #252：最后一道过 redact_line
        if self.backchannel is not None:
            self.said_first = self.backchannel.note(a["redacted"]) or ""
        if self.mode == "rule":
            msg = self.session.rule_reply(a)  # 规则引擎直接出回复，不调用大模型
            self.intent = msg["intent"]
        else:
            self.intent = gate_intent(self.session.fresh_intent(self.session.choose_intent(a)), self.session)
            self.session.last_intent = self.intent
        await self.notify({"type": "scammer", "text": redact_line(a["redacted"]), "turn": a["turn"],
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
        scam = [m.get("text", "") for m in getattr(self.session, "messages", []) or [] if m.get("role") == "scammer"]
        frame.text = unmask(a["redacted"], prev=scam[-2] if len(scam) > 1 else "", refs=self.heard_refs())  # #214 复审：分段开头的星号看上一段
        await self.push_frame(frame, direction)

    async def _check_blocklist(self):
        try:
            await asyncio.to_thread(self.blocklist.annotate_session, self.session)
            await self.notify(self.snapshot())
        except Exception as e:  # 黑名单只是加分项，失败不影响通话
            logger.warning(f"blocklist check failed: {e}")


class ContextGuard(FrameProcessor):
    """#186：放在用户聚合器之后、LLM 之前：发给大模型的上下文再过一遍号码片段打码（IntelProcessor.guard_context）。"""

    def __init__(self, intel: IntelProcessor, **kwargs):
        super().__init__(**kwargs)
        self.intel = intel

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            try:
                self.intel.guard_context(frame.context)
            except Exception as e:  # 打码失败不能卡住通话；记下来
                logger.warning(f"context guard failed: {e}")
        await self.push_frame(frame, direction)


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
            # #184 顺序（#219，负责人已确认）：drop_unsaid 先过，然后 guard_output。这时打码值还是星号，所以 drop_unsaid
            # 只换模型自己写的代称；如果放在 guard_output 之后，会把打码 / 逐字解释换出来的「那个名字」「那个号」改成光秃秃的
            # 「名字」（见 #219，用例 voice/tests/test_unsaid_placeholder.py）。不要改回。
            text = guard_output(drop_unsaid(self.intel.redactor.apply("".join(self._buf)), self.intel.heard_refs()))
            self._buf = []
            if text:
                msg = self.intel.session.record_bot(text, self.intel.intent)
                await self.intel.notify({"type": "bot", "text": msg["text"], "intent": msg["intent"]})
                await self.intel.notify(self.intel.snapshot())
        await self.push_frame(frame, direction)


# ---- #175：跨轮尾句去重（#153 的 dedupe_tail 接到语音链路）----
import re  # noqa: E402

from deepsuck.engine import _td_norm, dedupe_tail, tail_sentence  # noqa: E402  （.persona 已把 python/ 放进 sys.path）


class TailHistory:
    """每通电话一份（同 CallRedactor）：本通最近 window 轮人设实际说出口（按通话打码后）的尾句。"""

    def __init__(self, window: int = 3):
        self.window = max(1, int(window))
        self._tails: List[str] = []

    def recent(self) -> List[str]:
        return list(self._tails[-self.window:])

    def seen(self) -> set:
        return {_td_norm(x) for x in self.recent()} - {""}

    def push(self, text: str) -> None:
        t = tail_sentence(text)
        if t:
            self._tails = (self._tails + [t])[-self.window:]

    def __len__(self) -> int:
        return len(self._tails)


class TailDedupeProcessor(FrameProcessor):
    """放在 LLM 之后、FillerProcessor / BotTextTap / TTS 之前：大模型这一轮回复的尾句和本通最近 3 轮的尾句重复就整句删掉，
    删空后用该人设 ask_repeat 里最近没说过的一句兜底（deepsuck.engine.dedupe_tail，persona_id 必传）。

    顺序：先按通话打码（CallRedactor.apply，与 BotTextTap / GuardTextFilter 同一份），再去重；speakable 守卫仍在 TTS 的
    GuardTextFilter 里做（只做一次，避免对已经过滤的文本二次过滤）。尾句历史记的是实际放出去的（打码后）文本。

    流式：不等整段收齐。当前这句（可能还没说完）去标点后已经不是任何最近尾句的前缀，就不可能被删，连同前面压着的
    一起放行；否则先压着，等这句说完或回复结束再定。所以只有疑似重复的那几句会多等。回复结束时以 dedupe_tail 的结果为准。

    dedupe_tail 返回空串（人设没有可用的 ask_repeat，或没有 persona_id）：这一轮当作没有回复——
    LLMFullResponseStart/End 和文本都不往下发（TTS、会话记录、模型上下文都看不到这一轮），FillerProcessor 也不会被取消，
    由填充音或下一轮接上；尾句历史不变。"""

    def __init__(self, persona_id: Optional[str], *, redactor: Optional[CallRedactor] = None,
                 history: Optional[TailHistory] = None, **kwargs):
        super().__init__(**kwargs)
        self.persona_id = persona_id
        self.redactor = redactor if redactor is not None else CallRedactor()
        self.history = history if history is not None else TailHistory()
        self.dropped = 0    # 删空、整轮不出声的次数（追踪用）
        self.rewritten = 0  # 删过尾句（含兜底换句）的次数
        self._reset()

    def _reset(self):
        self._active = False    # 在一段 LLMFullResponseStart…End 之间
        self._started = False   # Start 帧是否已经放行（第一次放出文字时才放）
        self._full = ""         # 本轮大模型原文
        self._sent = 0          # 已放行的字符数（_full 的前缀）
        self._seen: set = set()

    def _red(self, text: str) -> str:
        return self.redactor.apply(text)

    def _safe(self) -> bool:
        """当前最后一句（打码、去标点后）不是任何最近尾句的前缀 → 这一句最终不可能和最近尾句相同。"""
        parts = [x for x in self._sentences(self._red(self._full)) if _td_norm(x)]
        if not parts:
            return False
        k = _td_norm(parts[-1])
        return not any(s.startswith(k) for s in self._seen)

    @staticmethod
    def _sentences(text: str) -> List[str]:
        return [x for x in re.split(r"(?<=[。？！?!；;\n])(?=[^。？！?!；;\n])", text) if x]

    async def _emit(self, text: str):
        if not text:
            return
        if not self._started:
            self._started = True
            await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame(text))

    async def _finish(self):
        full = self._red(self._full)
        final = dedupe_tail(full, self.history.recent(), self.persona_id)
        if self._sent == 0:
            out, spoken = final, final
        else:  # 前面已放行的部分一定保留（见 _safe），剩下压着的那段单独过一遍
            rest = self._full[self._sent:]
            out = dedupe_tail(self._red(rest), self.history.recent(), None) if rest else ""
            spoken = self._red(self._full[:self._sent]) + out
        if _td_norm(full) and _td_norm(final) != _td_norm(full):
            self.rewritten += 1
        await self._emit(out)
        if self._started:
            self.history.push(spoken)
            await self.push_frame(LLMFullResponseEndFrame())
        elif _td_norm(full):
            self.dropped += 1
            logger.debug("tail dedupe: 本轮删空且无兜底，当作没有回复")
        self._reset()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, LLMFullResponseStartFrame):
            self._reset()
            self._active = True
            self._seen = self.history.seen()
            return
        if isinstance(frame, LLMTextFrame) and self._active:
            self._full += frame.text or ""
            if not self._seen or self._safe():
                await self._emit(self._full[self._sent:])
                self._sent = len(self._full)
            return
        if isinstance(frame, LLMFullResponseEndFrame) and self._active:
            await self._finish()
            return
        if isinstance(frame, InterruptionFrame):
            self._reset()  # 被打断：没放出去的丢掉，历史不记
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
                meter.tts(len(line), kind="filler", text=line)
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
