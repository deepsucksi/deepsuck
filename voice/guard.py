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
from typing import Dict, List, Optional

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


@dataclass
class Prices:
    """单价（元）。默认值为 2026-10 百炼北京地域原价，以控制台为准。"""
    asr_per_sec: float = 0.00024      # paraformer-realtime-v2
    tts_per_char: float = 0.0001      # cosyvoice-v3-flash：1 元 / 万字符
    llm_in_per_m: float = 0.8         # qwen-plus 输入：元 / 百万 token
    llm_out_per_m: float = 2.0        # qwen-plus 输出

    @classmethod
    def from_env(cls) -> "Prices":
        return cls(_env_f("PRICE_ASR_PER_SEC", 0.00024), _env_f("PRICE_TTS_PER_10K_CHARS", 0.8) / 10000,
                   _env_f("PRICE_LLM_IN_PER_M", 0.8), _env_f("PRICE_LLM_OUT_PER_M", 2.0))


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


class Ticket:
    """一局通话的预占额度与实际花费。"""

    def __init__(self, budget: "VoiceBudget", resv: float, sid: str):
        self.budget, self.resv, self.sid = budget, resv, sid
        self.spent = 0.0
        self.usage = {"asr_sec": 0.0, "tts_chars": 0, "llm_in": 0, "llm_out": 0}
        self.closed = False

    # 计量回调（服务里调用）
    def asr(self, seconds: float) -> None:
        self.usage["asr_sec"] += seconds
        self._charge(seconds * self.budget.prices.asr_per_sec)

    def tts(self, chars: int) -> None:
        self.usage["tts_chars"] += chars
        self._charge(chars * self.budget.prices.tts_per_char)

    def llm(self, tokens_in: int, tokens_out: int) -> None:
        self.usage["llm_in"] += tokens_in
        self.usage["llm_out"] += tokens_out
        p = self.budget.prices
        self._charge((tokens_in * p.llm_in_per_m + tokens_out * p.llm_out_per_m) / 1e6)

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
