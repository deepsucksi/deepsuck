"""#164 区分度校准：同一批骗子台词，换四组回复，看骗子档和评委档能不能把差的和好的分开（默认只估算费用）。

    # 好组来源：voice.llm_ab 的输出（旧 qwen3.7-flash 语音人设的回复，不入库），例如
    python -m voice.llm_ab --models qwen3.7-flash --out ab.json
    # 只估算：
    python eval/discrimination_calib.py --good-file ab.json
    # 实跑（逐笔记台账）：
    python eval/discrimination_calib.py --good-file ab.json --run --budget-tag <标签> --json eval/results-calibration-qwen38.json

四组回复（骗子台词完全相同，来自好组文件里每通电话的脚本台词，按通话顺序）：
- good：旧 qwen3.7-flash 语音人设的原回复（好组 / 上限参照）；
- persona：文字人设（规则引擎 deepsuck.engine + personas.humanize，王阿姨等，即 llm_scammer 默认被测对象）对同一串台词的回复；
- stall：口语但只会 6 句万能拖延话轮换（较隐蔽的差组）；
- bad：客服腔模板轮换 + 原样复述骗子的话 + 满口答应（明显的差组）。

两项测量：
1. 骗子回放：把台词当作骗子已经说过的话、回复当作对方的话，逐轮让 qwen3.8-flash 骗子（default / hard 档，提示词与
   eval/llm_scammer.py 相同）决定继续还是挂断，第一次挂断即停；指标是起疑挂断（bot / trolling）的通话占比、hard 档平均起疑分；
2. 评委：每组每条（台词, 回复）逐题判（default / strict 档，提示词与 eval/realism_judge.py 相同），指标是露馅率（bot=1 占比）和像真人分。
判定口径（写在 docs/EVAL.md）：新档要让差组（bad、stall）的起疑挂断率 / 露馅率比好组高至少 30 个百分点，否则继续调。

配对评委（#164 续，--pair-file）：同一批台词上旧 qwen3.7-flash 与新 qwen3.8-flash 语音人设各自的回复（voice.llm_ab 同一次运行
两个模型的输出，逐轮无状态脚本，台词逐字相同），只过评委（default / strict），看新口径下新旧回复能不能拉开分差：
    python eval/discrimination_calib.py --pair-file run1.json run2.json --run --judge-api sync --budget-tag <标签>

结果文件只含汇总数字，不含回复原文；好组文件不入库。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "python"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name: str, fn: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(fn))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("llm_scammer", "llm_scammer.py")
J = M.J
L = M.L
R = _load("realism_blind", "realism_blind.py")

from deepsuck import sim as SIM  # noqa: E402
from deepsuck.engine import Session, vague_digits  # noqa: E402
from deepsuck.rng import mulberry32  # noqa: E402
from personas.humanize import Humanizer  # noqa: E402

GROUPS = ("good", "persona", "stall", "bad")
OPENING = "喂？"
HARD_MAX_COST_CNY = 2.0


# ---------------------------------------------------------------- data
def load_calls(paths: List[Path], model: str = "qwen3.7-flash", max_calls: int = 28) -> List[dict]:
    """voice.llm_ab 输出 → 通话列表 [{persona, scenario, lines: [台词], good: [回复]}]，去重（同一串台词 + 同一串回复只留一次），
    按场景轮流取，最多 max_calls 通。只取场景在模拟器里的通话。"""
    seen, by_sc = set(), defaultdict(list)
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        rows = (d.get("rows") or {}).get(model) or []
        calls = defaultdict(list)
        for r in rows:
            calls[(r["persona"], r["scenario"], r["call"])].append(r)
        for (pid, sc, _), rs in sorted(calls.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if sc not in SIM.SCENARIO_TYPE:
                continue
            rs = sorted(rs, key=lambda r: r["turn"])
            lines, replies = [r["scammer"] for r in rs], [r["reply"] for r in rs]
            k = json.dumps([lines, replies], ensure_ascii=False)
            if k in seen or not all(replies):
                continue
            seen.add(k)
            by_sc[sc].append({"persona": pid, "scenario": sc, "lines": lines, "good": replies})
    out, i = [], 0
    scs = sorted(by_sc)
    while len(out) < max_calls and any(by_sc[s] for s in scs):
        s = scs[i % len(scs)]
        if by_sc[s]:
            out.append(by_sc[s].pop(0))
        i += 1
    return out


def responder_replies(call: dict, group: str, seed: int) -> List[str]:
    if group == "good":
        return list(call["good"])
    sid = M.session_seed(call["scenario"], call["persona"], seed)
    if group in ("bad", "stall"):
        bot = (M.BadResponder if group == "bad" else M.StallResponder)(sid)
        return [bot.reply(x) for x in call["lines"]]
    pid = call["persona"] if call["persona"] in M.HUMANIZE_PROFILE else "wang"
    s = Session(call["scenario"], pid, rng=mulberry32(seed ^ 0x5EED), now=lambda: 0)
    s.opening()
    hum = Humanizer(profile=M.HUMANIZE_PROFILE.get(pid, pid), seed=seed ^ 0x4855)
    out = []
    for x in call["lines"]:
        r = s.rule_reply(s.ingest(x))
        out.append(vague_digits(hum.apply(r["text"], context=x, intent=r["intent"]).text))
    return out


# ---------------------------------------------------------------- scammer replay
def replay_messages(call: dict, replies: List[str], upto: int, profile: str, corpus: dict, seed: int) -> List[dict]:
    legacy = SIM.load_scripts("legacy")
    kinds = legacy["scenarios"][call["scenario"]]["intel"]
    values = SIM.plant(SIM.Rand(seed))
    msgs = [{"role": "system", "content": M.system_prompt(corpus, call["scenario"], values, kinds, seed, profile)},
            {"role": "user", "content": OPENING}]
    for line, rep in list(zip(call["lines"], replies))[:upto]:
        msgs.append({"role": "assistant", "content": json.dumps({"say": line, "action": "continue"}, ensure_ascii=False)})
        msgs.append({"role": "user", "content": rep})
    return msgs


def replay_call(call: dict, replies: List[str], profile: str, caller, corpus: dict, seed: int) -> dict:
    params = M.params_for(M.MODEL, M.session_seed(call["scenario"], call["persona"], seed))
    sus = []
    for k in range(1, len(replies) + 1):
        t = M.parse_turn(caller(replay_messages(call, replies, k, profile, corpus, seed), params)["content"])
        if "suspicion" in t:
            sus.append(t["suspicion"])
        if t["action"] == "hangup":
            return {"quit": "suspicious" if t["hangup_type"] in M.SUSPICIOUS else "give_up", "turn": k,
                    "category": t.get("category"), "suspicion": sus}
    return {"quit": "survived", "turn": len(replies), "suspicion": sus}


def estimate_replay(calls, groups, profiles, corpus, seed) -> dict:
    inp = out = 0
    for c in calls:
        for g in groups:
            reps = responder_replies(c, g, seed)
            for pr in profiles:
                for k in range(1, len(reps) + 1):
                    inp += sum(J.estimate_tokens(m["content"]) for m in replay_messages(c, reps, k, pr, corpus, seed))
                    out += M.EST_OUT_TOKENS_PER_TURN
    return {"prompt_tokens": inp, "completion_tokens": out, "cost_cny": round(J.cost_cny(inp, out), 4)}


def summarize_replay(rows: List[dict]) -> dict:
    n = max(1, len(rows))
    sus = [x for r in rows for x in r["suspicion"]]
    return {"calls": len(rows), "suspiciousQuit": sum(r["quit"] == "suspicious" for r in rows) / n,
            "giveUp": sum(r["quit"] == "give_up" for r in rows) / n,
            "avgHangupTurn": mean(r["turn"] for r in rows if r["quit"] != "survived") if any(r["quit"] != "survived" for r in rows) else None,
            "avgSuspicion": mean(sus) if sus else None,
            "flagRate": sum(x >= M.FLAG_SUSPICION for x in sus) / len(sus) if sus else None}


# ---------------------------------------------------------------- judge
def judge_items(calls, groups, seed, per_group: int) -> tuple:
    """每组取前 per_group 条（台词, 回复）；同一条台词在四组里各出现一次，题号打乱组别（key 只记组别）。"""
    key, rows, pair = {}, [], 0
    flat = [(c, i) for c in calls for i in range(len(c["lines"]))][:per_group]
    reps = {(id(c), g): responder_replies(c, g, seed) for c in calls for g in groups}
    import random
    rng = random.Random(seed)
    items = []
    for c, i in flat:
        for g in groups:
            items.append((g, pair, R.fill_placeholders(c["lines"][i]), reps[(id(c), g)][i]))
        pair += 1
    rng.shuffle(items)
    for n, (g, p, sc, rep) in enumerate(items, 1):
        q = f"C{n:04d}"
        key[q] = {"form": "A", "condition": g, "pair": p, "persona": "", "scammer_id": "", "scammer_source": "calib",
                  "humanize_seed": None, "stats": R.text_stats(rep)}
        rows.append({"id": q, "scammer": sc, "reply": rep})
    return key, {"A": rows}, pair


# ---------------------------------------------------------------- paired judge（旧 3.7 vs 新 3.8，同一句台词）
def pair_items(paths: List[Path], models: List[str], seed: int, max_pairs: int = 200) -> tuple:
    """voice.llm_ab 输出里同一次运行的两个模型逐轮对齐（同一句台词），两边都有回复的才要；题号打乱，key 只记模型。"""
    import random
    key, rows, pairs = {}, [], []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        cols = [(d.get("rows") or {}).get(m) or [] for m in models]
        for k in range(min(len(c) for c in cols) if cols else 0):
            rs = [c[k] for c in cols]
            if len({r.get("scammer") for r in rs}) != 1 or not all(r.get("reply") for r in rs):
                continue
            pairs.append((rs[0]["scammer"], [r["reply"] for r in rs]))
    pairs = pairs[:max_pairs]
    items = [(m, i, R.fill_placeholders(sc), reps[j]) for i, (sc, reps) in enumerate(pairs) for j, m in enumerate(models)]
    random.Random(seed).shuffle(items)
    for n, (m, i, sc, rep) in enumerate(items, 1):
        q = f"P{n:04d}"
        key[q] = {"form": "A", "condition": m, "pair": i, "persona": "", "scammer_id": "", "scammer_source": "pair",
                  "humanize_seed": None, "stats": R.text_stats(rep)}
        rows.append({"id": q, "scammer": sc, "reply": rep})
    return key, {"A": rows}, len(pairs)


def paired_diff(key: Dict[str, dict], ratings: List[dict], models: List[str]) -> dict:
    """按台词配对：新 − 旧 的像真人分差与露馅率差（models[1] − models[0]），以及新旧谁分高的句数。"""
    by = defaultdict(dict)
    for r in ratings:
        k = key.get(r["id"])
        if k:
            by[k["pair"]][k["condition"]] = r
    both = [v for v in by.values() if all(m in v for m in models[:2])]
    if not both:
        return {"pairs": 0}
    old, new = models[0], models[1]
    dh = [v[new]["human"] - v[old]["human"] for v in both]
    db = [v[new]["bot"] - v[old]["bot"] for v in both]
    return {"pairs": len(both), "human_diff_new_minus_old": round(mean(dh), 3), "detected_diff_new_minus_old": round(mean(db), 3),
            "new_higher": sum(x > 0 for x in dh), "old_higher": sum(x < 0 for x in dh), "tie": sum(x == 0 for x in dh)}


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#164 区分度校准（默认只估算）")
    ap.add_argument("--good-file", type=Path, nargs="+", default=None, help="voice.llm_ab 输出 JSON（qwen3.7-flash 回复，不入库）")
    ap.add_argument("--pair-file", type=Path, nargs="+", default=None,
                    help="配对评委：voice.llm_ab 同一次运行里 --pair-models 两个模型的输出（同一句台词新旧回复各一条）")
    ap.add_argument("--pair-models", default="qwen3.7-flash,qwen3.8-flash", help="旧,新")
    ap.add_argument("--batch-fallback", action="store_true", help="Batch 超时后取消任务、退回同步接口")
    ap.add_argument("--good-model", default="qwen3.7-flash")
    ap.add_argument("--calls", type=int, default=14, help="回放多少通（按场景轮流取），默认 14 = 7 场景 × 2")
    ap.add_argument("--judge-n", type=int, default=60, help="评委每组多少条，默认 60")
    ap.add_argument("--profiles", default="default,hard")
    ap.add_argument("--judge-profiles", default="default,strict")
    ap.add_argument("--judge-api", choices=("sync", "batch"), default="batch")
    ap.add_argument("--batch-timeout", type=float, default=3600.0)
    ap.add_argument("--skip-replay", action="store_true")
    ap.add_argument("--skip-judge", action="store_true")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--max-cost", type=float, default=HARD_MAX_COST_CNY)
    ap.add_argument("--budget-tag", default=None)
    ap.add_argument("--total-budget", type=float, default=L.HARD_TOTAL_CNY)
    ap.add_argument("--ledger", type=Path, default=L.LEDGER)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        max_cost = L.cap(min(a.max_cost, HARD_MAX_COST_CNY), a.budget_tag, a.total_budget, a.ledger)
    except L.LedgerBudgetError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not a.good_file and not a.pair_file:
        ap.error("需要 --good-file 或 --pair-file")
    corpus = json.loads(SIM.default_corpus_path().read_text(encoding="utf-8"))
    calls = load_calls(a.good_file, a.good_model, a.calls) if a.good_file else []
    if not a.good_file:
        a.skip_replay = a.skip_judge = True
    profiles = [x for x in a.profiles.split(",") if x]
    res = {"date": M.date.today().isoformat(), "model": M.MODEL, "goodModel": a.good_model, "seed": a.seed,
           "calls": len(calls), "turns": sum(len(c["lines"]) for c in calls),
           "scenarios": sorted({c["scenario"] for c in calls}), "groups": list(GROUPS)}
    log = lambda s: print(s, file=sys.stderr)  # noqa: E731
    spent = 0.0
    pending = False
    if not a.skip_replay:
        est = estimate_replay(calls, GROUPS, profiles, corpus, a.seed)
        log(f"回放估算：{len(calls)} 通 × {len(GROUPS)} 组 × {len(profiles)} 档，至多约 {est['cost_cny']} 元（上限 {max_cost:.4f} 元）")
        res["replayEstimate"] = est
        if est["cost_cny"] > max_cost:
            print(f"估算 {est['cost_cny']} 元超过上限 {max_cost:.4f} 元，拒绝运行", file=sys.stderr)
            return 2
        if a.run:
            from concurrent.futures import ThreadPoolExecutor
            meter = M.Meter(max_cost)
            holder = {}

            def get_client():
                if "c" not in holder:
                    holder["c"] = J.default_client_factory()()
                    if holder["c"] is None:
                        raise RuntimeError("缺少 DASHSCOPE_API_KEY")
                return holder["c"]
            out = {}
            try:
                for pr in profiles:
                    caller = M.Caller(get_client, meter, M.CACHE_DIR, False, "calib-" + M.PROMPT_VERSIONS[pr])
                    jobs = [(g, i) for g in GROUPS for i in range(len(calls))]

                    def work(j, pr=pr, caller=caller):
                        g, i = j
                        return j, replay_call(calls[i], responder_replies(calls[i], g, a.seed), pr, caller, corpus, a.seed)
                    with ThreadPoolExecutor(max_workers=a.workers) as ex:
                        for (g, i), row in ex.map(work, jobs):
                            out.setdefault(pr, {}).setdefault(g, []).append(row)
            finally:
                u = dict(meter.u)
                if a.budget_tag and u["requests"]:
                    L.append(a.budget_tag, "eval/discrimination_calib.py replay", M.MODEL, u,
                             f"calls={len(calls)} groups={','.join(GROUPS)} profiles={','.join(profiles)} "
                             f"cacheHit={u['cached_tokens'] / max(1, u['prompt_tokens']):.1%}", a.ledger)
            spent += meter.u["cost_cny"]
            res["replay"] = {pr: {g: summarize_replay(rows) for g, rows in gs.items()} for pr, gs in out.items()}
            res["replayUsage"] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in meter.u.items()}
    if not a.skip_judge:
        key, forms, npairs = judge_items(calls, GROUPS, a.seed, a.judge_n)
        res["judgeItemsPerGroup"] = npairs
        res["judge"] = {}
        for jp in [x for x in a.judge_profiles.split(",") if x]:
            left = max(0.0, max_cost - spent)
            held = {}
            try:
                try:
                    o = J.run_judge(key, forms, J.default_client_factory(), n_pairs=npairs, mode="item", seed=a.seed,
                                    max_cost=min(left, J.HARD_MAX_COST_CNY), dry_run=not a.run, profile=jp, api=a.judge_api,
                                    batch_timeout=a.batch_timeout, log=log, usage_hook=lambda u: held.__setitem__("u", u),
                                    batch_fallback=a.batch_fallback, workers=a.workers)
                except J.BatchPending as e:
                    log(f"评委 {jp} 档：{e}")
                    res["judge"][jp] = {"pending": True}
                    pending = True
                    continue
            finally:
                u = held.get("u")
                if a.budget_tag and a.run and u and u.get("requests"):
                    L.append(a.budget_tag, f"eval/discrimination_calib.py judge ({a.judge_api})", M.MODEL, u,
                             f"profile={jp} items={len(forms['A'])} "
                             f"cacheHit={u.get('cached_tokens', 0) / max(1, u.get('prompt_tokens', 0)):.1%}", a.ledger)
            if a.run:
                spent += o["usage"]["cost_cny"]
                sc = R.score(key, o["ratings"])
                res["judge"][jp] = {"api": a.judge_api, "batchFallback": o.get("batch_fallback"),
                                    "invalid": o["invalid_items"], "usage": o["usage"],
                                    "conditions": sc["conditions"]}
            else:
                res["judge"][jp] = {"estimate": o["estimate"]}
    if a.pair_file:
        models = [x for x in a.pair_models.split(",") if x][:2]
        pkey, pforms, npairs = pair_items(a.pair_file, models, a.seed)
        res["pair"] = {"models": models, "pairs": npairs, "judge": {}}
        for jp in [x for x in a.judge_profiles.split(",") if x]:
            left = max(0.0, max_cost - spent)
            held = {}
            try:
                try:
                    o = J.run_judge(pkey, pforms, J.default_client_factory(), n_pairs=npairs, mode="item", seed=a.seed,
                                    max_cost=min(left, J.HARD_MAX_COST_CNY), dry_run=not a.run, profile=jp, api=a.judge_api,
                                    batch_timeout=a.batch_timeout, log=log, usage_hook=lambda u: held.__setitem__("u", u),
                                    batch_fallback=a.batch_fallback, workers=a.workers)
                except J.BatchPending as e:
                    log(f"配对评委 {jp} 档：{e}")
                    res["pair"]["judge"][jp] = {"pending": True}
                    pending = True
                    continue
            finally:
                u = held.get("u")
                if a.budget_tag and a.run and u and u.get("requests"):
                    L.append(a.budget_tag, f"eval/discrimination_calib.py pair-judge ({a.judge_api})", M.MODEL, u,
                             f"profile={jp} models={','.join(models)} items={len(pforms['A'])} "
                             f"cacheHit={u.get('cached_tokens', 0) / max(1, u.get('prompt_tokens', 0)):.1%}", a.ledger)
            if a.run:
                spent += o["usage"]["cost_cny"]
                sc = R.score(pkey, o["ratings"])
                res["pair"]["judge"][jp] = {"api": a.judge_api, "batchFallback": o.get("batch_fallback"),
                                            "invalid": o["invalid_items"], "usage": o["usage"],
                                            "conditions": sc["conditions"], "paired": paired_diff(pkey, o["ratings"], models)}
            else:
                res["pair"]["judge"][jp] = {"estimate": o["estimate"]}
    res["spentCny"] = round(spent, 6)
    if pending:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        print("有 Batch 任务未完成，稍后用同样参数重跑（不会重复提交）", file=sys.stderr)
        return 4
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
