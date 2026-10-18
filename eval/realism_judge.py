"""“像不像真人”盲测的大模型评委（代理指标，默认关闭）。

    # 先 make 出 form-A.csv / form-B.csv / key.json，再显式打开大模型评委：
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --json eval/realism/judge-llm.json
    # 只估算 token 和费用，不调用：
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --dry-run

设计：
- 评委是百炼 DashScope 的 qwen-plus（OpenAI 兼容接口，非思考模式），temperature 0、固定 seed，要求 JSON 输出；
- 评委看到的内容和评测者一样：骗子消息 + 回复，不知道条件；默认逐题独立判（--judge-mode item：一题一次请求，
  评委看不到同一份表的其他题，避免“与某题雷同”式的跨题比较）；可选批量模式（--judge-mode batch：每次请求放同一份表的
  若干题，默认 10 题，即 76cef8b 的旧做法）。两种模式下同一句的 raw / humanized 都不会出现在同一次请求里，请求之间没有上下文；
- 默认评前 60 个句对（A、B 两份表各 60 题，共 120 次判断）；调用前按字符数保守估算 token 与费用，
  超过 1 元（硬上限，--max-cost 只能调低）直接拒绝运行；运行中实际费用超过上限也会停下；
- 每次请求与回复按内容哈希缓存在 eval/.judge-cache/（.gitignore），重跑不重复计费；
- 判断结果转成与人工评分相同的行格式（id / rater / human / bot / unreadable），交给 realism_blind.score() 汇总；
- API Key 只从环境变量 DASHSCOPE_API_KEY 或仓库根目录 .env 读取，不打印、不写进缓存或结果。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

MODEL = "qwen-plus"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# qwen-plus 单价（元 / 百万 token，华北 2 北京地域，单次请求输入 ≤128K 档，非思考模式），
# 来源：阿里云百炼「模型调用价格」https://help.aliyun.com/zh/model-studio/model-pricing（2026-10-18 查阅）。
# 本脚本每次请求只有几千 token，始终落在 ≤128K 档；不计免费额度和缓存折扣，按原价算，偏保守。
PRICE_INPUT_PER_M = 0.8
PRICE_OUTPUT_PER_M = 2.0
PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/model-pricing (qwen-plus, 北京, ≤128K, 非思考, 2026-10-18)"
HARD_MAX_COST_CNY = 1.0
DEFAULT_PAIRS = 60
DEFAULT_BATCH = 10
DEFAULT_SEED = 1
PROMPT_VERSION = "judge-v1"          # 批量模式（提示词与 76cef8b 相同，旧缓存仍可命中）
PROMPT_VERSION_ITEM = "judge-v2-item"
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
    "回复有的是真人随手打的，有的是聊天机器人生成的，比例未知。请判断这条回复是真人还是机器人。\n"
    "给出：\n"
    "- bot：你认为回复是机器人写的填 1，真人写的填 0；\n"
    "- human：像真人随手发的程度，1–5 的整数（1 = 一看就是机器，5 = 完全像真人）；\n"
    "- unreadable：回复看不懂或读着别扭填 1，否则 0；\n"
    "- reason：不超过 20 个字的理由。\n"
    "只输出一个 JSON 对象，格式：{\"bot\": 0, \"human\": 3, \"unreadable\": 0, \"reason\": \"...\"}，不要输出其他文字。"
)


def system_prompt(mode: str = "batch") -> str:
    return SYSTEM_PROMPT_ITEM if mode == "item" else SYSTEM_PROMPT


def prompt_version(mode: str = "batch") -> str:
    return PROMPT_VERSION_ITEM if mode == "item" else PROMPT_VERSION


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
        return f"诈骗消息：{it['scammer']}\n回复：{it['reply']}\n"
    lines = [f"共 {len(batch)} 道题：", ""]
    for it in batch:
        lines += [f"[{it['id']}]", f"诈骗消息：{it['scammer']}", f"回复：{it['reply']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def messages_for(batch: List[dict], mode: str = "batch") -> List[dict]:
    return [{"role": "system", "content": system_prompt(mode)}, {"role": "user", "content": user_prompt(batch, mode)}]


def request_params(batch: List[dict], model: str = MODEL, seed: int = DEFAULT_SEED) -> dict:
    return {"model": model, "temperature": 0, "seed": seed, "response_format": {"type": "json_object"},
            "enable_thinking": False, "max_tokens": OUT_TOKENS_OVERHEAD + OUT_TOKENS_PER_ITEM * len(batch)}


# ---------------------------------------------------------------- cost
def estimate_tokens(text: str) -> int:
    """保守估算：每个汉字 / 全角符号按 1 token，其余字符按 0.5 token，再加消息开销。实际通常更少。"""
    wide = sum(1 for ch in text if ord(ch) > 0x2E7F)
    return int(math.ceil(wide + 0.5 * (len(text) - wide))) + 8


def cost_cny(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens * PRICE_INPUT_PER_M / 1e6 + completion_tokens * PRICE_OUTPUT_PER_M / 1e6


def estimate_batch(batch: List[dict], mode: str = "batch") -> Dict[str, int]:
    inp = sum(estimate_tokens(m["content"]) for m in messages_for(batch, mode))
    return {"prompt_tokens": inp, "completion_tokens": OUT_TOKENS_OVERHEAD + OUT_TOKENS_PER_ITEM * len(batch)}


# ---------------------------------------------------------------- cache
def cache_key(batch: List[dict], params: dict, mode: str = "batch") -> str:
    blob = json.dumps({"v": prompt_version(mode), "system": system_prompt(mode), "batch": batch, "params": params},
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


def run_judge(key: Dict[str, dict], forms: Dict[str, List[dict]], client_factory: Optional[Callable[[], object]] = None,
              n_pairs: int = DEFAULT_PAIRS, batch_size: int = DEFAULT_BATCH, seed: int = DEFAULT_SEED,
              model: str = MODEL, max_cost: float = HARD_MAX_COST_CNY, cache_dir: Path = CACHE_DIR,
              dry_run: bool = False, refresh: bool = False, log: Callable[[str], None] = lambda s: None,
              mode: str = DEFAULT_MODE) -> dict:
    """返回 {"ratings": [...人工评分同格式...], "judgments": {...}, "usage": {...}, "estimate": {...}}。
    client_factory 只在确实需要调用（有未缓存批次且不是 dry_run）时才被调用。"""
    max_cost = min(float(max_cost), HARD_MAX_COST_CNY)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    items = select_items(key, forms, n_pairs)
    batches = make_batches(items, 1 if mode == "item" else batch_size)
    plan = []
    est_in = est_out = 0
    for b in batches:
        params = request_params(b, model, seed)
        k = cache_key(b, params, mode)
        hit = None if refresh else cache_get(cache_dir, k)
        if hit is None:
            e = estimate_batch(b, mode)
            est_in += e["prompt_tokens"]
            est_out += e["completion_tokens"]
        plan.append((b, params, k, hit))
    est_cost = cost_cny(est_in, est_out)
    estimate = {"mode": mode, "items": sum(len(b) for b in batches), "batches": len(batches),
                "uncached_batches": sum(1 for p in plan if p[3] is None), "prompt_tokens": est_in,
                "completion_tokens": est_out, "cost_cny": round(est_cost, 4), "max_cost_cny": max_cost,
                "price": {"input_per_m": PRICE_INPUT_PER_M, "output_per_m": PRICE_OUTPUT_PER_M, "source": PRICE_SOURCE}}
    log(f"估算（{'逐题' if mode == 'item' else '批量'}）：{estimate['items']} 题 / {estimate['batches']} 次请求（未缓存 {estimate['uncached_batches']} 批），"
        f"输入约 {est_in} token、输出至多 {est_out} token，约 {est_cost:.4f} 元（上限 {max_cost} 元）")
    if est_cost > max_cost:
        raise BudgetError(f"估算费用 {est_cost:.4f} 元超过上限 {max_cost} 元，拒绝运行；请减少 --judge-n（或用 --judge-mode batch 调大批量）")
    result = {"model": model, "mode": mode, "date": date.today().isoformat(), "seed": seed, "estimate": estimate,
              "dry_run": dry_run, "judgments": {}, "ratings": [],
              "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost_cny": 0.0, "requests": 0, "cached_requests": 0,
                        "cached_prompt_tokens": 0, "cached_completion_tokens": 0}}
    if dry_run:
        return result
    client = None
    u = result["usage"]
    invalid = 0
    for b, params, k, hit in plan:
        if hit is None:
            if client is None:
                client = client_factory() if client_factory else None
                if client is None:
                    raise RuntimeError("没有可用的评委客户端（缺少 DASHSCOPE_API_KEY）")
            resp = client.chat(messages_for(b, mode), **params)
            usage = resp.get("usage") or {}
            pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            hit = {"model": resp.get("model") or model, "content": resp.get("content", ""),
                   "usage": {"prompt_tokens": pt, "completion_tokens": ct}, "request_id": resp.get("request_id"),
                   "date": date.today().isoformat(), "prompt_version": prompt_version(mode)}
            cache_put(cache_dir, k, hit)
            u["prompt_tokens"] += pt
            u["completion_tokens"] += ct
            u["requests"] += 1
            u["cost_cny"] = cost_cny(u["prompt_tokens"], u["completion_tokens"])
            result["model"] = hit["model"]
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
