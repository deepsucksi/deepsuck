"""语音演示公开部署时的费用护栏（不依赖 Pipecat，便于单测）。

- VoiceBudget：每日全局预算（人民币）。按实际用量记账：ASR 音频秒数、TTS 字符数、LLM token。
  开局前按"本局最坏花费"预占（max_minutes × ASR 单价 + TTS/LLM 上限），保证并发下也不会超过上限；
  账本按 Asia/Shanghai 自然日持久化到 DATA_DIR/voice-budget.json，重启不清零。
- Gate：最大并发通话数、每 IP 每小时/每天通话次数。
- Limits：每局最长分钟数、最多轮数、静默超时（浏览器一直在推音频，ASR 按音频时长计费，静默也花钱）。

默认值偏保守；全部可用环境变量覆盖（见 deploy/.env.example）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CN = timezone(timedelta(hours=8))


def cn_day(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), CN).strftime("%Y-%m-%d")


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# 大模型单价表（元 / 百万 token，华北 2（北京）原价、非思考模式、最低一档输入长度；以百炼控制台为准）。
# 来源（2026-10-19 查询）：
#   qwen-plus      https://help.aliyun.com/zh/model-studio/qwen-plus       输入≤128K：0.8 / 2
#   qwen3.7-flash  https://help.aliyun.com/zh/model-studio/qwen3-7-flash   输入≤32K：0.2 / 0.8
#   qwen3.8-flash  https://help.aliyun.com/zh/model-studio/qwen3-8-flash   输入≤1M：0.8 / 2.7
# 每轮输入约 1–3K token，都落在最低一档。快照名（如 qwen-plus-2025-12-01）按前缀取价。
# 覆盖优先级：VOICE_PRICE_LLM_IN/OUT_PER_M（语音专用）> PRICE_LLM_IN/OUT_PER_M（Node 代理那份，只在语音模型
# 与代理的 LLM_MODEL 相同时才套用）> PRICE_LLM_TABLE="模型:输入:输出,..." > 下表。
LLM_PRICES: Dict[str, Tuple[float, float]] = {
    "qwen-plus": (0.8, 2.0),
    "qwen3.7-flash": (0.2, 0.8),
    "qwen3.8-flash": (0.8, 2.7),
}
DEFAULT_LLM_MODEL = "qwen3.7-flash"   # 语音默认模型（#40 选型，见 docs/LLM_AB.md）
PROXY_LLM_MODEL = "qwen-plus"         # Node 文字代理 LLM_MODEL 的默认值（server/index.js）


def llm_price_table(env=None) -> Dict[str, Tuple[float, float]]:
    e = os.environ if env is None else env
    table = dict(LLM_PRICES)
    for item in (e.get("PRICE_LLM_TABLE") or "").split(","):
        parts = [x.strip() for x in item.split(":")]
        if len(parts) == 3 and parts[0]:
            try:
                table[parts[0]] = (float(parts[1]), float(parts[2]))
            except ValueError:
                pass
    return table


def llm_price(model: str, env=None) -> Tuple[float, float]:
    """按模型取（输入, 输出）单价。精确名优先，其次最长前缀（快照名）；查不到按表里最贵的算（预算宁高勿低）。"""
    table = llm_price_table(env)
    if model in table:
        return table[model]
    hits = [k for k in table if model.startswith(k + "-")]
    if hits:
        return table[max(hits, key=len)]
    return max(table.values(), key=lambda p: p[0] + p[1])


@dataclass
class Prices:
    """单价（元）。默认值为 2026-10 百炼北京地域原价，以控制台为准。"""
    asr_per_sec: float = 0.00024      # paraformer-realtime-v2
    tts_per_char: float = 0.0001      # cosyvoice-v3-flash：1 元 / 万字符
    llm_in_per_m: float = 0.2         # qwen3.7-flash 输入：元 / 百万 token
    llm_out_per_m: float = 0.8        # qwen3.7-flash 输出
    llm_model: str = DEFAULT_LLM_MODEL

    @classmethod
    def from_env(cls, model: Optional[str] = None, env=None) -> "Prices":
        e = os.environ if env is None else env
        model = model or e.get("DEEPSUCK_LLM_MODEL") or DEFAULT_LLM_MODEL
        p_in, p_out = llm_price(model, e)

        def f(name: str, default: float) -> float:
            try:
                return float(e.get(name, default))
            except (TypeError, ValueError):
                return default

        # PRICE_LLM_* 是 Node 代理按 LLM_MODEL 记账用的；语音换了别的模型时不能沿用，否则预算算错
        same = model == (e.get("LLM_MODEL") or PROXY_LLM_MODEL)
        p_in = f("VOICE_PRICE_LLM_IN_PER_M", f("PRICE_LLM_IN_PER_M", p_in) if same else p_in)
        p_out = f("VOICE_PRICE_LLM_OUT_PER_M", f("PRICE_LLM_OUT_PER_M", p_out) if same else p_out)
        out = cls(f("PRICE_ASR_PER_SEC", 0.00024), f("PRICE_TTS_PER_10K_CHARS", 0.8) / 10000, p_in, p_out, model)
        return out


@dataclass
class Limits:
    max_sessions: int = 2          # 同时进行的通话数
    max_minutes: float = 5.0       # 每局最长分钟数
    max_turns: int = 30            # 每局骗子最多发言轮数
    idle_seconds: float = 60.0     # 这么久没识别到骗子说话就挂断
    per_ip_per_hour: int = 4
    per_ip_per_day: int = 10
    daily_budget_cny: float = 0.0  # 0 = 不限（仅本地开发）
    llm_in_per_turn: int = 3000    # 预占估算用：每轮 LLM 输入 token 上限
    llm_out_per_turn: int = 120
    tts_chars_per_turn: int = 120

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            max_sessions=_env_i("VOICE_MAX_SESSIONS", 2), max_minutes=_env_f("VOICE_MAX_MINUTES", 5),
            max_turns=_env_i("VOICE_MAX_TURNS", 30), idle_seconds=_env_f("VOICE_IDLE_SECONDS", 60),
            per_ip_per_hour=_env_i("VOICE_PER_IP_PER_HOUR", 4), per_ip_per_day=_env_i("VOICE_PER_IP_PER_DAY", 10),
            daily_budget_cny=_env_f("VOICE_DAILY_BUDGET_CNY", 0),
        )


def _is_hanzi(ch: str) -> bool:
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF
            or 0x20000 <= o <= 0x3134F)


def tts_billed_chars(text) -> int:
    """CosyVoice 计费字符数：汉字（简体、繁体、日文汉字、韩文汉字）算 2 个，其他字符（标点、字母、数字、空格、
    假名、谚文）算 1 个。用实际送去合成的原文算（脱敏之前）。
    出处（2026-10-19 查阅）：百炼「实时语音合成」https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide
    （CosyVoice 字符计数规则）；CosyVoice 接口说明 https://help.aliyun.com/zh/isi/user-guide/siso-text-to-speech-synthesis-for-cosyvoice-interface-description
    （「1个汉字计为 2个字符；1个英文字母、标点或句子中间的空格计为 1个字符」，计量字段 measureLength）。"""
    t = "" if text is None else str(text)
    return sum(2 if _is_hanzi(c) else 1 for c in t)


TICKET_KEYS = ("asr_sec", "tts_chars", "tts_billed_chars", "llm_in", "llm_out")


class Ticket:
    """一局通话的预占额度与实际花费。

    usage 是整局合计；by_kind 按调用用途（reply / filler / opening / disclosure / farewell / asr …）分开记，
    给通话追踪 v3 的 type="call" 行用（docs/TRACE_SCHEMA.md），各 kind 之和等于 usage。"""

    def __init__(self, budget: "VoiceBudget", resv: float, sid: str):
        self.budget, self.resv, self.sid = budget, resv, sid
        self.spent = 0.0
        self.usage = {"asr_sec": 0.0, "tts_chars": 0, "tts_billed_chars": 0, "llm_in": 0, "llm_out": 0}
        self.by_kind: Dict[str, Dict[str, float]] = {}
        self._tags: List[list] = []  # [剩余文字, kind]：开场白、告别语等下一次合成时按文字认出用途
        self.closed = False

    def _kind(self, kind: str, key: str, v) -> None:
        d = self.by_kind.setdefault(kind or "reply", {k: 0 for k in TICKET_KEYS})
        d[key] += v

    def tag(self, text, kind: str) -> None:
        """登记一段即将合成的文字的用途（opening / disclosure / farewell）；TTS 服务分句合成时按子串认领。"""
        t = "".join(str(text or "").split())
        if t:
            self._tags.append([t, kind])

    def _claim(self, text) -> Optional[str]:
        t = "".join(str(text or "").split())
        if not t:
            return None
        for tag in self._tags:
            if t in tag[0]:
                tag[0] = tag[0].replace(t, "", 1)
                if not any(c.isalnum() for c in tag[0]):
                    self._tags.remove(tag)
                return tag[1]
        return None

    # 计量回调（服务里调用）
    def asr(self, seconds: float, kind: str = "asr") -> None:
        self.usage["asr_sec"] += seconds
        self._kind(kind, "asr_sec", seconds)
        self._charge(seconds * self.budget.prices.asr_per_sec)

    def tts(self, chars: int, kind: Optional[str] = None, text=None) -> None:
        """chars：送去合成的字数（len）；text：原文（算计费字符数、认领 tag 用）。kind 不给时按 tag 认，认不出算 reply。"""
        billed = tts_billed_chars(text) if text is not None else int(chars)
        kind = kind or self._claim(text) or "reply"
        self.usage["tts_chars"] += chars
        self.usage["tts_billed_chars"] += billed
        self._kind(kind, "tts_chars", chars)
        self._kind(kind, "tts_billed_chars", billed)
        self._charge(chars * self.budget.prices.tts_per_char)

    def llm(self, tokens_in: int, tokens_out: int, kind: str = "reply") -> None:
        self.usage["llm_in"] += tokens_in
        self.usage["llm_out"] += tokens_out
        self._kind(kind, "llm_in", tokens_in)
        self._kind(kind, "llm_out", tokens_out)
        p = self.budget.prices
        self._charge((tokens_in * p.llm_in_per_m + tokens_out * p.llm_out_per_m) / 1e6)

    def kinds(self) -> Dict[str, Dict[str, float]]:
        return {k: dict(v) for k, v in self.by_kind.items()}

    def _charge(self, cny: float) -> None:
        self.spent += cny
        self.budget._add(cny, self.usage)

    @property
    def over(self) -> bool:
        """本局实际花费已超过预占（估算偏低时兜底挂断）。"""
        return self.resv > 0 and self.spent >= self.resv

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.budget._release(self)


class VoiceBudget:
    def __init__(self, cap_cny: float = 0.0, prices: Optional[Prices] = None, data_dir: Optional[str] = None,
                 clock=time.time):
        self.cap = float(cap_cny or 0)
        self.prices = prices or Prices()
        self.clock = clock
        self.file = Path(data_dir) / "voice-budget.json" if data_dir else None
        self._lock = threading.Lock()
        self._active: List[Ticket] = []
        self._last_save = 0.0
        self.st = self._fresh()
        if self.file and self.file.exists():
            try:
                j = json.loads(self.file.read_text(encoding="utf-8"))
                if j.get("day") == self.st["day"]:
                    self.st.update(j)
            except Exception:
                pass

    def _fresh(self) -> dict:
        return {"day": cn_day(self.clock()), "spent_cny": 0.0, "sessions": 0, "refused": 0,
                "asr_sec": 0.0, "tts_chars": 0, "llm_in": 0, "llm_out": 0}

    def _roll(self) -> None:
        if cn_day(self.clock()) != self.st["day"]:
            self.st = self._fresh()

    def session_cost_cap(self, lim: Limits) -> float:
        """一局的最坏花费估算（用于预占）。"""
        p = self.prices
        asr = lim.max_minutes * 60 * p.asr_per_sec
        tts_chars = min((lim.max_turns + 6) * lim.tts_chars_per_turn, lim.max_minutes * 60 * 6)  # 说话最快 ~6 字/秒
        llm = lim.max_turns * (lim.llm_in_per_turn * p.llm_in_per_m + lim.llm_out_per_turn * p.llm_out_per_m) / 1e6
        return round(asr + tts_chars * p.tts_per_char + llm, 6)

    def _held(self) -> float:
        return sum(max(0.0, t.resv - t.spent) for t in self._active)

    def reserve(self, est: float, sid: str = "") -> Optional[Ticket]:
        with self._lock:
            self._roll()
            if self.cap > 0 and self.st["spent_cny"] + self._held() + est > self.cap + 1e-9:
                self.st["refused"] += 1
                self._save(force=True)
                return None
            t = Ticket(self, est if self.cap > 0 else 0.0, sid)
            self._active.append(t)
            self.st["sessions"] += 1
            return t

    def _add(self, cny: float, _usage) -> None:
        with self._lock:
            self._roll()
            self.st["spent_cny"] = round(self.st["spent_cny"] + cny, 6)
            self._save()

    def _release(self, t: Ticket) -> None:
        with self._lock:
            if t in self._active:
                self._active.remove(t)
            for k, v in t.usage.items():
                self.st[k] = round(self.st.get(k, 0) + v, 3)
            self._save(force=True)

    def exhausted(self) -> bool:
        with self._lock:
            self._roll()
            return self.cap > 0 and self.st["spent_cny"] >= self.cap * 0.999

    def status(self) -> dict:
        with self._lock:
            self._roll()
            used = round(self.st["spent_cny"] / self.cap * 100) if self.cap > 0 else None
            return {"day": self.st["day"], "capCny": self.cap, "usedPct": min(100, used) if used is not None else None,
                    "exhausted": self.cap > 0 and self.st["spent_cny"] >= self.cap * 0.999,
                    "active": len(self._active)}

    def _save(self, force: bool = False) -> None:
        if not self.file:
            return
        now = self.clock()
        if not force and now - self._last_save < 2:
            return
        self._last_save = now
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.st), encoding="utf-8")
            tmp.replace(self.file)
        except Exception as e:  # 账本写不进去不影响内存里的护栏，但要让运维看到
            if not getattr(self, "_warned", False):
                self._warned = True
                import logging
                logging.getLogger("deepsuck.guard").warning(f"voice budget save failed: {e}")
                print(f"[guard] voice budget save failed: {e}", flush=True)


@dataclass
class Gate:
    """并发 + 每 IP 频率。admit() 返回 None 表示放行，否则返回 (HTTP 状态码, 原因)。"""
    limits: Limits
    clock: object = time.time
    active: Dict[str, str] = field(default_factory=dict)   # sid -> ip
    hist: Dict[str, List[float]] = field(default_factory=dict)

    def admit(self, ip: str, sid: str):
        now = self.clock()
        if len(self.active) >= self.limits.max_sessions:
            return 503, f"当前同时通话已满（最多 {self.limits.max_sessions} 路），请稍后再试"
        h = [t for t in self.hist.get(ip, []) if now - t < 86400]
        self.hist[ip] = h
        if self.limits.per_ip_per_hour > 0 and sum(1 for t in h if now - t < 3600) >= self.limits.per_ip_per_hour:
            return 429, "这个 IP 一小时内通话次数已达上限，请稍后再试"
        if self.limits.per_ip_per_day > 0 and len(h) >= self.limits.per_ip_per_day:
            return 429, "这个 IP 今日通话次数已达上限，明天再来"
        h.append(now)
        self.active[sid] = ip
        if len(self.hist) > 5000:
            self.hist = {k: v for k, v in self.hist.items() if v and now - v[-1] < 86400}
        return None

    def release(self, sid: str) -> None:
        self.active.pop(sid, None)


def end_reason(*, started: float, last_heard: float, turns: int, limits: Limits, ticket: Optional[Ticket],
               budget: VoiceBudget, now: float) -> Optional[str]:
    """看门狗：返回应当挂断的原因（None 表示继续）。"""
    if limits.max_minutes > 0 and now - started >= limits.max_minutes * 60:
        return "time"
    if limits.max_turns > 0 and turns >= limits.max_turns:
        return "turns"
    if limits.idle_seconds > 0 and now - last_heard >= limits.idle_seconds:
        return "idle"
    if ticket is not None and ticket.over:
        return "budget"
    if budget.exhausted():
        return "budget"
    return None


END_TEXT = {
    "time": "我这边有点事，先挂了，回头再说。",
    "turns": "说了这么半天我也没弄明白，先这样，回头再说。",
    "idle": "喂？没声音了，那我先挂了。",
    "budget": "手机快没电了，先挂了。",
}
END_NOTE = {
    "time": "已达每局通话时长上限",
    "turns": "已达每局轮数上限",
    "idle": "长时间没有听到说话，自动挂断",
    "budget": "今日语音体验额度已用完",
}
