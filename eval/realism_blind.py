"""“像不像真人”盲测：生成评测表、汇总评分。

    # 1) 生成盲测表（默认骗子台词来自 corpus/scripts/*.yaml）
    python eval/realism_blind.py make --out-dir eval/realism --seed 1 --n 60
    # 以后换成情报分析师的真实语料文件（deepsuck.core.scam-scripts/v1，或 JSON/JSONL/YAML 列表）
    python eval/realism_blind.py make --scammer-file site/assets/core/scam_scripts.json --out-dir eval/realism
    # 2) 评测者在 form-A.csv / form-B.csv 里填 human / bot / unreadable 三列后
    python eval/realism_blind.py score --key eval/realism/key.json eval/realism/rated-*.csv --json eval/results-realism.json
    # 3) 可选：大模型评委代理指标（默认关闭，需显式 --judge llm；见 eval/realism_judge.py）
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --dry-run   # 只估算费用
    python eval/realism_blind.py score --key eval/realism/key.json --judge llm --json eval/realism/judge-llm.json

设计：
- 每道题 = 一条骗子消息 + 一条人设回复；回复有三种条件：
  raw（人设原句）、humanized（同一句经 personas.humanize 真人化，固定种子）、human（可选：--human-replies 提供的真人回复，作为上限参照）；
- 同一句的 raw / humanized 分到 A、B 两份表的不同位置（A 表第 k 题是 raw，B 表就是 humanized），同一个评测者不会看到同一句的两个版本；
- 回复按人设不放回抽取（句池够用时一份表里没有重复句，避免评测者 / 评委跨题比较“雷同”）；
- 评测者只看到骗子消息和回复，不知道条件；key.json 记录每题的条件、人设、种子与来源，不发给评测者。
- make 和人工评分不调用大模型、不联网；只有显式 --judge llm 时才调用评委模型；骗子消息里的占位符一律填虚构的打码值。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personas.humanize import Humanizer  # noqa: E402
from personas.humanize import confusion as C  # noqa: E402

SCRIPTS_DIR = ROOT / "corpus" / "scripts"
PROMPTS_DIR = ROOT / "personas" / "prompts"
PERSONAS = ("retiree", "mom", "graduate", "shop_owner")
CONDITIONS = ("raw", "humanized", "human")

# 占位符的展示值：全部虚构，且已打码（与首页示例一致的格式）
FILL = {
    "银行卡": "622202*********3445", "手机号": "139****2233", "电话": "139****2233", "户名": "王**",
    "网址": "xi***mo.top", "APP名": "星辰任务", "微信号": "wx_***88", "QQ号": "28****321",
    "钱包地址": "TQ8x***9Fz", "机构": "某平台", "姓氏": "王", "金额": "两千元", "工号": "A1234",
    "警号": "0****1", "城市": "本市", "二维码": "这个二维码",
}
_PH = re.compile(r"\{([^{}]{1,8})\}")


def _yaml():
    import yaml  # type: ignore
    return yaml


def fill_placeholders(text: str, fill: Optional[Dict[str, str]] = None) -> str:
    fill = {**FILL, **(fill or {})}
    return _PH.sub(lambda m: fill.get(m.group(1), "某" + m.group(1)), text)


# ---------------------------------------------------------------- scammer lines
def load_corpus_scripts(directory: Path = SCRIPTS_DIR) -> List[dict]:
    """corpus/scripts/*.yaml → 统一格式 [{id, type, stage, text, source}]（只取骗子一方的话）。"""
    yaml = _yaml()
    out = []
    for p in sorted(directory.glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        src = d.get("source", "")
        for st in d["stages"]:
            for k, line in enumerate(st["lines"]):
                out.append({"id": f"{d['id']}/{st['id']}/{k}", "type": d["id"], "stage": st["id"], "text": line,
                            "source": src})
        for ex in d.get("examples", []):
            for k, t in enumerate(ex["turns"]):
                if t["role"] == "scammer":
                    out.append({"id": f"{d['id']}/{ex['id']}/{k}", "type": d["id"], "stage": "example",
                                "text": t["text"], "source": src})
    return out


def load_scammer_file(path: Path) -> List[dict]:
    """外部骗子语料（情报分析师的真实语料文件），支持：
    - deepsuck.core.scam-scripts/v1（entries[].text / type / stage 或 phase / sourceLabel），占位符示例值不使用，统一填打码值；
    - JSON 或 YAML：字符串列表，或对象列表（text 或 r 字段，可选 id / type / stage / source）；
    - JSONL：每行一个上述对象或字符串。"""
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        items = [json.loads(x) for x in raw.splitlines() if x.strip()]
    elif path.suffix in (".yaml", ".yml"):
        items = _yaml().safe_load(raw)
    else:
        items = json.loads(raw)
    if isinstance(items, dict):
        items = items.get("entries") or items.get("lines") or items.get("items") or []
    out = []
    for k, it in enumerate(items):
        if isinstance(it, str):
            it = {"text": it}
        text = it.get("text") or it.get("r")
        if not text:
            continue
        out.append({"id": str(it.get("id", f"{path.stem}/{k}")), "type": it.get("type", ""),
                    "stage": it.get("stage") or it.get("phase", ""), "text": text,
                    "source": it.get("sourceLabel") or it.get("source", str(path.name))})
    if not out:
        raise ValueError(f"no scammer lines found in {path}")
    return out


# ---------------------------------------------------------------- persona replies
def persona_replies(persona_id: str) -> List[str]:
    """人设原句池：sample_lines + elicit_moves（去掉句末的分号）+ stall_pools 各池，去重保序。
    原来只有前两项（每个人设 7 句），60 个句对里同一句会在一份表里出现多次，评委会拿来跨题比较；
    加上 stall_pools 后每个人设 30 句左右，make 按人设不放回抽取，一份表里不再有重复句。"""
    d = _yaml().safe_load((PROMPTS_DIR / f"{persona_id}.yaml").read_text(encoding="utf-8"))
    pool = list(d["sample_lines"]) + [re.sub(r"[；;]\s*$", "", x) for x in d["elicit_moves"]]
    for lines in (d.get("stall_pools") or {}).values():
        pool += list(lines or [])
    out, seen = [], set()
    for x in pool:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class _Deck:
    """按人设不放回抽句：抽完一轮才重新洗牌，保证句池够用时同一句不会出现两次。"""

    def __init__(self, pool: List[str], rng: random.Random):
        self.pool, self.rng, self.left = list(pool), rng, []

    def draw(self) -> str:
        if not self.left:
            self.left = list(self.pool)
            self.rng.shuffle(self.left)
        return self.left.pop()


def load_human_replies(path: Path) -> List[dict]:
    """可选的真人回复（上限参照）：JSONL / JSON 列表，每条 {persona, reply, scammer?}。"""
    raw = path.read_text(encoding="utf-8")
    items = [json.loads(x) for x in raw.splitlines() if x.strip()] if path.suffix == ".jsonl" else json.loads(raw)
    return [it for it in items if it.get("reply")]


# ---------------------------------------------------------------- automatic proxies
_PUNCT = re.compile(r"[，,。！？!?；;：:、…~～]")
_WRONG = sorted({w for v in C.HOMOPHONE_WORDS.values() for w in v}, key=len, reverse=True)


def text_stats(text: str) -> dict:
    n = max(1, len(text))
    return {"chars": len(text), "punct_per_10": round(10 * len(_PUNCT.findall(text)) / n, 2),
            "ends_with_punct": bool(text) and bool(_PUNCT.match(text[-1]))}


# ---------------------------------------------------------------- make
def make(n: int = 60, seed: int = 1, scammer_file: Optional[Path] = None, human_file: Optional[Path] = None,
         personas: Iterable[str] = PERSONAS) -> dict:
    rng = random.Random(seed)
    lines = load_scammer_file(scammer_file) if scammer_file else load_corpus_scripts()
    personas = list(personas)
    pools = {p: persona_replies(p) for p in personas}
    decks = {p: _Deck(pools[p], rng) for p in personas}
    humans = load_human_replies(human_file) if human_file else []
    picked = rng.sample(lines, min(n, len(lines))) if n <= len(lines) else [rng.choice(lines) for _ in range(n)]
    pairs = []
    for k, sc in enumerate(picked):
        pid = personas[k % len(personas)]
        scam = fill_placeholders(sc["text"])
        reply = decks[pid].draw()
        hseed = seed * 100000 + k
        hum = Humanizer(profile=pid, seed=hseed).apply(reply, context=scam)
        pairs.append({"pair": k, "persona": pid, "scammer": scam, "scammer_id": sc["id"], "scammer_type": sc["type"],
                      "scammer_source": sc["source"], "raw": reply, "humanized": hum.text, "humanize_seed": hseed,
                      "humanize_ops": hum.ops})
    forms = {"A": [], "B": []}
    key = {}
    for p in pairs:
        conds = ("raw", "humanized") if p["pair"] % 2 == 0 else ("humanized", "raw")
        for form, cond in zip(("A", "B"), conds):
            forms[form].append((p, cond))
    for j, h in enumerate(humans):  # 真人回复两份表都放（同一句真人话只有一个版本）
        p = {"pair": f"h{j}", "persona": h.get("persona", ""), "scammer": fill_placeholders(h.get("scammer", "")),
             "scammer_id": "", "scammer_type": "", "scammer_source": "human", "human": h["reply"]}
        for form in forms:
            forms[form].append((p, "human"))
    out_forms = {}
    for form, items in forms.items():
        rng.shuffle(items)
        rows = []
        for idx, (p, cond) in enumerate(items, 1):
            qid = f"{form}{idx:03d}"
            reply = p[cond]
            rows.append({"id": qid, "scammer": p["scammer"], "reply": reply})
            key[qid] = {"form": form, "condition": cond, "pair": p["pair"], "persona": p["persona"],
                        "scammer_id": p["scammer_id"], "scammer_source": p["scammer_source"],
                        "humanize_seed": p.get("humanize_seed"), "stats": text_stats(reply)}
        out_forms[form] = rows
    return {"meta": {"schema": "deepsuck.realism_blind/1", "seed": seed, "n_pairs": len(pairs),
                     "scammer_source": str(scammer_file.relative_to(ROOT) if scammer_file and scammer_file.is_absolute()
                                           and ROOT in scammer_file.parents else (scammer_file or "corpus/scripts")),
                     "human_replies": len(humans)},
            "forms": out_forms, "key": key, "pairs": pairs}


def write_make(data: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for form, rows in data["forms"].items():
        with open(out_dir / f"form-{form}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "scammer", "reply", "human", "bot", "unreadable", "note"])
            for r in rows:
                w.writerow([r["id"], r["scammer"], r["reply"], "", "", "", ""])
    (out_dir / "key.json").write_text(json.dumps({"meta": data["meta"], "key": data["key"], "pairs": data["pairs"]},
                                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "评测说明：每行是一条骗子消息和一条回复。请判断回复像不像真人随手发的消息。\n"
        "human：1–5 分（1 = 一看就是机器，5 = 完全像真人）\n"
        "bot：你认为这条是机器人写的填 1，否则填 0\n"
        "unreadable：看不懂或读着别扭填 1，否则留空或 0\n"
        "请不要和其他评测者讨论，也不要打开 key.json。\n", encoding="utf-8")


# ---------------------------------------------------------------- score
def read_ratings(paths: Iterable[Path]) -> List[dict]:
    rows = []
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if not (r.get("human") or "").strip() and not (r.get("bot") or "").strip():
                    continue
                rows.append({"id": r["id"].strip(), "rater": (r.get("rater") or p.stem).strip(),
                             "human": float(r["human"]) if (r.get("human") or "").strip() else None,
                             "bot": int(r["bot"]) if (r.get("bot") or "").strip() else None,
                             "unreadable": int(r["unreadable"]) if (r.get("unreadable") or "").strip() else 0})
    return rows


def read_forms(forms_dir: Path) -> Dict[str, List[dict]]:
    """读回 make 生成的 form-A.csv / form-B.csv（只取 id / scammer / reply，不读评分列）。"""
    out = {}
    for form in ("A", "B"):
        p = forms_dir / f"form-{form}.csv"
        with open(p, encoding="utf-8-sig", newline="") as f:
            out[form] = [{"id": r["id"].strip(), "scammer": r["scammer"], "reply": r["reply"]} for r in csv.DictReader(f)]
    return out


def _mean_ci(xs: List[float]):
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    if len(xs) < 2:
        return m, None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return m, 1.96 * sd / math.sqrt(len(xs))


def score(key: Dict[str, dict], ratings: List[dict], seed: int = 0, boot: int = 2000) -> dict:
    by_cond: Dict[str, dict] = {}
    for r in ratings:
        k = key.get(r["id"])
        if not k:
            continue
        c = by_cond.setdefault(k["condition"], {"human": [], "bot": [], "unreadable": []})
        if r["human"] is not None:
            c["human"].append(r["human"])
        if r["bot"] is not None:
            c["bot"].append(r["bot"])
        c["unreadable"].append(r["unreadable"])
    res = {"conditions": {}}
    for cond, c in by_cond.items():
        m, ci = _mean_ci(c["human"])
        res["conditions"][cond] = {
            "n": max(len(c["human"]), len(c["bot"])),
            "human_mean": None if m is None else round(m, 3), "human_ci95": None if ci is None else round(ci, 3),
            "detected_rate": round(sum(c["bot"]) / len(c["bot"]), 3) if c["bot"] else None,
            "unreadable_rate": round(sum(c["unreadable"]) / len(c["unreadable"]), 3) if c["unreadable"] else None,
        }
    # humanized − raw：按句对（pair）配对的露馅率差，自助法 95% 区间
    per_pair: Dict[object, Dict[str, List[int]]] = {}
    for r in ratings:
        k = key.get(r["id"])
        if k and k["condition"] in ("raw", "humanized") and r["bot"] is not None:
            per_pair.setdefault(k["pair"], {"raw": [], "humanized": []})[k["condition"]].append(r["bot"])
    diffs = [sum(v["humanized"]) / len(v["humanized"]) - sum(v["raw"]) / len(v["raw"])
             for v in per_pair.values() if v["raw"] and v["humanized"]]
    if diffs:
        rng = random.Random(seed)
        bs = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(boot))
        res["detected_diff_humanized_minus_raw"] = {"pairs": len(diffs), "mean": round(sum(diffs) / len(diffs), 3),
                                                    "ci95": [round(bs[int(0.025 * boot)], 3),
                                                             round(bs[int(0.975 * boot) - 1], 3)]}
    # 评测者之间对 bot 判断的两两一致率
    by_item: Dict[str, List[int]] = {}
    for r in ratings:
        if r["bot"] is not None:
            by_item.setdefault(r["id"], []).append(r["bot"])
    agree = tot = 0
    for v in by_item.values():
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                tot += 1
                agree += v[i] == v[j]
    res["pairwise_agreement"] = round(agree / tot, 3) if tot else None
    res["raters"] = len({r["rater"] for r in ratings})
    res["ratings"] = len(ratings)
    return res


def auto_stats(key: Dict[str, dict]) -> dict:
    """不需要评测者的自动指标：各条件的平均长度、标点密度、句末带标点比例。"""
    out = {}
    for cond in CONDITIONS:
        st = [k["stats"] for k in key.values() if k["condition"] == cond]
        if st:
            out[cond] = {"items": len(st), "chars": round(sum(s["chars"] for s in st) / len(st), 1),
                         "punct_per_10": round(sum(s["punct_per_10"] for s in st) / len(st), 2),
                         "ends_with_punct": round(sum(s["ends_with_punct"] for s in st) / len(st), 3)}
    return out


def load_judge():
    """按文件路径加载 eval/realism_judge.py（eval/ 不是包）。"""
    import importlib.util
    if "realism_judge" in sys.modules:
        return sys.modules["realism_judge"]
    spec = importlib.util.spec_from_file_location("realism_judge", Path(__file__).with_name("realism_judge.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["realism_judge"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="像不像真人：盲测表生成与评分")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--n", type=int, default=60, help="句对数（每对在 A/B 表各出一个版本）")
    mk.add_argument("--seed", type=int, default=1)
    mk.add_argument("--scammer-file", type=Path, default=None,
                    help="骗子语料文件；省略时用 corpus/scripts/*.yaml")
    mk.add_argument("--human-replies", type=Path, default=None, help="可选：真人回复（JSONL/JSON）")
    mk.add_argument("--out-dir", type=Path, default=ROOT / "eval" / "realism")
    sc = sub.add_parser("score")
    sc.add_argument("ratings", nargs="*", type=Path, help="评测者填好的表（rated-*.csv）；只跑大模型评委时可省略")
    sc.add_argument("--key", type=Path, required=True)
    sc.add_argument("--json", type=Path, default=None)
    sc.add_argument("--judge", choices=("none", "llm"), default="none",
                    help="自动评委代理指标；默认 none，llm = 百炼 qwen-plus（需要 DASHSCOPE_API_KEY，会产生费用）")
    sc.add_argument("--forms-dir", type=Path, default=None, help="form-A/B.csv 所在目录，默认与 key.json 相同")
    sc.add_argument("--judge-n", type=int, default=60, help="评委评前多少个句对（每对 A、B 各一题），默认 60")
    sc.add_argument("--judge-mode", choices=("item", "batch"), default="item",
                    help="item（默认）= 逐题独立判，一题一次请求；batch = 每次请求放同一份表的若干题（旧做法）")
    sc.add_argument("--judge-batch", type=int, default=10, help="批量模式下每次请求放几道题（同一份表），默认 10")
    sc.add_argument("--judge-seed", type=int, default=1)
    sc.add_argument("--judge-model", default="qwen-plus")
    sc.add_argument("--max-cost", type=float, default=1.0, help="费用上限（元），不能超过 1 元")
    sc.add_argument("--dry-run", action="store_true", help="只估算 token 与费用，不调用")
    sc.add_argument("--refresh-cache", action="store_true", help="忽略缓存重新调用（会再次计费）")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        data = make(a.n, a.seed, a.scammer_file, a.human_replies)
        write_make(data, a.out_dir)
        print(json.dumps({"meta": data["meta"], "auto": auto_stats(data["key"])}, ensure_ascii=False, indent=2))
        return 0
    if not a.ratings and a.judge == "none":
        ap.error("score 需要评分表，或显式 --judge llm")
    key = json.loads(a.key.read_text(encoding="utf-8"))["key"]
    res = {}
    if a.ratings:
        res["score"] = score(key, read_ratings(a.ratings))
    res["auto"] = auto_stats(key)
    if a.judge == "llm":
        J = load_judge()  # 只在显式打开时加载
        forms_dir = a.forms_dir or a.key.parent
        try:
            out = J.run_judge(key, read_forms(forms_dir), J.default_client_factory(), n_pairs=a.judge_n,
                              batch_size=a.judge_batch, mode=a.judge_mode, seed=a.judge_seed, model=a.judge_model, max_cost=a.max_cost,
                              cache_dir=J.CACHE_DIR, dry_run=a.dry_run, refresh=a.refresh_cache, log=lambda m: print(m, file=sys.stderr))
        except J.BudgetError as e:
            print(f"拒绝运行：{e}", file=sys.stderr)
            return 2
        except RuntimeError as e:
            print(f"大模型评委未运行：{e}", file=sys.stderr)
            return 3
        judge = {"note": "代理指标：大模型评委的判断，不能代替人工盲测，可能有评委偏差",
                 "model": out["model"], "mode": out["mode"], "date": out["date"], "seed": out["seed"], "estimate": out["estimate"],
                 "dry_run": out["dry_run"]}
        if not out["dry_run"]:
            judge.update({"items": len(out["ratings"]), "invalid_items": out["invalid_items"], "usage": out["usage"],
                          "score": score(key, out["ratings"])})
            with open(forms_dir / "judge-llm.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["id", "rater", "human", "bot", "unreadable", "reason"])
                for q, j in sorted(out["judgments"].items()):
                    w.writerow([q, f"llm:{out['model']}", j["human"], j["bot"], j["unreadable"], j["reason"]])
        res["llm_judge"] = judge
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
