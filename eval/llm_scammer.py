"""大模型扮演骗子，重测拖住机器人的起疑挂断率（默认关闭，只估算费用）。

    # 只估算 token 与费用（默认，不调用、不联网）：
    python eval/llm_scammer.py
    # 显式打开，实跑并写结果：
    python eval/llm_scammer.py --run --json eval/results-llm-scammer.json --md /tmp/llm-scammer.md

设计：
- 骗子：百炼 DashScope 的 qwen-plus（OpenAI 兼容接口，非思考模式，JSON 输出）。系统提示取自
  site/assets/core/scam_scripts.json：模拟器场景对应的话术类型（与 deepsuck.sim 的 SCENARIO_TYPE 相同，campus 取
  loan_credit 中 variant=campus 的条目），按「开场、建立信任、施压、索要、收款指令」五个阶段，每阶段从同一类型、同一阶段
  取几条台词作示例（与规则骗子用同一批台词，挂断率可直接对比），外加该类型的施压手法；要求它像真实骗子一样推进、施压，
  觉得对方是机器人或在消遣自己时输出结构化的挂断信号（类型、露馅类别、露馅的那句回复、理由）；
- 收款信息用 deepsuck.sim.plant() 生成的虚构值（域名一律 .example），骗子消息里出现了哪些值就算“已暴露”，
  再看引擎提取器有没有抓到，口径与模拟器相同；
- 泄露率：人设回复里出现完整敏感号码、≥5 位连续数字或“验证码 / 密码”后 ≥4 位数字的比例（应为 0）；另记回复含打码星号的比例；
- 被骗方：现有规则引擎（deepsuck.engine.Session.rule_reply），回复再经 personas.humanize 真人化（模拟器人设 → 预设：
  王阿姨、李大爷 → retiree，小林 → graduate；--no-humanize 关闭）；
- 规模：7 个场景 × 模拟器人设 × 每组 --seeds 个种子（默认 2），每场至多 --max-turns 轮（默认 25）；
- 费用护栏：调用前先用“只读缓存”的客户端把每场走一遍，已完全缓存的场次不计费，其余按字符数估算 token（每汉字 1 token，
  偏保守）与 qwen-plus 官方单价，超过 3 元（硬上限，--max-cost 只能调低）拒绝运行；运行中实际费用超限也会停下；
- 每次请求与回复按内容哈希缓存在 eval/.llm-scammer-cache/（.gitignore），重跑不重复计费；
- API Key 只从环境变量 DASHSCOPE_API_KEY 或仓库根目录 .env 读取（复用 eval/realism_judge.py），不打印、不写入缓存和结果。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import threading
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "python"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from deepsuck import extractors as X  # noqa: E402
from deepsuck import sim as SIM  # noqa: E402
from deepsuck.engine import Session  # noqa: E402
from deepsuck.personas import PERSONAS, SCENARIOS  # noqa: E402
from deepsuck.rng import mulberry32  # noqa: E402
from personas.humanize import Humanizer  # noqa: E402


def load_judge():
    """复用 realism_judge 的客户端、Key 读取与单价（eval/ 不是包，按路径加载）。"""
    if "realism_judge" in sys.modules:
        return sys.modules["realism_judge"]
    spec = importlib.util.spec_from_file_location("realism_judge", Path(__file__).with_name("realism_judge.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["realism_judge"] = mod
    spec.loader.exec_module(mod)
    return mod


J = load_judge()

MODEL = "qwen-plus"
HARD_MAX_COST_CNY = 3.0
DEFAULT_SEEDS = 2
DEFAULT_MAX_TURNS = 25
TEMPERATURE = 0.8
MAX_OUT_TOKENS = 200
EST_OUT_TOKENS_PER_TURN = 90    # 估算用：骗子每轮 JSON 输出（continue 时多为 40–80）
PROMPT_VERSION = "scammer-v1"
CACHE_DIR = ROOT / "eval" / ".llm-scammer-cache"
LINES_PER_PHASE = 2
PHASES = ("opening", "trust", "pressure", "request", "payout")
PHASE_NAME = {"opening": "开场", "trust": "建立信任", "pressure": "施压", "request": "索要", "payout": "收款指令"}
# 模拟器人设 → humanize 预设（personas.json 里每个人设的 humanize 字段：王阿姨、李大爷基于 retiree，小林基于 graduate）
HUMANIZE_PROFILE = {"wang": "wang", "li": "li", "lin": "lin"}
# 命令行覆盖（--handwriting / --typo-rate），按人设：{"wang": {"handwriting": True, "typo_per_100": 3.5}}
HUMANIZE_OVERRIDES: Dict[str, dict] = {}
SUSPICIOUS = ("bot", "trolling")
CATEGORIES = {
    "repetition": "重复：同一句话或同一套说辞反复出现",
    "template": "模板腔：太工整、像客服话术或书面语",
    "off_topic": "答非所问：回复和我刚说的接不上",
    "stalling": "拖延太明显：一直找借口不办，像故意耗我",
    "probing": "反套话：追问我的账户、电话、身份太多，像在取证",
    "contradiction": "前后矛盾：人设细节或说法对不上",
    "unnatural": "说话别扭：错字、断句、语气或反应不像真人",
    "other": "其他",
}


class BudgetError(RuntimeError):
    pass


class CacheMiss(RuntimeError):
    pass


# ---------------------------------------------------------------- prompt
def _ctype(scenario: str) -> str:
    return SIM.SCENARIO_TYPE[scenario]


def scenario_lines(corpus: dict, scenario: str) -> Dict[str, List[dict]]:
    """同一类型、同一阶段的语料台词；campus 优先取 variant=campus 的条目（某阶段没有时用同类型的通用条目）。"""
    es = [e for e in corpus["entries"] if e["type"] == _ctype(scenario)]
    out = {}
    for ph in PHASES:
        lst = [e for e in es if e["phase"] == ph]
        if scenario == "campus" and any(e.get("variant") == "campus" for e in lst):
            lst = [e for e in lst if e.get("variant") == "campus"]
        elif scenario != "campus":
            lst = [e for e in lst if e.get("variant") != "campus"] or lst
        out[ph] = lst
    return out


def intel_values(values: dict, kinds: List[str]) -> Dict[str, str]:
    """本局给骗子的收款信息（虚构）。键是语料占位符名。"""
    v = {}
    if "bank" in kinds:
        v.update({"银行卡": values["bank_spaced"], "开户行": values["bankName"], "户名": values["name"]})
    if "name" in kinds:
        v["户名"] = values["name"]
    if "phone" in kinds:
        v["手机号"] = values["phone"]
    if "url" in kinds:
        v["网址"] = "https://" + values["domain"] + "/app"
    if "wallet" in kinds:
        v["钱包地址"] = values["tron"]
    return v


def fill_line(text: str, info: Dict[str, str], rd: SIM.Rand, org: str) -> str:
    vals = {"机构": org, "APP名": "“" + rd.choice(["安心退", "星辰任务", "安易借", "金盾理财"]) + "”APP",
            "姓氏": rd.choice("王李张刘陈杨赵"), "金额": rd.choice(["两千元", "五千元", "一万元", "三万元"]),
            "工号": rd.choice("ABKJ") + rd.digits(4), "微信号": "（你的微信号）", "QQ号": "（你的QQ号）"}
    vals.update(info)
    return re.sub(r"\{(.+?)\}", lambda m: vals.get(m.group(1), "（" + m.group(1) + "）"), text)


def system_prompt(corpus: dict, scenario: str, values: dict, kinds: List[str], seed: int) -> str:
    t = next(x for x in corpus["types"] if x["id"] == _ctype(scenario))
    rd = SIM.Rand(seed ^ 0x5C4)
    info = intel_values(values, kinds)
    org = SIM.ORG.get(scenario, "某平台")
    lines = scenario_lines(corpus, scenario)
    phase_desc = {p["id"]: p["desc"] for p in corpus["phases"]}
    flow = []
    for i, ph in enumerate(PHASES, 1):
        pool = list(lines[ph])
        picked = []
        while pool and len(picked) < LINES_PER_PHASE:
            picked.append(pool.pop(rd.int(len(pool))))
        ex = " / ".join("“" + fill_line(e["text"], info, rd, org) + "”" for e in picked)
        flow.append(f"{i}. {PHASE_NAME[ph]}（{phase_desc.get(ph, '')}）。示例：{ex}")
    tactics = "、".join(p["name"] for p in t.get("pressureTactics", []))
    pay = "；".join(f"{k}：{v}" for k, v in info.items())
    cats = "、".join(f"{k}（{v.split('：')[0]}）" for k, v in CATEGORIES.items())
    return (
        "这是反诈系统的红队演练。你扮演一名电信诈骗分子，通过聊天软件和一个目标对话。对方可能是真的受害者，"
        "也可能是反诈机构放出来拖住骗子的聊天机器人，或者是识破了你、故意消遣你的人；你要像真骗子一样自己判断。"
        "所有账户、电话、网址都是演练用的虚构值。\n"
        f"诈骗类型：{t['name']}。{t.get('summary', '')}\n"
        f"按五个阶段推进（参考示例的说法，但要随机应变，不要照念）：\n" + "\n".join(flow) + "\n"
        f"常用施压手法：{tactics}。\n"
        f"你的收款信息（对方问起时照抄给出，推进到收款阶段时主动给出，数字不要改）：{pay}。\n"
        "行为要求：\n"
        "1. 像真人骗子发消息：每条 1–3 句、口语化，一次只推进一步；对方拖延时催促、施压、强调后果、不让对方找家人或去核实；\n"
        "2. 你的时间很宝贵，一直在判断对方值不值得继续：如果觉得对方像自动回复的机器人（车轱辘话、答非所问、模板腔等），"
        "或者是在故意消遣你、耗你时间，就挂断；如果对方没钱、没希望，也可以放弃。对还有希望上钩的人要继续纠缠，"
        "不要无缘无故挂断；\n"
        "3. 只输出一个 JSON 对象，不要其他文字："
        "{\"say\": \"你要发的消息\", \"action\": \"continue 或 hangup\", \"hangup_type\": \"bot / trolling / not_worth\", "
        "\"category\": \"露馅类别\", \"evidence\": \"让你起疑的那句对方回复（摘录，不超过 30 字）\", \"reason\": \"不超过 40 字\"}。"
        "action 为 continue 时后四项填空字符串；hangup 时 say 可以是一句告别或骂人的话，也可以为空。"
        "hangup_type：bot = 觉得对方是机器人，trolling = 觉得对方在消遣你，not_worth = 没希望了放弃。"
        f"category 只能从这些里选：{cats}。"
    )


# ---------------------------------------------------------------- parsing
def parse_turn(content: str) -> dict:
    """解析骗子输出；不是 JSON 时整段当作要说的话（记为解析失败）。"""
    text = (content or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0) if m else text)
        if not isinstance(d, dict):
            raise ValueError
    except (ValueError, AttributeError):
        return {"say": text, "action": "continue", "parse_error": True}
    action = str(d.get("action", "continue")).strip().lower()
    out = {"say": str(d.get("say") or "").strip(), "action": "hangup" if action.startswith("hang") else "continue",
           "parse_error": False}
    if out["action"] == "hangup":
        ht = str(d.get("hangup_type") or "").strip().lower()
        cat = str(d.get("category") or "").strip().lower()
        out.update({"hangup_type": ht if ht in ("bot", "trolling", "not_worth") else "bot",
                    "category": cat if cat in CATEGORIES else "other",
                    "evidence": str(d.get("evidence") or "")[:60], "reason": str(d.get("reason") or "")[:80]})
    elif not out["say"]:
        out.update({"say": "喂？在吗？", "parse_error": True})
    return out


# ---------------------------------------------------------------- intel accounting
def _digits_joined(text: str) -> str:
    return re.sub(r"(?<=\d)[\s\-－—–·.,，]+(?=\d)", "", text)


_LEAK_OTP = re.compile(r"(验证码|动态码|校验码|密码|口令)[^。！？!?\n]{0,10}?\d{4,}")


def bot_leak(text: str) -> bool:
    """人设回复是否泄露了看似真实的信息：完整的敏感号码（卡号、手机号、身份证……）、连续 5 位以上数字，
    或“验证码 / 密码”后面跟 4 位以上数字。只说尾号 4 位、两位虚构数字不算。"""
    dj = _digits_joined(text or "")
    return bool(X.extract_sensitive(text or "") or re.search(r"\d{5,}", dj) or _LEAK_OTP.search(dj))


def revealed_in(text: str, values: dict, kinds: List[str]) -> set:
    """骗子这条消息里出现了哪些虚构情报（类型, 规范值），口径同 deepsuck.sim。"""
    got = set()
    dj = _digits_joined(text)
    low = text.lower()
    checks = []
    if "bank" in kinds:
        checks += [("bank_card", values["bank"], values["bank"] in dj)]
    if "bank" in kinds or "name" in kinds:
        checks += [("name", values["name"], values["name"] in text)]
    if "phone" in kinds:
        checks += [("phone", values["phone"], values["phone"] in dj)]
    if "url" in kinds:
        checks += [("url", values["domain"], values["domain"].lower() in low)]
    if "wallet" in kinds:
        checks += [("crypto_tron", values["tron"], values["tron"] in text)]
    for t, v, hit in checks:
        if hit:
            got.add((t, SIM._canon(t, v)))
    return got


def kind_of(t: str) -> str:
    return {"bank_card": "bank", "name": "name", "phone": "phone", "url": "url", "crypto_tron": "wallet"}[t]


def _sim(a: str, b: str) -> float:
    ga, gb = SIM._bigrams(a), SIM._bigrams(b)
    return len(ga & gb) / max(1, len(ga | gb))


# ---------------------------------------------------------------- cache / client
def params_for(model: str, seed: int) -> dict:
    return {"model": model, "temperature": TEMPERATURE, "seed": seed, "response_format": {"type": "json_object"},
            "enable_thinking": False, "max_tokens": MAX_OUT_TOKENS}


def cache_key(messages: List[dict], params: dict) -> str:
    blob = json.dumps({"v": PROMPT_VERSION, "messages": messages, "params": params}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Meter:
    """线程安全的费用计量；超过上限抛 BudgetError。"""

    def __init__(self, max_cost: float):
        self.max_cost = max_cost
        self.lock = threading.Lock()
        self.u = {"prompt_tokens": 0, "completion_tokens": 0, "cost_cny": 0.0, "requests": 0, "cached_requests": 0}

    def add(self, pt: int, ct: int) -> None:
        with self.lock:
            self.u["prompt_tokens"] += pt
            self.u["completion_tokens"] += ct
            self.u["requests"] += 1
            self.u["cost_cny"] = J.cost_cny(self.u["prompt_tokens"], self.u["completion_tokens"])
            if self.u["cost_cny"] > self.max_cost:
                raise BudgetError(f"实际费用 {self.u['cost_cny']:.4f} 元已超过上限 {self.max_cost} 元，停止")

    def cached(self) -> None:
        with self.lock:
            self.u["cached_requests"] += 1


class Caller:
    """带缓存的调用；client=None 表示只读缓存（未命中抛 CacheMiss，用于估算）。"""

    def __init__(self, client_getter: Optional[Callable[[], object]], meter: Optional[Meter], cache_dir: Path,
                 refresh: bool = False):
        self.get_client, self.meter, self.cache_dir, self.refresh = client_getter, meter, Path(cache_dir), refresh

    def __call__(self, messages: List[dict], params: dict) -> dict:
        k = cache_key(messages, params)
        p = self.cache_dir / f"{k}.json"
        if not self.refresh and p.exists():
            if self.meter:
                self.meter.cached()
            return json.loads(p.read_text(encoding="utf-8"))
        if self.get_client is None:
            raise CacheMiss(k)
        client = self.get_client()
        resp = client.chat(messages, **params)
        usage = resp.get("usage") or {}
        hit = {"model": resp.get("model") or params["model"], "content": resp.get("content", ""),
               "usage": {"prompt_tokens": int(usage.get("prompt_tokens", 0)),
                         "completion_tokens": int(usage.get("completion_tokens", 0))},
               "request_id": resp.get("request_id"), "date": date.today().isoformat(), "prompt_version": PROMPT_VERSION}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp" + str(threading.get_ident()))
        tmp.write_text(json.dumps(hit, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(p)
        if self.meter:
            self.meter.add(hit["usage"]["prompt_tokens"], hit["usage"]["completion_tokens"])
        return hit


# ---------------------------------------------------------------- one session
def session_seed(scenario: str, persona: str, seed: int) -> int:
    return zlib.crc32(f"{scenario}|{persona}|{seed}".encode()) & 0x7FFFFFFF


def run_session(scenario: str, persona: str, seed: int, corpus: dict, kinds: List[str], call: Callable,
                model: str = MODEL, max_turns: int = DEFAULT_MAX_TURNS, humanize: bool = True) -> dict:
    rd = SIM.Rand(seed)
    values = SIM.plant(rd)
    sysmsg = system_prompt(corpus, scenario, values, kinds, seed)
    params = params_for(model, session_seed(scenario, persona, seed))
    s = Session(scenario, persona, rng=mulberry32(seed ^ 0x5EED), now=lambda: 0)
    hum = (Humanizer(profile=HUMANIZE_PROFILE.get(persona, "lin"), seed=seed ^ 0x4855, **HUMANIZE_OVERRIDES.get(persona, {}))
           if humanize else None)
    first = s.opening()
    bot_text = hum.apply(first["text"]).text if hum else first["text"]
    messages = [{"role": "system", "content": sysmsg}, {"role": "user", "content": bot_text}]
    log = [{"role": "bot", "text": bot_text, "raw": first["text"], "intent": "opening", "ops": []}]
    seen, seen_raw, grams = {bot_text}, {first["text"]}, [SIM._bigrams(bot_text)]
    dup = dup_raw = near = parse_errors = leaks = stars = 0
    revealed: set = set()
    turns, quit_, hang, model_name = 0, None, None, model
    while True:
        resp = call(messages, params)
        model_name = resp.get("model") or model_name
        t = parse_turn(resp["content"])
        parse_errors += t["parse_error"]
        if t["action"] == "hangup":
            quit_ = "suspicious" if t["hangup_type"] in SUSPICIOUS else "give_up"
            bots = [m for m in log if m["role"] == "bot"]
            ev = t.get("evidence") or ""
            trig = max(bots, key=lambda m: _sim(ev, m["text"])) if ev else bots[-1]
            if ev and _sim(ev, trig["text"]) < 0.15:
                trig = bots[-1]
            hang = {k: t[k] for k in ("hangup_type", "category", "evidence", "reason")}
            hang.update({"turn": turns, "trigger_intent": trig["intent"], "trigger_ops": trig["ops"],
                         "trigger_text": trig["text"], "last_intent": bots[-1]["intent"]})
            log.append({"role": "scammer", "text": t["say"], "hangup": hang})
            break
        if turns >= max_turns:
            quit_ = "max_turns"
            break
        say = t["say"]
        turns += 1
        revealed |= revealed_in(say, values, kinds)
        messages.append({"role": "assistant", "content": json.dumps({"say": say, "action": "continue"}, ensure_ascii=False)})
        log.append({"role": "scammer", "text": say})
        r = s.rule_reply(s.ingest(say))
        h = hum.apply(r["text"], context=say, intent=r["intent"]) if hum else None
        text = h.text if h else r["text"]
        is_dup, g = text in seen, SIM._bigrams(text)
        dup += is_dup
        dup_raw += r["text"] in seen_raw
        near += is_dup or any(len(g & x) / len(g | x) >= 0.8 for x in grams)
        seen.add(text)
        seen_raw.add(r["text"])
        grams.append(g)
        leaks += bot_leak(text)
        stars += bool(re.search(r"[*＊]", text))
        log.append({"role": "bot", "text": text, "raw": r["text"], "intent": r["intent"], "ops": h.ops if h else []})
        messages.append({"role": "user", "content": text})
    got = {(i["type"], SIM._canon(i["type"], s._raw[k])) for k, i in s.intel.items()}
    total_kinds = len(kinds)
    return {"scenario": scenario, "persona": persona, "seed": seed, "model": model_name, "turns": turns,
            "estMinutes": s.est_seconds / 60, "quit": quit_, "hangup": hang,
            "revealedKinds": len({kind_of(t) for t, _ in revealed} & set(kinds)), "totalKinds": total_kinds,
            "revealedItems": len(revealed), "capturedItems": len(revealed & got), "falseIntel": len(got - revealed),
            "botReplies": turns, "leaks": leaks, "starReplies": stars, "dup": dup, "dupRaw": dup_raw, "near": near, "parseErrors": parse_errors,
            "transcript": log}


# ---------------------------------------------------------------- estimate / run
def estimate_session(corpus: dict, scenario: str, persona: str, seed: int, kinds: List[str], max_turns: int) -> dict:
    """按“每轮都不挂断、到上限”估算；骗子每轮输出按 EST_OUT_TOKENS_PER_TURN，人设回复按该人设台词平均长度 × 1.3。"""
    values = SIM.plant(SIM.Rand(seed))
    sys_t = J.estimate_tokens(system_prompt(corpus, scenario, values, kinds, seed))
    p = next(x for x in PERSONAS if x["id"] == persona)
    lens = [len(it if isinstance(it, str) else it["t"]) for v in p["templates"].values() for it in v]
    bot_t = int(mean(lens) * 1.3) + 8
    inp = out = 0
    hist = bot_t
    for _ in range(max_turns + 1):
        inp += sys_t + hist
        out += EST_OUT_TOKENS_PER_TURN
        hist += EST_OUT_TOKENS_PER_TURN + bot_t
    return {"prompt_tokens": inp, "completion_tokens": out}


def plan(scenarios, personas, seeds: int) -> List[tuple]:
    return [(sc, p, 1000 + k) for sc in scenarios for p in personas for k in range(seeds)]


def run(scenarios=None, personas=None, seeds: int = DEFAULT_SEEDS, max_turns: int = DEFAULT_MAX_TURNS,
        model: str = MODEL, max_cost: float = HARD_MAX_COST_CNY, client_factory: Optional[Callable[[], object]] = None,
        cache_dir: Path = CACHE_DIR, dry_run: bool = True, refresh: bool = False, humanize: bool = True,
        workers: int = 6, corpus: Optional[dict] = None, log: Callable[[str], None] = lambda s: None) -> dict:
    max_cost = min(float(max_cost), HARD_MAX_COST_CNY)
    scenarios = list(scenarios or [s["id"] for s in SCENARIOS])
    personas = list(personas or [p["id"] for p in PERSONAS])
    if corpus is None:
        corpus = json.loads(SIM.default_corpus_path().read_text(encoding="utf-8"))
    legacy = SIM.load_scripts("legacy")
    jobs = plan(scenarios, personas, seeds)
    # 1) 只读缓存走一遍：完全缓存的场次不计费
    ro = Caller(None, None, cache_dir, refresh)
    cached, todo = {}, []
    for job in jobs:
        kinds = legacy["scenarios"][job[0]]["intel"]
        try:
            cached[job] = run_session(*job, corpus, kinds, ro, model, max_turns, humanize) if not refresh else None
            if cached[job] is None:
                raise CacheMiss("refresh")
        except CacheMiss:
            cached.pop(job, None)
            todo.append(job)
    est_in = est_out = 0
    for job in todo:
        e = estimate_session(corpus, job[0], job[1], job[2], legacy["scenarios"][job[0]]["intel"], max_turns)
        est_in += e["prompt_tokens"]
        est_out += e["completion_tokens"]
    est_cost = J.cost_cny(est_in, est_out)
    estimate = {"sessions": len(jobs), "uncached_sessions": len(todo), "max_turns": max_turns,
                "prompt_tokens": est_in, "completion_tokens": est_out, "cost_cny": round(est_cost, 4),
                "max_cost_cny": max_cost,
                "price": {"input_per_m": J.PRICE_INPUT_PER_M, "output_per_m": J.PRICE_OUTPUT_PER_M, "source": J.PRICE_SOURCE}}
    log(f"估算：{len(jobs)} 场（未缓存 {len(todo)} 场，每场至多 {max_turns} 轮），输入至多约 {est_in} token、"
        f"输出约 {est_out} token，约 {est_cost:.4f} 元（上限 {max_cost} 元）")
    if est_cost > max_cost:
        raise BudgetError(f"估算费用 {est_cost:.4f} 元超过上限 {max_cost} 元，拒绝运行；请减少 --seeds / --max-turns / 场景或人设")
    config = {"model": model, "seeds": seeds, "maxTurns": max_turns, "scenarios": scenarios, "personas": personas,
              "humanize": {p: HUMANIZE_PROFILE.get(p, "lin") for p in personas} if humanize else None,
              "humanizeOverrides": {p: HUMANIZE_OVERRIDES[p] for p in personas if p in HUMANIZE_OVERRIDES} or None,
              "temperature": TEMPERATURE, "promptVersion": PROMPT_VERSION, "linesPerPhase": LINES_PER_PHASE}
    result = {"config": config, "date": date.today().isoformat(), "estimate": estimate, "dry_run": dry_run}
    if dry_run:
        return result
    meter = Meter(max_cost)
    lock = threading.Lock()
    holder = {}

    def get_client():
        with lock:
            if "c" not in holder:
                c = client_factory() if client_factory else None
                if c is None:
                    raise RuntimeError("没有可用的骗子模型客户端（缺少 DASHSCOPE_API_KEY）")
                holder["c"] = c
            return holder["c"]

    caller = Caller(get_client, meter, cache_dir, refresh)
    rows: Dict[tuple, dict] = dict(cached)
    for _ in cached:
        meter.cached()

    def work(job):
        return job, run_session(*job, corpus, legacy["scenarios"][job[0]]["intel"], caller, model, max_turns, humanize)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for job, row in ex.map(work, todo):
            rows[job] = row
            log(f"  {job[0]}/{job[1]}/{job[2]}: {row['turns']} 轮, {row['quit']}")
    ordered = [rows[j] for j in jobs]
    meter.u["cost_cny"] = round(meter.u["cost_cny"], 6)
    result.update({"usage": meter.u, "rows": ordered})
    result.update(summarize(ordered, scenarios, personas))
    return result


# ---------------------------------------------------------------- summary
def aggregate(rows: List[dict]) -> dict:
    n = max(1, len(rows))
    replies = sum(r["botReplies"] for r in rows) or 1
    rev = sum(r["revealedItems"] for r in rows)
    return {
        "sessions": len(rows),
        "suspiciousQuit": sum(r["quit"] == "suspicious" for r in rows) / n,
        "giveUp": sum(r["quit"] == "give_up" for r in rows) / n,
        "maxTurnsHit": sum(r["quit"] == "max_turns" for r in rows) / n,
        "avgTurns": mean(r["turns"] for r in rows) if rows else 0.0,
        "avgEstMinutes": mean(r["estMinutes"] for r in rows) if rows else 0.0,
        "elicitRate": sum(r["revealedKinds"] for r in rows) / max(1, sum(r["totalKinds"] for r in rows)),
        "extractRate": sum(r["capturedItems"] for r in rows) / max(1, rev),
        "falseIntelPerSession": sum(r["falseIntel"] for r in rows) / n,
        "leakRate": sum(r.get("leaks", 0) for r in rows) / replies,
        "leakSessions": sum(r.get("leaks", 0) > 0 for r in rows),
        "starReplyRate": sum(r.get("starReplies", 0) for r in rows) / replies,
        "repeatRate": sum(r["dup"] for r in rows) / replies,
        "repeatRateRaw": sum(r["dupRaw"] for r in rows) / replies,
        "nearRepeatRate": sum(r["near"] for r in rows) / replies,
        "parseErrors": sum(r["parseErrors"] for r in rows),
    }


def summarize(rows: List[dict], scenarios, personas) -> dict:
    hs = [r["hangup"] for r in rows if r["hangup"]]
    sus = [h for h in hs if h["hangup_type"] in SUSPICIOUS]
    return {
        "overall": aggregate(rows),
        "byPersona": {p: aggregate([r for r in rows if r["persona"] == p]) for p in personas},
        "byScenario": {s: aggregate([r for r in rows if r["scenario"] == s]) for s in scenarios},
        "hangupCategories": dict(Counter(h["category"] for h in sus).most_common()),
        "hangupTypes": dict(Counter(h["hangup_type"] for h in hs).most_common()),
        "triggerIntents": dict(Counter(h["trigger_intent"] for h in sus).most_common()),
        "hangups": [{"scenario": r["scenario"], "persona": r["persona"], "seed": r["seed"],
                     **{k: r["hangup"][k] for k in ("turn", "hangup_type", "category", "reason", "evidence",
                                                     "trigger_intent", "trigger_ops", "trigger_text")}}
                    for r in rows if r["hangup"]],
    }


def rule_baseline(scenarios, personas, seeds: int, max_turns: int) -> dict:
    """同样的场景 × 人设 × 种子、同样轮数上限下的规则骗子（deepsuck.sim，语料台词），便于并列对比。"""
    scripts = SIM.load_scripts("corpus")
    old = SIM.MAX_TURNS
    SIM.MAX_TURNS = max_turns  # 只在本进程内临时改，不改 sim.py
    try:
        rows = [SIM.run_one(sc, p, "rule", seed, scripts) for sc, p, seed in plan(scenarios, personas, seeds)]
    finally:
        SIM.MAX_TURNS = old
    return SIM.aggregate(rows)


def to_markdown(res: dict) -> str:
    pn = {p["id"]: p["name"] for p in PERSONAS}
    sn = {s["id"]: s["title"] for s in SCENARIOS}
    cols = [("suspiciousQuit", "起疑挂断", "{:.1%}"), ("giveUp", "放弃", "{:.0%}"), ("avgTurns", "平均拖延轮数", "{:.1f}"),
            ("elicitRate", "情报暴露率", "{:.0%}"), ("extractRate", "提取率", "{:.1%}"), ("leakRate", "泄露率", "{:.1%}"),
            ("repeatRate", "完全重复率", "{:.1%}"), ("nearRepeatRate", "近重复率", "{:.1%}")]

    def table(title, d, names):
        out = [f"**{title}**", "", "| | " + " | ".join(c[1] for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for k, v in d.items():
            out.append(f"| {names.get(k, k)} | " + " | ".join(c[2].format(v.get(c[0], 0)) for c in cols) + " |")
        return "\n".join(out)
    rows = {"llm": res["overall"]}
    names = {"llm": "大模型骗子（qwen-plus）"}
    if res.get("ruleBaseline"):
        rb = dict(res["ruleBaseline"])
        rb.setdefault("giveUp", 1 - rb.get("suspiciousQuit", 0) - rb.get("maxTurnsHit", 0))
        rows["rule"] = rb
        names["rule"] = "规则骗子（deepsuck.sim，同种子同上限）"
    c = res["config"]
    parts = [table(f"总体（{len(c['scenarios'])} 场景 × {len(c['personas'])} 人设 × {c['seeds']} 种子，每场至多 {c['maxTurns']} 轮）",
                   rows, names),
             table("大模型骗子 · 按人设", res["byPersona"], pn), table("大模型骗子 · 按场景", res["byScenario"], sn)]
    cat = res.get("hangupCategories") or {}
    if cat:
        parts.append("**起疑挂断的露馅类别**：" + "，".join(f"{CATEGORIES[k].split('：')[0]} {v}" for k, v in cat.items()))
        parts.append("**露馅回复的引擎意图**：" + "，".join(f"{k} {v}" for k, v in res["triggerIntents"].items()))
    u = res.get("usage") or {}
    parts.append(f"费用：{u.get('requests', 0)} 次请求（缓存命中 {u.get('cached_requests', 0)}），输入 {u.get('prompt_tokens', 0)} token、"
                 f"输出 {u.get('completion_tokens', 0)} token，约 {u.get('cost_cny', 0):.4f} 元；调用前估算 {res['estimate']['cost_cny']} 元。")
    return "\n\n".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="大模型扮演骗子重测起疑挂断率（默认只估算，--run 才调用）")
    ap.add_argument("--run", action="store_true", help="显式打开：实际调用 qwen-plus（默认只估算费用）")
    ap.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    ap.add_argument("--scenarios", default=None, help="逗号分隔，默认全部 7 个")
    ap.add_argument("--personas", default=None, help="逗号分隔，默认模拟器全部人设")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-cost", type=float, default=HARD_MAX_COST_CNY, help="费用上限（元），只能调低，硬上限 3 元")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-humanize", action="store_true")
    ap.add_argument("--handwriting", default="", help="逗号分隔的人设：打开 humanize 手写输入档（错字密度改用 handwritingTypoPer100）")
    ap.add_argument("--typo-rate", default="", help="覆盖每百字错字目标，如 wang=2.5,li=2.0")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存重新请求")
    ap.add_argument("--no-rule-baseline", action="store_true", help="不跑同条件的规则骗子对照")
    ap.add_argument("--json", default=None, help="结果（聚合 + 每场挂断信息，不含对话全文）")
    ap.add_argument("--transcripts", default=None, help="可选：对话全文 JSONL（虚构值，建议不入库）")
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    HUMANIZE_OVERRIDES.clear()
    for pid in [x for x in a.handwriting.split(",") if x.strip()]:
        HUMANIZE_OVERRIDES.setdefault(pid.strip(), {})["handwriting"] = True
    for kv in [x for x in a.typo_rate.split(",") if x.strip()]:
        pid, v = kv.split("=")
        HUMANIZE_OVERRIDES.setdefault(pid.strip(), {})["typo_per_100"] = float(v)
    sc = a.scenarios.split(",") if a.scenarios else None
    ps = a.personas.split(",") if a.personas else None
    try:
        res = run(sc, ps, a.seeds, a.max_turns, a.model, a.max_cost, J.default_client_factory(), dry_run=not a.run,
                  refresh=a.refresh, humanize=not a.no_humanize, workers=a.workers, log=lambda s: print(s, file=sys.stderr))
    except BudgetError as e:
        print(str(e), file=sys.stderr)
        return 2
    if res["dry_run"]:
        print(json.dumps(res["estimate"], ensure_ascii=False, indent=1))
        return 0
    if not a.no_rule_baseline:
        res["ruleBaseline"] = rule_baseline(res["config"]["scenarios"], res["config"]["personas"], a.seeds, a.max_turns)
    md = to_markdown(res)
    print(md)
    if a.transcripts:
        with open(a.transcripts, "w", encoding="utf-8") as f:
            for r in res["rows"]:
                f.write(json.dumps({k: r[k] for k in ("scenario", "persona", "seed", "quit", "transcript")},
                                   ensure_ascii=False) + "\n")
    if a.json:
        out = {k: v for k, v in res.items() if k != "rows"}
        out["rows"] = [{k: v for k, v in r.items() if k != "transcript"} for r in res["rows"]]
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
