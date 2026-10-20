"""#194：eval/llm_scammer.py --responder llm 的被骗方：大模型扮人设，提示词取自网页 site/assets/js/llm.js。

- 提示词来源（PromptSource）：默认是当前检出的 site/assets；--persona-prompt-ref <git ref> 时用 git archive 把那个 ref 的
  site/assets/js 和 site/assets/core 解到临时目录，不切换工作区、不改索引。提示词由 Node 直接调用那份 llm.js 生成
  （eval/persona_prompt_bridge.js），不另写一份。来源的身份是这两个目录的 git tree（或工作区文件内容）的哈希，进缓存键，
  A / B 两个 ref 不会串缓存。指定 ref 时 llm_scammer 还在 import deepsuck 之前把 DEEPSUCK_CORE_DIR 指到解出来的 core/，
  Python 过滤链、规则引擎和提示词读的是同一份 personas.json（含 eagerAsk.rule）等共享规则源，eval/ 里不放规则副本。
- 发送前过滤：Python 版 deepsuck.llmfilter.llm_pipeline（与 llm.js sanitizeReply 共用 tests/fixtures/llm_sanitize.json），
  代理模式的整条链：sanitizeReply 两遍 → dedupeTail（最近三条人设回复的尾句）→ vagueDigits，最后 Session.record_bot 再脱敏。
  过滤链的代码是当前检出的 Python 版，读的规则数据与提示词同源。
- 本轮意图、缺项与网页 demo.js produceReply 一致：Session.choose_intent(analysis)、Session.missing_goals()；开场白用规则引擎。
- 请求布局 --persona-layout：cache（默认）= 系统提示词里不随轮次变的那几行（探针比较得出）放最前面，接全部对话历史，
  本轮会变的几行（角色称呼、本轮建议策略、规则 4、规则 7）作为最后一条 system，与语音端 #169 的做法相同，前缀每轮不变、
  只往后追加，便于命中隐式缓存；web = 与网页 buildMessages 完全相同（系统提示词每轮重算，历史只留最近 16 条）。
- 模型默认 qwen3.8-flash，temperature 0.9、max_tokens 200（llm.js DEFAULTS），每个请求显式 enable_thinking=false。
"""
from __future__ import annotations

import atexit
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = Path(__file__).with_name("persona_prompt_bridge.js")
PROMPT_DIRS = ("site/assets/js", "site/assets/core")
LAYOUTS = ("cache", "web")
TEMPERATURE = 0.9   # llm.js DEFAULTS.temperature（服务端代理没设 LLM_TEMPERATURE 时也用它）
MAX_TOKENS = 200    # llm.js DEFAULTS.maxTokens
VERSION = "persona-llm-v1"
# 探针用的对方的话（已打码的样子）：场景说法、各类代称都出现，用来找出系统提示词里不随轮次变的行，也用来估最长的系统提示词
PROBE_HEARD = (
    "我是公安局反诈中心的，你的银行卡涉嫌洗钱，收款人张**，卡号 6222 **** **** 7890，转到安全账户",
    "客服这边给你退款，下载 https://ab***.example/app，钱包 TQ7x...BcDe，邮箱 a***@example.com，加微信，打这个电话",
    "刷单返利，贷款额度，同学，老板，儿子，领导，快递，理财",
)


class PromptSourceError(RuntimeError):
    pass


def _git(*args: str, binary: bool = False):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if r.returncode != 0:
        raise PromptSourceError(f"git {' '.join(args[:2])} 失败：{r.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return r.stdout if binary else r.stdout.decode("utf-8").strip()


class PromptSource:
    """人设提示词的来源：ref=None 用当前检出的 site/assets；否则从 git ref 读，不切换工作区。"""

    def __init__(self, ref: Optional[str] = None, assets_dir: Optional[Path] = None):
        self.ref = ref
        self._tmp = None
        if assets_dir is not None:  # 测试用：直接给目录
            self.dir = Path(assets_dir)
            self.commit = None
            self.key = "dir:" + self._hash_dir(self.dir)
        elif ref:
            if ref.startswith("-"):
                raise PromptSourceError(f"ref 不能以 - 开头：{ref}")
            self.commit = _git("rev-parse", "--verify", "--quiet", ref + "^{commit}")
            trees = [_git("rev-parse", f"{self.commit}:{d}") for d in PROMPT_DIRS]
            # 缓存键：ref 名、提交和两个目录的 tree 都进去（A / B 不串；同一提交换个 ref 名也重新算，宁可多花不串）
            self.key = (f"ref:{ref}@{self.commit[:12]}|tree:"
                        + hashlib.sha256("|".join(trees).encode()).hexdigest()[:16])
            self._tmp = Path(tempfile.mkdtemp(prefix="deepsuck-persona-prompt-"))
            atexit.register(shutil.rmtree, self._tmp, True)
            data = _git("archive", "--format=tar", self.commit, *PROMPT_DIRS, binary=True)
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                for m in tf.getmembers():  # 只解普通文件和目录，路径都在临时目录内
                    if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise PromptSourceError(f"ref {ref} 的归档里有不该有的条目：{m.name}")
                tf.extractall(self._tmp, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
            self.dir = self._tmp / "site" / "assets"
        else:
            self.commit = None
            self.dir = ROOT / "site" / "assets"
            self.key = "worktree:" + self._hash_dir(self.dir)
        if not (self.dir / "js" / "llm.js").exists():
            raise PromptSourceError(f"提示词来源里没有 js/llm.js：{self.dir}")
        self._proc = None
        self._lock = threading.Lock()
        self._fixed: dict = {}

    @staticmethod
    def _hash_dir(d: Path) -> str:
        h = hashlib.sha256()
        for sub in ("js", "core"):
            for p in sorted((Path(d) / sub).glob("*")):
                if p.is_file():
                    h.update(f"{sub}/{p.name}\0".encode())
                    h.update(p.read_bytes())
        return h.hexdigest()[:16]

    @property
    def label(self) -> str:
        return f"{self.ref}@{self.commit[:7]}" if self.ref and self.commit else ("worktree" if self.ref is None else str(self.ref))

    def describe(self) -> dict:
        return {"ref": self.ref, "commit": self.commit, "key": self.key, "label": self.label}

    def request(self, obj: dict) -> dict:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = subprocess.Popen(["node", str(BRIDGE), str(self.dir)], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
                atexit.register(self.close)
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        if not line:
            raise PromptSourceError("提示词桥（node）没有返回")
        out = json.loads(line)
        if not out.get("ok"):
            raise PromptSourceError(out.get("error") or "提示词桥出错")
        return out["result"]

    def close(self) -> None:
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.stdin.close()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()

    def fixed_lines(self, persona: str) -> List[int]:
        if persona not in self._fixed:
            self._fixed[persona] = self.request({"op": "probe", "persona": persona, "heard": list(PROBE_HEARD)})["fixed"]
        return self._fixed[persona]

    def messages(self, persona: str, scenario: str, hint: str, missing: List[str], transcript: List[dict],
                 layout: str = "cache") -> List[dict]:
        req = {"persona": persona, "scenario": scenario, "hint": hint, "missing": list(missing or []),
               "transcript": [{"role": m["role"], "text": m.get("text", "")} for m in transcript]}
        if layout == "web":
            return self.request({"op": "web", **req})["messages"]
        if layout != "cache":
            raise ValueError(f"layout must be one of {LAYOUTS}")
        parts = self.request({"op": "parts", **req})
        fixed = set(self.fixed_lines(persona))
        lines = parts["system"]
        head = "\n".join(x for i, x in enumerate(lines) if i in fixed)
        tail = "\n".join(x for i, x in enumerate(lines) if i not in fixed)
        return [{"role": "system", "content": head}] + parts["history"] + ([{"role": "system", "content": tail}] if tail else [])


def params_for(model: str, seed: int) -> dict:
    return {"model": model, "temperature": TEMPERATURE, "seed": seed, "enable_thinking": False, "max_tokens": MAX_TOKENS}


def version_for(source: PromptSource, layout: str) -> str:
    """缓存键里的提示词来源：内容哈希 + 布局。"""
    return f"{VERSION}|{layout}|{source.key}"


class LLMResponder:
    """一场对话的大模型被骗方。call(messages, params) -> {"content", ...}，与骗子共用 llm_scammer.Caller（缓存 + 计费）。"""

    def __init__(self, session, persona: str, scenario: str, source: PromptSource, call: Callable, model: str,
                 seed: int, layout: str = "cache"):
        from deepsuck.llmfilter import llm_pipeline
        self.s, self.persona, self.scenario, self.source = session, persona, scenario, source
        self.call, self.layout = call, layout
        self.params = params_for(model, seed)
        self._pipe = llm_pipeline

    def reply(self, analysis: dict) -> dict:
        """返回 {"text": 过滤后要发的话（可能为空串）, "raw": 模型原文, "intent": 本轮意图}；非空时已 record_bot。"""
        s = self.s
        hint = s.choose_intent(analysis)
        msgs = self.source.messages(self.persona, self.scenario, hint, s.missing_goals(), s.messages, self.layout)
        resp = self.call(msgs, self.params)
        raw = resp.get("content") or ""
        recent = [m["text"] for m in s.messages if m.get("role") == "bot"]
        text = self._pipe(raw, recent, self.persona)
        if not text.strip():
            return {"text": "", "raw": raw, "intent": hint}
        msg = s.record_bot(text, hint)
        return {"text": msg["text"], "raw": raw, "intent": hint}
