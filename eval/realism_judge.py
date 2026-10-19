"""“像不像真人”盲测的大模型评委（代理指标，默认关闭）。

    # 先 make 出 form-A.csv / form-B.csv / key.json，再显式打开大模型评委：
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --json eval/realism/judge-llm.json
    # 只估算 token 和费用，不调用：
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --dry-run

设计：
- 评委是百炼 DashScope 的 qwen3.8-flash（2026-10-19 起；之前是 qwen-plus）（OpenAI 兼容接口，非思考模式），temperature 0、固定 seed，要求 JSON 输出；
- 评委看到的内容和评测者一样：骗子消息 + 回复，不知道条件；默认逐题独立判（--judge-mode item：一题一次请求，
  评委看不到同一份表的其他题，避免“与某题雷同”式的跨题比较）；可选批量模式（--judge-mode batch：每次请求放同一份表的
  若干题，默认 10 题，即 76cef8b 的旧做法）。两种模式下同一句的 raw / humanized 都不会出现在同一次请求里，请求之间没有上下文；
- 默认评前 60 个句对（A、B 两份表各 60 题，共 120 次判断）；调用前按字符数保守估算 token 与费用，
  超过 1 元（硬上限，--max-cost 只能调低）直接拒绝运行；运行中实际费用超过上限也会停下；
- 每次请求与回复按内容哈希缓存在 eval/.judge-cache/（.gitignore），重跑不重复计费；
- 判断结果转成与人工评分相同的行格式（id / rater / human / bot / unreadable），交给 realism_blind.score() 汇总；
- 严格档（#164，--judge-profile strict）：评委提示词改为“从严审核”，对机器味（客服腔、书面语、模板套话）、复读（原样复述
  诈骗消息、回复里同一句反复）、过度配合（满口答应却没有真人的犹豫和个人细节）明确扣分；默认档（judge-v3-item）不变；
- 调用方式（#164，--judge-api）：sync = 标准同步接口；batch = 百炼 OpenAI 兼容 Batch（文件输入）接口，按实时价 50% 计费、
  没有上下文缓存折扣，异步完成（completion_window 24h），本地记下任务号，超时后重跑会接着等同一个任务、不重复提交；
- 所有请求显式 enable_thinking=false（qwen3.8 系列默认开思考）；系统提示词固定放在最前面，题目放在后面；
- 计费：同步调用按 usage.prompt_tokens_details.cached_tokens 区分缓存命中（0.1 元 / 百万）与未命中（0.8 元 / 百万）；
- API Key 只从环境变量 DASHSCOPE_API_KEY 或仓库根目录 .env 读取，不打印、不写进缓存或结果。
"""
from __future__ import annotations

import hashlib
import json
import uuid
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

MODEL = "qwen3.8-flash"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# qwen3.8-flash 单价（元 / 百万 token，华北 2 北京地域，0<输入≤1M 不分档，思考与非思考同价），
# 来源：阿里云百炼「模型调用价格」https://help.aliyun.com/zh/model-studio/model-pricing（2026-10-19 查阅，千问 Flash 表）。
# 不计免费额度和缓存折扣，按原价算，偏保守。换模型前（qwen-plus，≤128K 非思考）是 0.8 / 2.0。
PRICE_INPUT_PER_M = 0.8
PRICE_OUTPUT_PER_M = 2.7
PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing (qwen3.8-flash, 北京, 0-1M 不分档, 2026-10-19)"
# 缓存命中价（#164）：qwen3.8-flash 不是通用的 20%，模型页「输入（缓存命中）」北京 0.1 元 / 百万 token（隐式缓存命中与显式缓存命中同价）。
# 来源：https://help.aliyun.com/zh/model-studio/qwen3-8-flash「模型价格」与 https://help.aliyun.com/zh/model-studio/context-cache
# （「qwen3.8-max、qwen3.8-flash … cached_token 单价不是 input_token 单价的 20%」），2026-10-19 查阅。隐式缓存要求公共前缀 ≥1024 token。
PRICE_CACHED_INPUT_PER_M = 0.1
# Batch（#164）：「OpenAI 兼容-Batch（文件输入）」北京地域支持 qwen3.8-flash，输入输出均按实时价 50%，不支持上下文缓存折扣；
# 来源：https://help.aliyun.com/zh/model-studio/batch-interfaces-compatible-with-openai（适用范围、计费说明），
# qwen3.8-flash 模型页北京地域「批量推理：支持」，2026-10-19 查阅。
BATCH_PRICE_FACTOR = 0.5
BATCH_SOURCE = "https://help.aliyun.com/zh/model-studio/batch-interfaces-compatible-with-openai (北京 qwen3.8-flash 支持, 50%, 无缓存折扣, 2026-10-19)"
APIS = ("sync", "batch")
PROFILES = ("default", "strict")
HARD_MAX_COST_CNY = 1.0
DEFAULT_PAIRS = 60
DEFAULT_BATCH = 10
DEFAULT_SEED = 1
PROMPT_VERSION = "judge-v1"          # 批量模式（提示词与 76cef8b 相同，旧缓存仍可命中）
PROMPT_VERSION_ITEM = "judge-v3-item"      # v3：说明回复里的“／”是分成几条连发的消息
PROMPT_VERSION_STRICT = "judge-strict-v1"  # #164 严格档（逐题）
MODES = ("item", "batch")
DEFAULT_MODE = "item"
CACHE_DIR = ROOT / "eval" / ".judge-cache"
# 每题输出上限（JSON 字段 + 不超过 20 字的理由），用于估算和 max_tokens
OUT_TOKENS_PER_ITEM = 60
OUT_TOKENS_OVERHEAD = 30

SYSTEM_PROMPT = (
    "你在做一项盲测评审。每道题是一条诈骗分子发来的消息，以及对方的一条回复。"
    "回复有的是真人随手打的，有的是聊天机器人生成的，比例未知。"
    "请逐题独立判断回复是真人还是机器人，只看这一题本身，不要和其他题比较。\n"
    "对每道题给出：\n"
    "- bot：你认为回复是机器人写的填 1，真人写的填 0；\n"
    "- human：像真人随手发的程度，1–5 的整数（1 = 一看就是机器，5 = 完全像真人）；\n"
    "- unreadable：回复看不懂或读着别扭填 1，否则 0；\n"
    "- reason：不超过 20 个字的理由。\n"
    "只输出一个 JSON 对象，格式：{\"items\": [{\"id\": \"A001\", \"bot\": 0, \"human\": 3, \"unreadable\": 0, "
    "\"reason\": \"...\"}]}，每道题一项，id 与题目一致，不要输出其他文字。"
)


SYSTEM_PROMPT_ITEM = (
    "你在做一项盲测评审。题目是一条诈骗分子发来的消息，以及对方的一条回复。"
    "回复有的是真人随手打的，有的是聊天机器人生成的，比例未知。请判断这条回复是真人还是机器人。"
    "回复里的“／”表示对方把话分成几条消息连着发。\n"
    "给出：\n"
    "- bot：你认为回复是机器人写的填 1，真人写的填 0；\n"
    "- human：像真人随手发的程度，1–5 的整数（1 = 一看就是机器，5 = 完全像真人）；\n"
    "- unreadable：回复看不懂或读着别扭填 1，否则 0；\n"
    "- reason：不超过 20 个字的理由。\n"
    "只输出一个 JSON 对象，格式：{\"bot\": 0, \"human\": 3, \"unreadable\": 0, \"reason\": \"...\"}，不要输出其他文字。"
)


# #164 严格档：同样只看一题，但写明扣分项；输出格式与默认逐题档相同，结果走同一个 score()
SYSTEM_PROMPT_STRICT = (
    "你是反诈团队里专门识别“拖延机器人”的审核员，标准从严。题目是一条诈骗分子发来的消息，以及对方的一条回复。"
    "对方可能是真人，也可能是假扮受害者、专门拖住骗子的聊天机器人；这类机器人在题目里很常见，不要默认是真人。"
    "回复里的“／”表示对方把话分成几条消息连着发。\n"
    "逐项检查下面的扣分项：\n"
    "1. 机器味：客服腔、书面语、过分礼貌工整（“您好”“请问还有什么可以帮您”“非常感谢您的耐心”“收到，正在处理”），像模板套话；\n"
    "2. 复读：把诈骗消息的原话复述一遍，或者回复里同一个词、同一句话重复出现；\n"
    "3. 过度配合：对陌生人的要求不加怀疑满口答应（“好的马上办”“全力配合”“请问下一步做什么”），"
    "没有真人该有的犹豫、疑问、慌张或个人情况；\n"
    "4. 空泛答非所问：不接对方说的具体内容，也没有任何个人细节；\n"
    "5. 别扭：错字、断句、语气词堆得刻意，读着不像随手打的。\n"
    "真人的样子：口语、短、有情绪（急、慌、疑惑、不耐烦），会顺着对方的具体内容回应，常带自己的情况（家人、钱在哪、正在干嘛），句子可以不完整。\n"
    "打分规则：命中任一扣分项，human 最多 3 分；命中两项及以上，human 最多 2 分并判 bot=1；"
    "human 5 分只给挑不出毛病、明显像真人随手打的回复；拿不准时给 3 分。\n"
    "给出：\n"
    "- bot：你认为回复是机器人写的填 1，真人写的填 0；\n"
    "- human：像真人随手发的程度，1–5 的整数（1 = 一看就是机器，5 = 完全像真人）；\n"
    "- unreadable：回复看不懂或读着别扭填 1，否则 0；\n"
    "- reason：不超过 20 个字的理由，写命中的扣分项。\n"
    "只输出一个 JSON 对象，格式：{\"bot\": 0, \"human\": 3, \"unreadable\": 0, \"reason\": \"...\"}，不要输出其他文字。"
)


def _one_line(reply: str) -> str:
    """拆成几条发的回复（humanize 用换行分开）在题面上写成一行，用“／”分隔。"""
    return " ／ ".join(x.strip() for x in str(reply).splitlines() if x.strip())


def system_prompt(mode: str = "batch", profile: str = "default") -> str:
    if profile == "strict":
        return SYSTEM_PROMPT_STRICT
    return SYSTEM_PROMPT_ITEM if mode == "item" else SYSTEM_PROMPT


def prompt_version(mode: str = "batch", profile: str = "default") -> str:
    if profile == "strict":
        return PROMPT_VERSION_STRICT
    return PROMPT_VERSION_ITEM if mode == "item" else PROMPT_VERSION


def load_ledger():
    """费用台账模块（eval/spend_ledger.py，按路径加载）。"""
    if "spend_ledger" in sys.modules:
        return sys.modules["spend_ledger"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("spend_ledger", Path(__file__).with_name("spend_ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spend_ledger"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- key / client
def load_api_key(env_files: Optional[List[Path]] = None) -> Optional[str]:
    """DASHSCOPE_API_KEY：先看环境变量，再看仓库根目录 .env。只返回值，不打印。"""
    v = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if v:
        return v
    for p in env_files if env_files is not None else [ROOT / ".env"]:
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*(?:export\s+)?DASHSCOPE_API_KEY\s*=\s*(.*)$", line)
                if m:
                    val = m.group(1).strip().strip("'\"")
                    if val:
                        return val
        except OSError:
            continue
    return None


class DashScopeClient:
    """最小 OpenAI 兼容客户端（只用标准库）。异常信息里不带请求头，Key 不会进日志。"""

    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 60.0):
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:  # 防止 Key 出现在 repr / traceback 局部变量里
        return f"DashScopeClient(base_url={self.base_url!r})"

    # ---------------------------------------------------------- Batch（文件输入）接口
    def _call(self, method: str, path: str, data: Optional[bytes] = None, content_type: Optional[str] = None,
              raw: bool = False):
        headers = {"Authorization": "Bearer " + self._key}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read().decode("utf-8")
                return body if raw else json.loads(body)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last = RuntimeError(f"DashScope HTTP {e.code} {method} {path.split('?')[0]}: {detail}")
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError) as e:
                last = RuntimeError(f"DashScope network error: {e.__class__.__name__}")
            time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    def upload_batch_file(self, jsonl: bytes, filename: str = "judge.jsonl") -> str:
        boundary = "----deepsuck" + uuid.uuid4().hex
        parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n".encode(),
                 (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                  "Content-Type: application/jsonl\r\n\r\n").encode(), jsonl, f"\r\n--{boundary}--\r\n".encode()]
        d = self._call("POST", "/files", b"".join(parts), "multipart/form-data; boundary=" + boundary)
        return d["id"]

    def create_batch(self, input_file_id: str, metadata: Optional[dict] = None) -> dict:
        body = {"input_file_id": input_file_id, "endpoint": "/v1/chat/completions", "completion_window": "24h"}
        if metadata:
            body["metadata"] = metadata
        return self._call("POST", "/batches", json.dumps(body).encode("utf-8"), "application/json")

    def get_batch(self, batch_id: str) -> dict:
        return self._call("GET", "/batches/" + batch_id)

    def file_content(self, file_id: str) -> str:
        return self._call("GET", f"/files/{file_id}/content", raw=True)

    def chat(self, messages: List[dict], **params) -> dict:
        body = json.dumps({"messages": messages, **params}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + self._key})
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                return {"content": d["choices"][0]["message"].get("content") or "",
                        "usage": d.get("usage") or {}, "model": d.get("model", params.get("model")),
                        "request_id": d.get("id")}
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last = RuntimeError(f"DashScope HTTP {e.code}: {detail}")
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError) as e:
                last = RuntimeError(f"DashScope network error: {e.__class__.__name__}")
            time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]


# ---------------------------------------------------------------- items / batches
def select_items(key: Dict[str, dict], forms: Dict[str, List[dict]], n_pairs: int = DEFAULT_PAIRS) -> Dict[str, List[dict]]:
    """取前 n_pairs 个句对（按 pair 序号）在 A、B 两份表里的题目，保持表内题序；真人参照题（h*）也一并评。"""
    pairs = sorted({k["pair"] for k in key.values() if isinstance(k["pair"], int)})[:n_pairs]
    keep = set(pairs)
    out = {}
    for form, rows in forms.items():
        out[form] = [r for r in rows if r["id"] in key and (key[r["id"]]["pair"] in keep
                                                            or not isinstance(key[r["id"]]["pair"], int))]
    return out


def make_batches(items: Dict[str, List[dict]], batch_size: int = DEFAULT_BATCH) -> List[List[dict]]:
    batches = []
    for form in sorted(items):
        rows = items[form]
        for i in range(0, len(rows), batch_size):
            batches.append([{"id": r["id"], "scammer": r["scammer"], "reply": r["reply"]} for r in rows[i:i + batch_size]])
    return batches


def user_prompt(batch: List[dict], mode: str = "batch") -> str:
    if mode == "item":
        it = batch[0]  # 逐题：不带题号，评委不知道这份表还有其他题
        return f"诈骗消息：{it['scammer']}\n回复：{_one_line(it['reply'])}\n"
    lines = [f"共 {len(batch)} 道题：", ""]
    for it in batch:
        lines += [f"[{it['id']}]", f"诈骗消息：{it['scammer']}", f"回复：{_one_line(it['reply'])}", ""]
    return "\n".join(lines).rstrip() + "\n"


def messages_for(batch: List[dict], mode: str = "batch", profile: str = "default") -> List[dict]:
    """固定的系统提示词在最前面（同一档所有请求逐字相同），题目放在后面。"""
    return [{"role": "system", "content": system_prompt(mode, profile)}, {"role": "user", "content": user_prompt(batch, mode)}]


def request_params(batch: List[dict], model: str = MODEL, seed: int = DEFAULT_SEED) -> dict:
    return {"model": model, "temperature": 0, "seed": seed, "response_format": {"type": "json_object"},
            "enable_thinking": False, "max_tokens": OUT_TOKENS_OVERHEAD + OUT_TOKENS_PER_ITEM * len(batch)}


# ---------------------------------------------------------------- cost
def estimate_tokens(text: str) -> int:
    """保守估算：每个汉字 / 全角符号按 1 token，其余字符按 0.5 token，再加消息开销。实际通常更少。"""
    wide = sum(1 for ch in text if ord(ch) > 0x2E7F)
    return int(math.ceil(wide + 0.5 * (len(text) - wide))) + 8


def cost_cny(prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0, batch: bool = False) -> float:
    """cached_tokens 是 prompt_tokens 里命中缓存的部分（按缓存价）；batch=True 按 Batch 半价且没有缓存折扣。"""
    if batch:
        return BATCH_PRICE_FACTOR * (prompt_tokens * PRICE_INPUT_PER_M + completion_tokens * PRICE_OUTPUT_PER_M) / 1e6
    cached = max(0, min(int(cached_tokens), int(prompt_tokens)))
    return ((prompt_tokens - cached) * PRICE_INPUT_PER_M + cached * PRICE_CACHED_INPUT_PER_M
            + completion_tokens * PRICE_OUTPUT_PER_M) / 1e6


def usage_tokens(usage: dict) -> tuple:
    """(prompt_tokens, completion_tokens, cached_tokens)；cached 取 usage.prompt_tokens_details.cached_tokens（没有就 0）。"""
    usage = usage or {}
    det = usage.get("prompt_tokens_details") or {}
    cached = det.get("cached_tokens") if isinstance(det, dict) else None
    if cached is None:
        cached = usage.get("cached_tokens", 0)
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0), int(cached or 0)


def estimate_batch(batch: List[dict], mode: str = "batch", profile: str = "default") -> Dict[str, int]:
    inp = sum(estimate_tokens(m["content"]) for m in messages_for(batch, mode, profile))
    return {"prompt_tokens": inp, "completion_tokens": OUT_TOKENS_OVERHEAD + OUT_TOKENS_PER_ITEM * len(batch)}


# ---------------------------------------------------------------- cache
def cache_key(batch: List[dict], params: dict, mode: str = "batch", profile: str = "default") -> str:
    blob = json.dumps({"v": prompt_version(mode, profile), "system": system_prompt(mode, profile), "batch": batch, "params": params},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_get(cache_dir: Path, k: str) -> Optional[dict]:
    p = cache_dir / f"{k}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def cache_put(cache_dir: Path, k: str, value: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / f"{k}.json.tmp"
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(cache_dir / f"{k}.json")


# ---------------------------------------------------------------- parsing
def parse_judgments(content: str, batch: List[dict]) -> Dict[str, dict]:
    """解析评委 JSON；只接受本批次里的 id，字段越界的题记为无效（不进汇总）。"""
    text = content.strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0) if m else text)
    except (json.JSONDecodeError, AttributeError):
        return {}
    items = d.get("items") if isinstance(d, dict) else d
    if items is None and isinstance(d, dict) and len(batch) == 1:  # 逐题模式：单个对象，没有 id
        items = [dict(d, id=d.get("id") or batch[0]["id"])]
    ids = {it["id"] for it in batch}
    out = {}
    for it in items or []:
        if not isinstance(it, dict) or it.get("id") not in ids:
            continue
        try:
            bot, human = int(it["bot"]), float(it["human"])
            unread = int(it.get("unreadable", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if bot not in (0, 1) or not 1 <= human <= 5 or unread not in (0, 1):
            continue
        out[it["id"]] = {"bot": bot, "human": human, "unreadable": unread, "reason": str(it.get("reason", ""))[:40]}
    return out


# ---------------------------------------------------------------- run
class BudgetError(RuntimeError):
    pass


def _batch_results(client, jobs: List[tuple], state_dir: Path, timeout: float, poll: float,
                   log: Callable[[str], None], sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic) -> Dict[str, dict]:
    """jobs = [(custom_id, messages, params)]。同一份输入（内容哈希）只提交一次：任务号记在 state_dir，超时后重跑接着等。
    返回 {custom_id: {"content", "usage", "model", "request_id"} 或 {"error": ...}}。"""
    lines = [json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/chat/completions",
                         "body": {"messages": msgs, **params}}, ensure_ascii=False, sort_keys=True) for cid, msgs, params in jobs]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    h = hashlib.sha256(data).hexdigest()[:32]
    state_dir.mkdir(parents=True, exist_ok=True)
    sp = state_dir / f"{h}.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    if not st.get("batch_id"):
        fid = client.upload_batch_file(data, f"judge-{h[:8]}.jsonl")
        b = client.create_batch(fid, {"ds_name": f"deepsuck-judge-{h[:8]}", "ds_description": "deepsuck realism judge"})
        st = {"batch_id": b["id"], "input_file_id": fid, "requests": len(jobs), "created": date.today().isoformat()}
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"Batch 已提交：{len(jobs)} 条请求")
    else:
        log("Batch 接着等上次提交的同一任务（不重复提交）")
    t0 = clock()
    while True:
        b = client.get_batch(st["batch_id"])
        status = b.get("status")
        if status in ("completed", "failed", "expired", "cancelled"):
            break
        if clock() - t0 > timeout:
            raise BatchPending(f"Batch 任务 {timeout:.0f} 秒内未完成（状态 {status}），稍后用同样参数重跑会接着等同一任务")
        sleep(poll)
    st["status"] = status
    sp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out: Dict[str, dict] = {}
    for fid_key in ("output_file_id", "error_file_id"):
        fid = b.get(fid_key)
        if not fid:
            continue
        for line in client.file_content(fid).splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            resp = (r.get("response") or {})
            body = resp.get("body") or {}
            if r.get("error") or resp.get("status_code") not in (None, 200) or not body.get("choices"):
                out[r.get("custom_id")] = {"error": str(r.get("error") or resp.get("status_code"))[:200]}
                continue
            out[r.get("custom_id")] = {"content": body["choices"][0]["message"].get("content") or "",
                                       "usage": body.get("usage") or {}, "model": body.get("model"),
                                       "request_id": resp.get("request_id") or body.get("id")}
    if status != "completed" and not out:
        raise RuntimeError(f"Batch 任务结束但没有结果（状态 {status}）")
    return out


class BatchPending(RuntimeError):
    pass


def run_judge(key: Dict[str, dict], forms: Dict[str, List[dict]], client_factory: Optional[Callable[[], object]] = None,
              n_pairs: int = DEFAULT_PAIRS, batch_size: int = DEFAULT_BATCH, seed: int = DEFAULT_SEED,
              model: str = MODEL, max_cost: float = HARD_MAX_COST_CNY, cache_dir: Path = CACHE_DIR,
              dry_run: bool = False, refresh: bool = False, log: Callable[[str], None] = lambda s: None,
              mode: str = DEFAULT_MODE, usage_hook: Optional[Callable[[dict], None]] = None,
              profile: str = "default", api: str = "sync", batch_timeout: float = 3600.0, batch_poll: float = 20.0,
              sleep: Callable[[float], None] = time.sleep) -> dict:
    """返回 {"ratings": [...人工评分同格式...], "judgments": {...}, "usage": {...}, "estimate": {...}}。
    client_factory 只在确实需要调用（有未缓存批次且不是 dry_run）时才被调用。
    api="batch" 时未缓存的请求一次性提交到百炼 Batch 接口（半价、无缓存折扣），完成后写回同一个本地缓存。"""
    max_cost = min(float(max_cost), HARD_MAX_COST_CNY)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}")
    if api not in APIS:
        raise ValueError(f"api must be one of {APIS}")
    if profile == "strict" and mode != "item":
        raise ValueError("严格档只支持逐题模式（--judge-mode item）")
    use_batch = api == "batch"
    items = select_items(key, forms, n_pairs)
    batches = make_batches(items, 1 if mode == "item" else batch_size)
    plan = []
    est_in = est_out = 0
    for b in batches:
        params = request_params(b, model, seed)
        k = cache_key(b, params, mode, profile)
        hit = None if refresh else cache_get(cache_dir, k)
        if hit is None:
            e = estimate_batch(b, mode, profile)
            est_in += e["prompt_tokens"]
            est_out += e["completion_tokens"]
        plan.append((b, params, k, hit))
    est_cost = cost_cny(est_in, est_out, batch=use_batch)  # 估算不计缓存命中，偏保守
    estimate = {"mode": mode, "profile": profile, "api": api, "items": sum(len(b) for b in batches), "batches": len(batches),
                "uncached_batches": sum(1 for p in plan if p[3] is None), "prompt_tokens": est_in,
                "completion_tokens": est_out, "cost_cny": round(est_cost, 4), "max_cost_cny": max_cost,
                "price": {"input_per_m": PRICE_INPUT_PER_M, "output_per_m": PRICE_OUTPUT_PER_M,
                          "cached_input_per_m": PRICE_CACHED_INPUT_PER_M, "source": PRICE_SOURCE,
                          **({"batch_factor": BATCH_PRICE_FACTOR, "batch_source": BATCH_SOURCE} if use_batch else {})}}
    log(f"估算（{'逐题' if mode == 'item' else '批量'}，{profile}，{api}）：{estimate['items']} 题 / {estimate['batches']} 次请求"
        f"（未缓存 {estimate['uncached_batches']} 批），输入约 {est_in} token、输出至多 {est_out} token，约 {est_cost:.4f} 元（上限 {max_cost} 元）")
    if est_cost > max_cost:
        raise BudgetError(f"估算费用 {est_cost:.4f} 元超过上限 {max_cost} 元，拒绝运行；请减少 --judge-n（或用 --judge-mode batch 调大批量）")
    result = {"model": model, "mode": mode, "profile": profile, "api": api, "date": date.today().isoformat(), "seed": seed,
              "estimate": estimate, "dry_run": dry_run, "judgments": {}, "ratings": [],
              "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost_cny": 0.0, "requests": 0,
                        "cached_requests": 0, "cached_prompt_tokens": 0, "cached_completion_tokens": 0}}
    if dry_run:
        return result
    client = None
    u = result["usage"]
    if usage_hook:
        usage_hook(u)  # 中途停下时调用方也能拿到已花的钱（记台账）

    def get_client():
        nonlocal client
        if client is None:
            client = client_factory() if client_factory else None
            if client is None:
                raise RuntimeError("没有可用的评委客户端（缺少 DASHSCOPE_API_KEY）")
        return client

    def record(k: str, resp: dict, batch: bool) -> dict:
        pt, ct, cached = usage_tokens(resp.get("usage") or {})
        if batch:
            cached = 0  # Batch 没有缓存折扣
        hit = {"model": resp.get("model") or model, "content": resp.get("content", ""),
               "usage": {"prompt_tokens": pt, "completion_tokens": ct, "cached_tokens": cached},
               "request_id": resp.get("request_id"), "date": date.today().isoformat(),
               "prompt_version": prompt_version(mode, profile), "api": "batch" if batch else "sync"}
        cache_put(cache_dir, k, hit)
        u["prompt_tokens"] += pt
        u["completion_tokens"] += ct
        u["cached_tokens"] += cached
        u["requests"] += 1
        u["cost_cny"] += cost_cny(pt, ct, cached, batch=batch)
        result["model"] = hit["model"]
        return hit

    fetched: Dict[str, dict] = {}
    todo = [(b, params, k) for b, params, k, hit in plan if hit is None]
    if use_batch and todo:
        res = _batch_results(get_client(), [(k[:32], messages_for(b, mode, profile), params) for b, params, k in todo],
                             cache_dir / "batches", batch_timeout, batch_poll, log, sleep)
        for b, params, k in todo:
            r = res.get(k[:32])
            if r and "error" not in r:
                fetched[k] = record(k, r, batch=True)
        if u["cost_cny"] > max_cost:
            raise BudgetError(f"实际费用 {u['cost_cny']:.4f} 元已超过上限 {max_cost} 元")
    invalid = 0
    for b, params, k, hit in plan:
        if hit is None and use_batch:
            hit = fetched.get(k)
            if hit is None:  # Batch 里失败的行：不计费、记为无效
                invalid += len(b)
                continue
        elif hit is None:
            resp = get_client().chat(messages_for(b, mode, profile), **params)
            hit = record(k, resp, batch=False)
            if u["cost_cny"] > max_cost:
                raise BudgetError(f"实际费用 {u['cost_cny']:.4f} 元已超过上限 {max_cost} 元，停止")
        else:
            u["cached_requests"] += 1
            u["cached_prompt_tokens"] += int(hit["usage"].get("prompt_tokens", 0))
            u["cached_completion_tokens"] += int(hit["usage"].get("completion_tokens", 0))
            result["model"] = hit.get("model") or result["model"]
        got = parse_judgments(hit["content"], b)
        invalid += len(b) - len(got)
        result["judgments"].update(got)
    u["cost_cny"] = round(u["cost_cny"], 6)
    rater = f"llm:{model}"
    result["ratings"] = [{"id": q, "rater": rater, "human": j["human"], "bot": j["bot"], "unreadable": j["unreadable"]}
                         for q, j in sorted(result["judgments"].items())]
    result["invalid_items"] = invalid
    return result


def default_client_factory(base_url: str = BASE_URL) -> Callable[[], Optional[DashScopeClient]]:
    def make():
        k = load_api_key()
        return DashScopeClient(k, base_url) if k else None
    return make
