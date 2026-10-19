"""通话追踪与问题反馈。字段表见 docs/TRACE_SCHEMA.md（schema_version = SCHEMA_VERSION）。

每通电话一个 8 位通话编号（base32，/api/offer 生成并返回给页面，页面可见、可复制），每一行都带 call_id。
网页通话：
  文字：每通都存（不论是否勾选同意）。每轮一行 JSONL（ASR 文本、人设回复、意图、情报、延迟拆解、模型、
        大模型 token、ASR 音频秒数、TTS 字数和音色、是否被打断），结束写一行汇总（起止时间、时长、退出原因、
        是否同意录音、用量合计）。
  录音：只有页面勾选同意（随 /api/offer 传 consent，只认 JSON true）才录两轨（对方 / 人设），各一个 16k 单声道
        ogg/opus，用 Pipecat 的 AudioBufferProcessor 分轨回调、后台线程边写边编码。
  “这通有问题”：页面带上 /api/offer 发的一次性反馈口令提交，写成 feedback 行（flagged=true）。
电话线路（SIP）：只存脱敏文字记录、不录音，主叫号码打码，consent 记为 "sip-text-only"。

文字落盘前一律再过一遍共享脱敏 deepsuck.redact_text(text, extract_sensitive(text))，再补一条自报姓名规则
（“我叫张伟”“我是李明警官”，姓氏表复用 core/extractors.json 的 nameRules）；卡号等原值只在进程内存里。
存储：文字 TRACE_DIR（默认 DATA_DIR/voice/traces，容器里是命名卷 voice-traces），录音 TRACE_AUDIO_DIR
      （默认同 TRACE_DIR），文件 0600。
保留：文字 TRACE_DAYS（默认 30）天，录音 TRACE_AUDIO_DAYS（默认同 TRACE_DAYS）天，按文件修改时间，
      服务启动时清一次，之后每天一次。
磁盘：录音目录总量超过 TRACE_MAX_MB（默认 1024）或磁盘剩余低于 TRACE_MIN_FREE_MB（默认 1024）时停止录音
      （文字照存），打 warning 日志。
读取：GET /api/traces*（TRACE_ADMIN_TOKEN 保护，见 voice/app.py；Caddy 对公网直接 404）和 python -m voice.trace_cli。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

from loguru import logger

from . import records as REC

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
ID_RE = re.compile(r"^[A-Z2-7]{8}$")
TRACKS = ("scammer", "persona")
AUDIO_RATE = 16000
OPUS_BITRATE = 16000
CHUNK_SECS = 10
MAX_FEEDBACK = 5          # 每通最多几条“这通有问题”
SCHEMA_VERSION = 2        # docs/TRACE_SCHEMA.md；v1 = 6ccede1 的旧格式（没有 schema_version 字段）
USAGE_KEYS = (("llm_in", "llm_in_tokens"), ("llm_out", "llm_out_tokens"), ("asr_sec", "asr_audio_sec"),
              ("tts_chars", "tts_chars"))
CLEANUP_INTERVAL_SECS = 86400
SIP_CONSENT = "sip-text-only"
try:  # 与 deepsuck 跨回合拼接窗口一致（extractors.json 的 stitch.window）
    from deepsuck.extractors import _ST as _STITCH
    HOLD = int(_STITCH.get("window", 3))
except Exception:  # noqa: BLE001
    HOLD = 3


def _env(env):
    return os.environ if env is None else env


def _int(env, key: str, default: int) -> int:
    try:
        return int(float(_env(env).get(key, "") or default))
    except ValueError:
        return default


def enabled(env=None) -> bool:
    return _env(env).get("VOICE_TRACE", "1").strip() != "0"


def trace_dir(env=None) -> Path:
    d = _env(env).get("TRACE_DIR", "").strip()
    return Path(d) if d else REC.data_root(env) / "traces"


def days(env=None) -> int:
    return max(1, _int(env, "TRACE_DAYS", 30))


def audio_dir(env=None) -> Path:
    d = _env(env).get("TRACE_AUDIO_DIR", "").strip()
    return Path(d) if d else trace_dir(env)


def audio_days(env=None) -> int:
    return max(1, _int(env, "TRACE_AUDIO_DAYS", days(env)))


def feedback_hours(env=None) -> int:
    """通话开始后多少小时内还能点“这通有问题”（只认刚打过的这一通）。"""
    return max(1, _int(env, "TRACE_FEEDBACK_HOURS", 6))


def max_bytes(env=None) -> int:
    return max(0, _int(env, "TRACE_MAX_MB", 1024)) * 1024 * 1024


def min_free_bytes(env=None) -> int:
    return max(0, _int(env, "TRACE_MIN_FREE_MB", 1024)) * 1024 * 1024


def audio_enabled(env=None) -> bool:
    return _env(env).get("TRACE_AUDIO", "1").strip() != "0"


def new_id() -> str:
    """8 位 base32 通话编号（40 bit 随机）。"""
    return base64.b32encode(secrets.token_bytes(5)).decode("ascii")


def valid_id(tid: str) -> bool:
    return bool(ID_RE.match(str(tid or "")))


def iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), TZ).isoformat(timespec="milliseconds")


_SELF_NAME: Optional[re.Pattern] = None
_NAME_TITLES: tuple = ()


def _self_name_re():
    """自报 / 转述姓名（“我叫张伟”“我是李明警官”“他叫王强”“姓名是王小红”）：共享提取规则只认收款人/户名，这里补上。
    姓氏表和称呼表复用 core/extractors.json 的 nameRules，打码用共享的 mask_name。"""
    global _SELF_NAME, _NAME_TITLES
    if _SELF_NAME is None:
        from deepsuck.extractors import _SURNAMES, _TITLES

        _NAME_TITLES = tuple(_TITLES) + ("警官", "警察", "民警", "同志", "先生", "女士", "小姐", "专员", "客服",
                                         "主任", "科长", "处长", "局长", "队长", "师傅", "阿姨", "大姐", "大哥")
        stop = "|".join(re.escape(t) for t in sorted(_NAME_TITLES, key=len, reverse=True))
        _SELF_NAME = re.compile(
            r"(?:(?:我|他|她|对方|本人)(?:的名字|的姓名)?(?:叫|是)|名字(?:是|叫)|姓名(?:是|叫|为)?|叫我)\s*[:：]?\s*"
            r"([" + _SURNAMES + r"][\u4e00-\u9fa5]{1,2}?)"
            r"(?=" + stop + r"|的|啊|呀|吧|呢|哈|啦|嘛|哦|[^\u4e00-\u9fa5]|$)")
    return _SELF_NAME


def _mask_self_names(t: str) -> str:
    from deepsuck.redact import mask_name

    rx = _self_name_re()

    def sub(m):
        n = m.group(1)
        if any(n.endswith(x) or n[1:].startswith(x) for x in _NAME_TITLES):  # “王经理”“李总”是称呼
            return m.group(0)
        return m.group(0)[: m.start(1) - m.start(0)] + mask_name(n)
    return rx.sub(sub, t)


def redact(text) -> str:
    from deepsuck.extractors import extract_sensitive
    from deepsuck.redact import redact_text

    t = "" if text is None else str(text)
    return _mask_self_names(redact_text(t, extract_sensitive(t)))


def key_hash(key: str) -> str:
    return hashlib.sha256(("deepsuck-feedback:" + str(key or "")).encode("utf-8")).hexdigest()[:32]


def usage_delta(now: Optional[Mapping], before: Optional[Mapping]) -> dict:
    """Ticket.usage（asr_sec/tts_chars/llm_in/llm_out）两次快照之差，换成 trace 字段名。"""
    now, before = now or {}, before or {}
    out = {}
    for k, name in USAGE_KEYS:
        v = float(now.get(k, 0) or 0) - float(before.get(k, 0) or 0)
        out[name] = round(max(0.0, v), 2) if k == "asr_sec" else int(max(0, v))
    return out


def mask_caller(num) -> str:
    from deepsuck.redact import mask_phone

    s = str(num or "").strip()
    if not s:
        return ""
    d = "".join(c for c in s if c.isdigit())
    return mask_phone(d) if len(d) >= 5 else "***"


# ---- 版本 ----
_CODE: Optional[str] = None


def _git_sha(root: Path) -> str:
    """不调用 git：读 .git（开发机）或镜像里的 .gitmeta（Dockerfile 从构建上下文拷的 HEAD 和 refs）。"""
    for gd in (root / ".git", root / ".gitmeta"):
        common = gd
        try:
            if gd.is_file():  # git worktree：.git 是一行 "gitdir: ..."，refs 在 commondir
                gd = Path(gd.read_text().split(":", 1)[1].strip())
                c = gd / "commondir"
                common = (gd / c.read_text().strip()).resolve() if c.exists() else gd
            head = (gd / "HEAD").read_text().strip()
        except (OSError, IndexError):
            continue
        if not head.startswith("ref:"):
            return head[:7]
        ref = head[4:].strip()
        for d in (gd, common):
            try:
                return (d / ref).read_text().strip()[:7]
            except OSError:
                pass
        try:
            for line in (common / "packed-refs").read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split()[0][:7]
        except OSError:
            pass
    return ""


def code_version() -> str:
    global _CODE
    if _CODE is None:
        _CODE = (os.environ.get("GIT_SHA", "").strip()[:7] or _git_sha(ROOT) or "unknown")
    return _CODE


_PROMPT_VER: Optional[str] = None


def prompt_version() -> str:
    """提示词模板版本：voice/persona.py + personas.json 的短哈希（具体每轮的提示词另记 prompt_sha）。"""
    global _PROMPT_VER
    if _PROMPT_VER is None:
        h = hashlib.sha1()
        for p in (ROOT / "voice" / "persona.py", ROOT / "site" / "assets" / "core" / "personas.json"):
            try:
                h.update(p.read_bytes())
            except OSError:
                pass
        _PROMPT_VER = h.hexdigest()[:8]
    return _PROMPT_VER


# ---- 文件 ----
def _append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def dir_bytes(env=None) -> int:
    """录音目录（和文字目录，二者不同时都算）的总字节数。"""
    total = 0
    for d in {trace_dir(env), audio_dir(env)}:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return total


def disk_free(path: Path) -> int:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return 1 << 62


def audio_room(env=None, free_fn=disk_free) -> tuple:
    """(还能写多少字节录音, 不能录的原因或 "")。"""
    d = audio_dir(env)
    used, cap = dir_bytes(env), max_bytes(env)
    free, floor = free_fn(d), min_free_bytes(env)
    room = min(cap - used, free - floor)
    if cap - used <= 0:
        return 0, f"录音目录已达上限 {cap // 1048576} MB"
    if free - floor <= 0:
        return 0, f"磁盘剩余 {free // 1048576} MB 低于 {floor // 1048576} MB"
    return room, ""


_STATS_LOCK = threading.Lock()


def count(kind: str, n: int = 1, env=None, now: Optional[float] = None) -> None:
    """无内容的计数（不含任何文字、编号、IP）：stats.json {日期: {calls, consent, noConsent, sip, turns}}。"""
    if not enabled(env):
        return
    p = trace_dir(env) / "stats.json"
    day = datetime.fromtimestamp(now or time.time(), TZ).strftime("%Y-%m-%d")
    with _STATS_LOCK:
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            data = {}
        row = data.setdefault(day, {})
        row[kind] = int(row.get(kind, 0)) + n
        try:
            REC._private_write(p, json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        except OSError as e:
            logger.warning(f"通话计数写入失败: {e}")


# ---- 录音 ----
class TrackEncoder:
    """一轨 16k 单声道 PCM → ogg/opus，后台线程边收边编码（不阻塞管线）。超出字节预算就停。"""

    def __init__(self, path: Path, sample_rate: int = AUDIO_RATE, on_full: Optional[Callable[[], None]] = None):
        self.path, self.rate = path, sample_rate
        self.q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=64)
        self.samples = 0
        self.error = ""
        self.closed = False
        self._t = threading.Thread(target=self._run, name=f"trace-enc-{path.stem}", daemon=True)
        self._t.start()

    def write(self, pcm: bytes) -> None:
        if self.closed or not pcm:
            return
        try:
            self.q.put_nowait(bytes(pcm))
        except queue.Full:
            self.error = self.error or "encoder backlog, dropped audio"

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.q.put(None)

    def join(self, timeout: Optional[float] = None) -> None:
        self._t.join(timeout)

    def _run(self) -> None:
        import av
        import numpy as np

        out = st = None
        try:
            while True:
                pcm = self.q.get()
                if pcm is None:
                    break
                if out is None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    os.close(fd)
                    out = av.open(str(self.path), "w", format="ogg")
                    st = out.add_stream("libopus", rate=self.rate)
                    st.layout = "mono"
                    st.bit_rate = OPUS_BITRATE
                arr = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).reshape(1, -1)
                fr = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
                fr.sample_rate, fr.pts = self.rate, self.samples
                self.samples += arr.shape[1]
                for pkt in st.encode(fr):
                    out.mux(pkt)
            if out is not None:
                for pkt in st.encode(None):
                    out.mux(pkt)
        except Exception as e:  # 编码失败不影响通话
            self.error = f"{type(e).__name__}: {e}"
            logger.warning(f"录音编码失败（{self.path.name}）: {e}")
        finally:
            if out is not None:
                try:
                    out.close()
                except Exception:
                    pass

    @property
    def seconds(self) -> float:
        return round(self.samples / self.rate, 1)


class AudioSink:
    """接 AudioBufferProcessor 的 on_track_audio_data：user = 对方，bot = 人设。"""

    def __init__(self, trace: "CallTrace", room: int):
        self.trace, self.room = trace, room
        self.enc = {k: TrackEncoder(trace.audio_path(k)) for k in TRACKS}
        self.stopped = ""
        self._bytes = 0

    def feed(self, user: bytes, bot: bytes, sample_rate: int) -> None:
        if self.stopped:
            return
        if sample_rate != AUDIO_RATE:
            self.stop(f"unexpected sample rate {sample_rate}")
            return
        # opus 16 kbps ≈ 每秒 2 KB / 轨；按这个估算写入量，留余量
        secs = max(len(user), len(bot)) / (2 * sample_rate)
        self._bytes += int(secs * OPUS_BITRATE / 8 * len(TRACKS) * 1.2) + 4096
        if self._bytes > self.room:
            self.stop("录音达到磁盘上限")
            return
        if self.trace.free_fn(audio_dir(self.trace.env)) < min_free_bytes(self.trace.env):
            self.stop("磁盘剩余不足")
            return
        self.enc["scammer"].write(user)
        self.enc["persona"].write(bot)

    def stop(self, why: str) -> None:
        if not self.stopped:
            self.stopped = why
            logger.warning(f"通话 {self.trace.id}: 停止录音（{why}），文字照存")
            self.trace.event("audio_stopped", reason=why)
        for e in self.enc.values():
            e.close()

    def close(self) -> None:
        for e in self.enc.values():
            e.close()

    def summary(self) -> dict:
        out = {}
        for k, e in self.enc.items():
            p = e.path
            out[k] = {"file": p.name, "bytes": p.stat().st_size if p.exists() else 0, "seconds": e.seconds}
            if e.error:
                out[k]["error"] = e.error
        if self.stopped:
            out["stopped"] = self.stopped
        return out


# ---- 一通电话 ----
class CallTrace:
    def __init__(self, *, channel: str, consent, persona: str, scenario: str, model: str, engine: str = "llm",
                 caller: str = "", trace_id: Optional[str] = None, env=None, clock=time.time,
                 free_fn=disk_free, prompt_sha: Optional[Callable[[], str]] = None, tts_voice: str = "",
                 asr_model: str = "", tts_model: str = "", usage_fn: Optional[Callable[[], Optional[dict]]] = None,
                 feedback_key: str = ""):
        self.env, self.clock, self.free_fn = env, clock, free_fn
        self.channel = channel
        self.consent = SIP_CONSENT if channel == "phone" else bool(consent is True)
        # 脱敏文字每通都存（VOICE_TRACE=0 时全关）；录音只在网页通话勾选同意时存
        self.store = enabled(env)
        self.id = trace_id if valid_id(trace_id or "") else new_id()
        self.persona, self.scenario, self.model, self.engine = persona, scenario, model, engine
        self.tts_voice, self.asr_model, self.tts_model = tts_voice or "", asr_model or "", tts_model or ""
        self.prompt_sha = prompt_sha or (lambda: "")
        self.usage_fn = usage_fn or (lambda: None)
        self._usage_mark: dict = {}
        # 会话（可选）：回合文字以 Session.messages 为准——跨回合拼接（卡号分几句报）会回头给前几句补打码，
        # 所以回合先压住 HOLD 个骗子回合再落盘，落盘时取会话里的最终脱敏文本
        self.session = None
        self._pending: List[dict] = []
        self.turns = 0
        self.interrupted = 0
        self.reason = ""
        self.audio: Optional[AudioSink] = None
        self._cur: Optional[dict] = None
        self._ended = False
        self.t0 = clock()
        count("calls", env=env)
        count("sip" if channel == "phone" else ("consent" if self.consent is True else "noConsent"), env=env)
        if self.store:
            self._write({"type": "start", "t": iso(self.t0), "started_at": iso(self.t0), "id": self.id,
                         "channel": channel, "consent": self.consent, "persona": persona, "persona_id": persona,
                         "scenario": scenario, "model": model, "engine": engine, "asr_model": self.asr_model,
                         "tts_model": self.tts_model, "tts_voice": self.tts_voice, "code": code_version(),
                         "promptVersion": prompt_version(),
                         **({"fk": key_hash(feedback_key)} if feedback_key and channel == "web" else {}),
                         **({"caller": mask_caller(caller)} if channel == "phone" and caller else {})})

    @property
    def path(self) -> Path:
        return trace_dir(self.env) / f"{self.id}.jsonl"

    def audio_path(self, track: str) -> Path:
        return audio_dir(self.env) / f"{self.id}-{track}.ogg"

    def _write(self, obj: dict) -> None:
        if not self.store:
            return
        try:
            _append(self.path, {"schema_version": SCHEMA_VERSION, "call_id": self.id, **obj})
        except OSError as e:
            logger.warning(f"通话追踪写入失败: {e}")

    def event(self, event_type: str, **kw) -> None:
        self._write({"type": event_type, "t": iso(self.clock()), **kw})

    # ---- 录音 ----
    def audio_processor(self):
        """勾选同意的网页通话返回一个 AudioBufferProcessor（放在 transport.output() 之后），否则 None。"""
        if not (self.store and self.consent is True and audio_enabled(self.env)):
            return None
        room, why = audio_room(self.env, self.free_fn)
        if why:
            logger.warning(f"通话 {self.id}: 不录音（{why}），文字照存")
            self.event("audio_stopped", reason=why)
            return None
        from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor

        self.audio = AudioSink(self, room)
        buf = AudioBufferProcessor(sample_rate=AUDIO_RATE, num_channels=1, buffer_size=AUDIO_RATE * 2 * CHUNK_SECS,
                                   auto_start_recording=True)

        @buf.event_handler("on_track_audio_data")
        async def _on_tracks(_p, user, bot, sample_rate, _ch):
            if self.audio is not None:
                self.audio.feed(user, bot, sample_rate)

        return buf

    # ---- 对话（从看板通知里拼回合）----
    def observe(self, msg: dict) -> None:
        if not self.store or self._ended:
            return
        try:
            self._observe(msg)
        except Exception as e:  # 记录失败不影响通话
            logger.warning(f"通话追踪记录失败: {e}")

    def _new(self) -> dict:
        return {"t": iso(self.clock()), "asr": [], "turn_nos": [], "intents": [], "reply": [], "intel": [],
                "tactics": [], "interrupted": False}

    def _observe(self, m: dict) -> None:
        typ = m.get("type")
        if typ == "scammer":
            if self._cur is not None and self._cur["reply"]:
                self._flush()
            if self._cur is None:
                self._cur = self._new()
            c = self._cur
            c["asr"].append(redact(m.get("text")))
            if isinstance(m.get("turn"), int):
                c["turn_nos"].append(m["turn"])
            if m.get("intent"):
                c["intents"].append(m["intent"])
            c["intel"] += [{k: i.get(k) for k in ("type", "label", "masked")} for i in m.get("newIntel") or []]
            c["tactics"] += [t.get("id") for t in m.get("tactics") or [] if t.get("id") not in c["tactics"]]
        elif typ == "bot":
            intent = m.get("intent")
            if intent in ("opening", "disclosure", "hangup"):
                self.event("bot", kind=intent, text=redact(m.get("text")))
                return
            if self._cur is None:
                self._cur = self._new()
            self._cur["reply"].append(redact(m.get("text")))
            if intent and not self._cur["intents"]:
                self._cur["intents"].append(intent)
        elif typ == "filler":
            if self._cur is not None:
                self._cur["filler"] = redact(m.get("text"))
        elif typ == "latency":
            row = {k: v for k, v in m.items() if k not in ("type", "turn")}
            if self._cur is not None and "latency" not in self._cur:
                self._cur["latency"] = row
            else:
                self.event("latency", **row)
        elif typ == "llm_done":
            # 大模型整句耗时（LLMFullResponseStart → End），常在回复首包之后才到
            if self._cur is not None and self._cur.get("llm_full_ms") is None:
                self._cur["llm_full_ms"] = m.get("full_ms")
        elif typ == "interrupt":
            # 人设在说话时对方开口：记在正在播回复的这一轮上；还没有回合（开场白被打断）就单写一行
            if self._cur is not None and self._cur["reply"]:
                self._cur["interrupted"] = True
            else:
                self.event("interrupt", during="opening" if self.turns == 0 and not self._pending else "filler")
        elif typ == "limit":
            self.reason = self.reason or str(m.get("reason") or "limit")

    def _flush(self) -> None:
        c, self._cur = self._cur, None
        if c and (c["asr"] or c["reply"]):
            c["prompt"] = self.prompt_sha()
            # 本轮用量 = 上一轮收尾到本轮收尾之间计量的增量（取各服务回报的 usage）
            snap = dict(self.usage_fn() or {})
            c["usage"] = usage_delta(snap, self._usage_mark)
            if snap:
                self._usage_mark = snap
            self._pending.append(c)
        self._drain()

    def _final_asr(self, c: dict) -> str:
        msgs = [m for m in getattr(self.session, "messages", []) if m.get("role") == "scammer"]
        if self.session is not None and c["turn_nos"] and all(0 < n <= len(msgs) for n in c["turn_nos"]):
            return " ".join(x for x in (redact(msgs[n - 1].get("text")) for n in c["turn_nos"]) if x)
        return " ".join(x for x in c["asr"] if x)

    def _drain(self, all_: bool = False) -> None:
        cur = getattr(self.session, "turn", 0) if self.session is not None else None
        while self._pending:
            c = self._pending[0]
            if not all_ and cur is not None and c["turn_nos"] and max(c["turn_nos"]) > cur - HOLD:
                return
            self._pending.pop(0)
            self._write_turn(c)

    def _write_turn(self, c: dict) -> None:
        self.turns += 1
        self.interrupted += 1 if c.get("interrupted") else 0
        lat = c.get("latency") or {}
        u = c.get("usage") or usage_delta(None, None)
        self._write({"type": "turn", "turn": self.turns, "n": self.turns, "ts": c["t"], "t": c["t"],
                     "persona_id": self.persona, "model": self.model,
                     "llm_in_tokens": u["llm_in_tokens"], "llm_out_tokens": u["llm_out_tokens"],
                     "llm_first_token_ms": lat.get("llm_ttft"), "llm_full_ms": c.get("llm_full_ms"),
                     "first_audible_ms": lat.get("first_audible"), "e2e_reply_ms": lat.get("e2e_reply"),
                     "asr_audio_sec": u["asr_audio_sec"], "tts_chars": u["tts_chars"], "tts_voice": self.tts_voice,
                     "interrupted": bool(c.get("interrupted")),
                     "asr": self._final_asr(c),
                     "intent": c["intents"][-1] if c["intents"] else None,
                     **({"intents": c["intents"]} if len(set(c["intents"])) > 1 else {}),
                     "reply": " ".join(c["reply"]), **({"filler": c["filler"]} if c.get("filler") else {}),
                     "intel": c["intel"], "tactics": c["tactics"], "latency": c.get("latency"),
                     "prompt": c.get("prompt") or self.prompt_sha(),
                     "promptVersion": prompt_version(), "code": code_version(), "persona": self.persona,
                     "scenario": self.scenario, "consent": self.consent})

    def end(self, reason: str = "", stats: Optional[dict] = None, latency: Optional[dict] = None,
            usage: Optional[dict] = None, cost_cny: Optional[float] = None) -> None:
        """写汇总行；录音在后台线程收尾，编码完再补一行 audio（不阻塞挂断）。"""
        if self._ended:
            return
        self._flush()
        self._drain(all_=True)
        self._ended = True
        reason = self.reason or reason or "unknown"
        now = self.clock()
        count("turns", self.turns, env=self.env)
        total = usage if usage is not None else (self.usage_fn() or {})
        self._write({"type": "end", "t": iso(now), "started_at": iso(self.t0), "ended_at": iso(now),
                     "duration_sec": round(max(0.0, now - self.t0), 1), "exit_reason": reason, "reason": reason,
                     "consent": self.consent, "persona_id": self.persona, "model": self.model,
                     "tts_voice": self.tts_voice, "turns": self.turns, "interrupted_turns": self.interrupted,
                     "usage_total": usage_delta(total, None),
                     **({"cost_cny": round(float(cost_cny), 6)} if cost_cny is not None else {}),
                     "stats": stats or {}, "latency": latency or {}, "usage": usage or {},
                     "audio": self.audio is not None})
        if self.audio is not None:
            sink = self.audio
            sink.close()

            def finish():
                for e in sink.enc.values():
                    e.join(60)
                self._write({"type": "audio", "t": iso(self.clock()), **sink.summary()})

            threading.Thread(target=finish, name=f"trace-fin-{self.id}", daemon=True).start()


# ---- 反馈、读取、清理 ----
def _lines(path: Path) -> List[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def _ts(s) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except (TypeError, ValueError):
        return None


def feedback(trace_id: str, note: str = "", turn=None, env=None, now: Optional[float] = None,
             key: Optional[str] = None) -> Optional[dict]:
    """“这通有问题”：只认当前这一通网页通话——编号存在、带 /api/offer 发给这个页面的反馈口令、
    通话开始不超过 TRACE_FEEDBACK_HOURS 小时；说明脱敏、截 200 字；每通最多 MAX_FEEDBACK 条。
    返回 None = 没有这通（404）；{"ok": False, "error": "forbidden" | "expired" | "too many"}。"""
    if not valid_id(trace_id):
        return None
    p = trace_dir(env) / f"{trace_id}.jsonl"
    rows = _lines(p)
    if not rows or rows[0].get("type") != "start" or rows[0].get("channel") != "web":
        return None
    st = rows[0]
    if st.get("fk"):
        if not key or not hmac.compare_digest(key_hash(key), str(st["fk"])):
            return {"ok": False, "error": "forbidden"}
    elif st.get("consent") is not True:  # v1 旧记录（没有口令）：沿用只认同意的规则
        return None
    t0 = _ts(st.get("t"))
    now = time.time() if now is None else now
    if t0 is not None and now - t0 > feedback_hours(env) * 3600:
        return {"ok": False, "error": "expired"}
    if sum(1 for r in rows if r.get("type") == "feedback") >= MAX_FEEDBACK:
        return {"ok": False, "error": "too many"}
    try:
        turn = int(turn) if turn not in (None, "") else None
        if turn is not None and not 0 <= turn <= 999:
            turn = None
    except (TypeError, ValueError):
        turn = None
    row = {"schema_version": SCHEMA_VERSION, "call_id": trace_id, "type": "feedback", "t": iso(now),
           "flagged": True, "note": redact(str(note or "")[:200]).strip(), "turn": turn}
    _append(p, row)
    return {"ok": True}


# ---- 前端上报（GitHub #3：连接失败原因写进同一编号的追踪） ----
CLIENT_STAGES = ("connected", "ice_failed", "ice_timeout", "offer_failed", "mic_denied", "media_error", "dc_timeout")
CLIENT_DETAIL_KEYS = ("ice", "conn", "gather", "relayOffered", "local", "remote", "path", "elapsedMs", "browser",
                      "online", "error")
MAX_CLIENT_REPORTS = 10
_STAGE_KEY = {"connected": "clientConnected", "ice_failed": "clientIceFailed", "ice_timeout": "clientIceTimeout",
              "offer_failed": "clientOfferFailed", "mic_denied": "clientMicDenied", "media_error": "clientMediaError",
              "dc_timeout": "clientDcTimeout"}


def _clean_detail(detail) -> dict:
    """只留白名单字段、标量值、短字符串（脱敏）；不收 SDP、IP 之类的原始数据。"""
    out: dict = {}
    if not isinstance(detail, dict):
        return out
    for k in CLIENT_DETAIL_KEYS:
        v = detail.get(k)
        if isinstance(v, bool) or v is None:
            if v is not None:
                out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = max(-1, min(int(v), 10_000_000))
        elif isinstance(v, str):
            out[k] = redact(re.sub(r"\d{1,3}(?:\.\d{1,3}){3}", "<ip>", v[:80])).strip()
    return out


def client_report(trace_id: Optional[str], stage: str, reason: str = "", detail=None, env=None,
                  now: Optional[float] = None) -> dict:
    """前端上报连接结果。总是只计一次数（无内容）；同意存储的网页通话再把阶段/原因/少量诊断字段
    追加进同一编号的 JSONL（connected → client_connected，其余 → client_error）。每通最多 MAX_CLIENT_REPORTS 条。"""
    if stage not in CLIENT_STAGES:
        return {"ok": False, "error": "bad stage"}
    count(_STAGE_KEY[stage], env=env, now=now)
    clean = _clean_detail(detail)
    if stage == "connected" and str(clean.get("path", "")).startswith("relay"):
        count("clientRelay", env=env, now=now)
    if not trace_id or not valid_id(trace_id):
        return {"ok": True, "stored": False}
    p = trace_dir(env) / f"{trace_id}.jsonl"
    rows = _lines(p)
    if not rows or rows[0].get("type") != "start" or rows[0].get("channel") != "web":
        return {"ok": True, "stored": False}
    if sum(1 for r in rows if r.get("type") in ("client_error", "client_connected")) >= MAX_CLIENT_REPORTS:
        return {"ok": True, "stored": False}
    row = {"schema_version": SCHEMA_VERSION, "call_id": trace_id,
           "type": "client_connected" if stage == "connected" else "client_error", "t": iso(now), "stage": stage,
           "reason": redact(re.sub(r"\d{1,3}(?:\.\d{1,3}){3}", "<ip>", str(reason or "")[:200])).strip(),
           "detail": clean}
    _append(p, row)
    return {"ok": True, "stored": True}


def _audio_file(trace_id: str, track: str, env=None) -> Optional[Path]:
    """录音文件：先找 TRACE_AUDIO_DIR，再找 TRACE_DIR（改目录前录下的旧文件）。"""
    for d in (audio_dir(env), trace_dir(env)):
        p = d / f"{trace_id}-{track}.ogg"
        if p.is_file():
            return p
    return None


def audio_file(trace_id: str, track: str, env=None) -> Optional[Path]:
    if not valid_id(trace_id) or track not in TRACKS:
        return None
    return _audio_file(trace_id, track, env)


def load(trace_id: str, env=None) -> Optional[dict]:
    if not valid_id(trace_id):
        return None
    rows = _lines(trace_dir(env) / f"{trace_id}.jsonl")
    if not rows:
        return None
    audio = {}
    for k in TRACKS:
        p = _audio_file(trace_id, k, env)
        if p is not None:
            audio[k] = {"file": str(p), "bytes": p.stat().st_size}
    return {"id": trace_id, "lines": rows, "audio": audio}


def _files(env=None) -> List[Path]:
    d = trace_dir(env)
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("*.jsonl") if valid_id(p.stem)), key=lambda p: p.stat().st_mtime, reverse=True)


def _summary(p: Path, rows: List[dict], env=None) -> dict:
    st = rows[0]
    end = next((r for r in reversed(rows) if r.get("type") == "end"), {})
    fb = [r for r in rows if r.get("type") == "feedback"]
    return {"id": p.stem, "t": st.get("t"), "channel": st.get("channel"), "consent": st.get("consent"),
            "persona": st.get("persona"), "scenario": st.get("scenario"), "code": st.get("code"),
            "turns": end.get("turns"), "reason": end.get("reason"),
            "feedback": len(fb), "flagged": bool(fb),
            "audio": any(_audio_file(p.stem, k, env) is not None for k in TRACKS)}


def list_traces(since: Optional[str] = None, limit: int = 50, env=None, flagged: bool = False) -> List[dict]:
    """最近的通话（按文件修改时间倒序）。flagged=True 只列被点了“这通有问题”的，附上各条说明。"""
    out = []
    for p in _files(env):
        rows = _lines(p)
        if not rows:
            continue
        if since and str(rows[0].get("t", "")) < since:
            continue
        row = _summary(p, rows, env)
        if flagged:
            if not row["flagged"]:
                continue
            row["notes"] = [{"t": r.get("t"), "turn": r.get("turn"), "note": r.get("note") or ""}
                            for r in rows if r.get("type") == "feedback"]
        out.append(row)
        if len(out) >= max(1, min(int(limit or 50), 500)):
            break
    return out


def _call_usage(rows: List[dict]) -> dict:
    """一通的用量：有 end 行取 usage_total（含告别语等轮外用量），否则把各轮加起来（通话中/异常退出）。"""
    end = next((r for r in reversed(rows) if r.get("type") == "end"), None)
    if end is not None and isinstance(end.get("usage_total"), dict):
        return dict(end["usage_total"])
    if end is not None and isinstance(end.get("usage"), dict) and end["usage"]:
        return usage_delta(end["usage"], None)  # v1 记录：end.usage 是 Ticket.usage 原样
    tot = usage_delta(None, None)
    for r in rows:
        if r.get("type") == "turn":
            for _k, name in USAGE_KEYS:
                tot[name] += r.get(name) or 0
    tot["asr_audio_sec"] = round(tot["asr_audio_sec"], 2)
    return tot


def usage_by_day(since: Optional[str] = None, until: Optional[str] = None, env=None) -> dict:
    """按天（UTC+8，以通话开始时间计）汇总用量，给成本监控（#20）直接用的 JSON。since/until 为 YYYY-MM-DD（含）。"""
    days_: Dict[str, dict] = {}
    for p in _files(env):
        rows = _lines(p)
        if not rows or rows[0].get("type") != "start":
            continue
        st = rows[0]
        day = str(st.get("t", ""))[:10]
        if not day or (since and day < since) or (until and day > until):
            continue
        end = next((r for r in reversed(rows) if r.get("type") == "end"), {})
        d = days_.setdefault(day, {"date": day, "calls": 0, "consent_calls": 0, "audio_calls": 0, "sip_calls": 0,
                                   "flagged_calls": 0, "turns": 0, "interrupted_turns": 0, "duration_sec": 0.0,
                                   "cost_cny": 0.0, **usage_delta(None, None), "by_model": {}, "by_persona": {},
                                   "exit_reasons": {}})
        u = _call_usage(rows)
        d["calls"] += 1
        d["consent_calls"] += 1 if st.get("consent") is True else 0
        d["sip_calls"] += 1 if st.get("channel") == "phone" else 0
        d["audio_calls"] += 1 if any(_audio_file(p.stem, k, env) for k in TRACKS) else 0
        d["flagged_calls"] += 1 if any(r.get("type") == "feedback" for r in rows) else 0
        turns = [r for r in rows if r.get("type") == "turn"]
        d["turns"] += end.get("turns") if isinstance(end.get("turns"), int) else len(turns)
        d["interrupted_turns"] += sum(1 for r in turns if r.get("interrupted"))
        if end.get("duration_sec") is not None:
            d["duration_sec"] = round(d["duration_sec"] + float(end["duration_sec"]), 1)
        if end.get("cost_cny") is not None:
            d["cost_cny"] = round(d["cost_cny"] + float(end["cost_cny"]), 6)
        for _k, name in USAGE_KEYS:
            d[name] = round(d[name] + (u.get(name) or 0), 2) if name == "asr_audio_sec" else d[name] + int(u.get(name) or 0)
        m = d["by_model"].setdefault(str(st.get("model") or ""), {"calls": 0, "llm_in_tokens": 0, "llm_out_tokens": 0})
        m["calls"] += 1
        m["llm_in_tokens"] += int(u.get("llm_in_tokens") or 0)
        m["llm_out_tokens"] += int(u.get("llm_out_tokens") or 0)
        pid = str(st.get("persona_id") or st.get("persona") or "")
        d["by_persona"][pid] = d["by_persona"].get(pid, 0) + 1
        why = str(end.get("exit_reason") or end.get("reason") or "unfinished")
        d["exit_reasons"][why] = d["exit_reasons"].get(why, 0) + 1
    return {"schema_version": SCHEMA_VERSION, "generated_at": iso(), "tz": "+08:00",
            "days": [days_[k] for k in sorted(days_)]}


def cleanup(env=None, now: Optional[float] = None) -> int:
    """按修改时间删除过期文件，返回删除的文件数：文字（*.jsonl）超过 TRACE_DAYS 天，录音（*.ogg）超过
    TRACE_AUDIO_DAYS 天。stats.json 只有计数，保留。"""
    now = now or time.time()
    removed = 0
    plan = [(trace_dir(env), ".jsonl", days(env)), (audio_dir(env), ".ogg", audio_days(env))]
    if audio_dir(env) != trace_dir(env):
        plan.append((trace_dir(env), ".ogg", audio_days(env)))  # 改目录前录下的旧录音
    for d, suffix, keep in plan:
        if not d.is_dir():
            continue
        cutoff = now - keep * 86400
        for p in d.iterdir():
            try:
                if p.is_file() and p.suffix == suffix and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError as e:
                logger.warning(f"清理 {p.name} 失败: {e}")
    if removed:
        logger.info(f"通话追踪清理：删除 {removed} 个过期文件")
    return removed


async def cleanup_loop(interval: float = CLEANUP_INTERVAL_SECS, env=None) -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup, env)
        except Exception as e:
            logger.warning(f"通话追踪清理失败: {e}")
        await asyncio.sleep(interval)


def describe(env=None) -> dict:
    return {"enabled": enabled(env), "schema": SCHEMA_VERSION, "dir": str(trace_dir(env)),
            "audioDir": str(audio_dir(env)), "days": days(env), "audioDays": audio_days(env),
            "audio": audio_enabled(env), "maxMB": max_bytes(env) // 1048576,
            "minFreeMB": min_free_bytes(env) // 1048576, "feedbackHours": feedback_hours(env),
            "adminToken": bool(_env(env).get("TRACE_ADMIN_TOKEN")), "code": code_version()}
