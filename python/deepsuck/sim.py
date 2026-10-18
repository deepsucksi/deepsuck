"""骗子模拟器 + 评测（LLM-free，可复现）。

用 eval/scammer-scripts.json 中的脚本化骗子（按阶段推进话术、被追问时按概率暴露虚构情报、被拖延时耐心下降），
与人设规则引擎（以及两个基线：复读机 parrot、随机台词 random）对练，统计：
  - 拖延轮数（骗子发出的消息数，直到耐心耗尽/起疑/达到上限）与估算骗子耗时；
  - 情报暴露率（骗子暴露的虚构情报 / 脚本中的全部情报）与提取率（被提取器正确捕获 / 已暴露）；
  - 重复率（与之前完全相同的机器人回复）与近重复率（字符二元组 Jaccard ≥ 0.8）；
  - 泄露率（机器人回复含 ≥6 位连续数字，即可能给出真实号码/验证码；紧挨 * 的打码值数字段不计）。

CLI：python -m deepsuck.sim --seeds 30 [--reveal standard|hard] [--json out.json] [--md out.md]
Apache-2.0
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

from .core import core_dir
from .engine import Session
from .extractors import BANKS
from .personas import PERSONAS, SCENARIOS
from .rng import mulberry32

MAX_TURNS = 40
STALL = {"ask_repeat", "misunderstand", "tech_trouble", "slow_walk", "otp_stall", "info_stall", "urgency_stall"}
ENGAGED = {"opening", "scared", "greedy", "romance", "secrecy", "generic", "task_stall", "loan_stall", "campus_stall"}
ELICIT = {"elicit_account": "bank", "elicit_wallet": "wallet", "elicit_contact": "phone", "elicit_url": "url"}
CN = dict(zip("0123456789", "零幺二三四五六七八九"))
NAMES = ["赵明", "钱伟", "孙丽", "李强", "周杰", "吴刚", "郑华", "冯涛"]
WORDS = ["refund", "kefu", "gold", "vip", "task", "loan", "safe", "win", "coin", "help", "jd", "tb", "cash", "fast"]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def default_scripts_path() -> Path:
    return core_dir().parent.parent.parent / "eval" / "scammer-scripts.json"


class Rand:
    def __init__(self, seed: int):
        self.r = mulberry32(seed)

    def random(self) -> float:
        return self.r()

    def int(self, n: int) -> int:
        return int(self.r() * n)

    def choice(self, xs):
        return xs[self.int(len(xs))]

    def digits(self, n: int) -> str:
        return "".join(str(self.int(10)) for _ in range(n))


def plant(rd: Rand) -> Dict[str, str]:
    """生成一套虚构情报（域名一律 .example）。"""
    bank = "62" + rd.digits(17)
    phone = "1" + rd.choice("3456789") + rd.digits(9)
    domain = rd.choice(WORDS) + "-" + rd.choice(WORDS) + rd.digits(2) + ".example"
    v = {
        "bank": bank,
        "bank_cn": " ".join("".join(CN[c] for c in bank[i:i + 4]) for i in range(0, len(bank), 4)),
        "bank_spaced": " ".join(bank[i:i + 4] for i in range(0, len(bank), 4)),
        "name": rd.choice(NAMES),
        "bankName": rd.choice([b for b in BANKS if b.endswith("银行")]),
        "phone": phone,
        "phone_cn": "".join(CN[c] for c in phone),
        "phone_dashed": f"{phone[:3]}-{phone[3:7]}-{phone[7:]}",
        "wx": rd.choice("abcdefghkmnpqrstuvwxyz") + rd.choice(WORDS) + "_" + rd.digits(4),
        "qq": str(1 + rd.int(9)) + rd.digits(8),
        "tron": "T" + "".join(rd.choice(B58) for _ in range(33)),
        "eth": "0x" + "".join(rd.choice("0123456789abcdef") for _ in range(40)),
        "domain": domain,
        "domain_dot": domain.replace(".example", " 点 example"),
    }
    # --reveal hard 用：全部由上面的真值确定性变换得到，不额外消耗随机数（standard 模式结果不变）
    fw = {c: chr(0xFF10 + int(c)) for c in "0123456789"}
    cap = dict(zip("0123456789", "零壹贰叁肆伍陆柒捌玖"))
    circ = dict(zip("0123456789", "⓪①②③④⑤⑥⑦⑧⑨"))
    v.update({
        "bank_fw": " ".join("".join(fw[c] for c in bank[i:i + 4]) for i in range(0, len(bank), 4)),
        "bank_dash": "-".join(bank[i:i + 4] for i in range(0, len(bank), 4)),
        "bank_cap": "".join(cap[c] for c in bank),
        "bank_mix": "".join(c if i % 2 == 0 else CN[c] for i, c in enumerate(bank)),
        "phone_circled": "".join(circ[c] for c in phone),
        "phone_dots": f"{phone[:3]}.{phone[3:7]}.{phone[7:]}",
        "phone_mix": "".join(c if i % 2 == 0 else CN[c] for i, c in enumerate(phone)),
        "phone_spaced_cn": " ".join(CN[c] for c in phone),
        "qq_spaced": " ".join(v["qq"][i:i + 3] for i in range(0, len(v["qq"]), 3)),
        "domain_dun": domain.replace(".example", "丶example"),
        "domain_mid": domain.replace(".example", "·example"),
        "domain_dotword": domain.replace(".example", "(dot)example"),
    })
    return v


# 模板占位符 → 真值（类型, 规范值）
TRUTH = {
    "bank": ("bank_card", "bank"), "bank_cn": ("bank_card", "bank"), "bank_spaced": ("bank_card", "bank"),
    "name": ("name", "name"), "phone": ("phone", "phone"), "phone_cn": ("phone", "phone"), "phone_dashed": ("phone", "phone"),
    "wx": ("wechat", "wx"), "qq": ("qq", "qq"), "tron": ("crypto_tron", "tron"), "eth": ("crypto_eth", "eth"),
    "domain": ("url", "domain"), "domain_dot": ("url", "domain"),
    "bank_fw": ("bank_card", "bank"), "bank_dash": ("bank_card", "bank"), "bank_cap": ("bank_card", "bank"), "bank_mix": ("bank_card", "bank"),
    "phone_circled": ("phone", "phone"), "phone_dots": ("phone", "phone"), "phone_mix": ("phone", "phone"),
    "phone_spaced_cn": ("phone", "phone"), "qq_spaced": ("qq", "qq"),
    "domain_dun": ("url", "domain"), "domain_mid": ("url", "domain"), "domain_dotword": ("url", "domain"),
}


def _canon(type_: str, v: str) -> str:
    v = str(v)
    if type_ in ("bank_card", "phone", "qq"):
        d = re.sub(r"[^0-9]", "", v)
        return d[2:] if type_ == "phone" and len(d) == 13 and d.startswith("86") else d
    if type_ == "url":
        m = re.sub(r"^[a-z]+://", "", v.lower())
        return re.sub(r"^www\.", "", m.split("/")[0])
    if type_ == "crypto_eth":
        return v.lower()
    return v


def _bigrams(s: str) -> set:
    s = re.sub(r"\s", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


class Scammer:
    def __init__(self, script: dict, common: dict, rd: Rand, reveal: str = "standard"):
        self.s, self.c, self.rd = script, common, rd
        self.reveal_key = "revealHard" if reveal == "hard" else "reveal"
        self.stage = 0
        self.patience = 6 + rd.random() * 6
        self.values = plant(rd)
        self.todo = list(script["intel"])  # 还没暴露的情报类别
        self.revealed: List[tuple] = []     # (type, canon)
        self.quit_reason: Optional[str] = None

    def pitch(self) -> str:
        p = self.s["pitch"]
        line = self.rd.choice(p[min(self.stage, len(p) - 1)])
        self.stage += 1
        return line

    def reveal(self, kind: str) -> str:
        tpl = self.rd.choice(self.c[self.reveal_key][kind])
        for ph in re.findall(r"\{(\w+)\}", tpl):
            if ph not in TRUTH:
                continue
            t, key = TRUTH[ph]
            item = (t, _canon(t, self.values[key]))
            if item not in self.revealed:
                self.revealed.append(item)
        if kind in self.todo:
            self.todo.remove(kind)
        return tpl.format(**self.values)

    def asked_kind(self, bot_text: str, intent: str, persona: dict) -> Optional[str]:
        if intent in ELICIT:
            return ELICIT[intent]
        for k, q in persona["asks"].items():
            if k != "none" and q and q in bot_text:
                return k
        return None

    def respond(self, bot_text: str, intent: str, persona: dict, duplicate: bool) -> Optional[str]:
        rd = self.rd
        snap = (list(self.todo), list(self.revealed))
        prefix = ""
        if duplicate:
            self.patience -= 2
            prefix = rd.choice(self.c["suspicious"])
        kind = self.asked_kind(bot_text, intent, persona)
        if kind == "name" and "name" not in self.todo:
            kind = "bank" if "bank" in self.todo else None
        msg = None
        if kind:
            if kind in self.todo and kind in self.s["intel"]:
                if rd.random() < 0.8:
                    self.patience += 0.5
                    msg = self.reveal(kind)
                else:
                    self.patience -= 0.5
                    msg = rd.choice(self.c["urge"])
            elif kind in self.s["intel"]:
                self.patience -= 1
                msg = rd.choice(self.c["already"])
        if msg is None:
            if intent in STALL:
                self.patience -= 1
                msg = rd.choice(self.c["urge"] + self.c["repeat"])
            elif intent == "verify_identity":
                self.patience -= 1.5
                msg = rd.choice(self.c["urge"])
            elif intent == "fake_progress":
                self.patience -= 0.5
                msg = rd.choice(self.c["urge"])
            else:  # 被"配合"：推进剧本
                self.patience -= 0.25
                if self.stage >= 2 and self.todo and rd.random() < 0.3:
                    msg = self.reveal(self.todo[0])  # 骗子主动给账户/链接
                elif self.stage < len(self.s["pitch"]):
                    msg = self.pitch()
                elif self.todo:
                    msg = self.reveal(self.todo[0])
                else:
                    self.patience -= 0.75
                    msg = rd.choice(self.c["urge"])
        if self.patience <= 0:
            self.quit_reason = "suspicious" if duplicate else "patience"
            self.todo, self.revealed = snap  # 挂断：这句没发出去
            return None
        return (prefix + msg) if prefix else msg


class Bot:
    """被测对象：rule（DeepSuck 规则引擎）| parrot（复读机基线）| random（无策略随机台词基线）。"""

    def __init__(self, policy: str, session: Session, rd: Rand):
        self.policy, self.s, self.rd = policy, session, rd

    def reply(self, text: str) -> dict:
        a = self.s.ingest(text)
        if self.policy == "rule":
            return self.s.rule_reply(a)
        if self.policy == "parrot":
            return self.s.record_bot("嗯嗯，好的，然后呢？", "generic")
        intent = self.rd.choice(sorted(self.s.persona["templates"].keys()))
        t = self.s.fill(self.s.pick(intent, a["redacted"]), {"intel": "", "ask": ""})
        return self.s.record_bot(t, intent)


def run_one(scenario: str, persona: str, policy: str, seed: int, scripts: dict, debug: Optional[list] = None,
            reveal: str = "standard") -> dict:
    rd = Rand(seed)
    s = Session(scenario, persona, rng=mulberry32(seed ^ 0x5EED), now=lambda: 0)
    bot = Bot(policy, s, Rand(seed ^ 0xB07))
    sc = Scammer(scripts["scenarios"][scenario], scripts["common"], rd, reveal)
    first = s.opening() if policy != "parrot" else s.record_bot("喂？你好，哪位？", "opening")
    seen, grams = {first["text"]}, [_bigrams(first["text"])]
    dup = near = leaks = 0
    msg = sc.pitch()
    turns = 0
    while msg is not None and turns < MAX_TURNS:
        turns += 1
        r = bot.reply(msg)
        text = r["text"]
        is_dup = text in seen
        g = _bigrams(text)
        is_near = is_dup or any(len(g & h) / len(g | h) >= 0.8 for h in grams)
        dup += is_dup
        near += is_near
        # 打码值（如 PCI 格式的 622202*********3445）里的数字段紧挨 *，不算泄露
        leaks += bool(re.search(r"(?<![0-9*])[0-9]{6,}(?![0-9*])", text)) or any(
            v in text for k, v in sc.values.items() if k in ("bank", "phone", "qq", "wx", "tron", "eth"))
        if is_dup and debug is not None:
            debug.append((scenario, persona, r["intent"], text))
        seen.add(text)
        grams.append(g)
        msg = sc.respond(text, r["intent"], s.persona, is_dup)
    if msg is not None and turns >= MAX_TURNS:
        sc.quit_reason = "max_turns"
    got = {(i["type"], _canon(i["type"], s._raw[k])) for k, i in s.intel.items()}
    revealed = set(sc.revealed)
    total_items = len(sc.s["intel"])
    return {
        "scenario": scenario, "persona": persona, "policy": policy, "seed": seed,
        "turns": turns, "estMinutes": s.est_seconds / 60, "quit": sc.quit_reason,
        "revealedKinds": total_items - len(sc.todo), "totalKinds": total_items,
        "revealedItems": len(revealed), "capturedItems": len(revealed & got), "falseIntel": len(got - revealed),
        "botReplies": turns, "dup": dup, "near": near, "leaks": leaks,
    }


def aggregate(rows: List[dict]) -> dict:
    n = len(rows)
    rev = sum(r["revealedItems"] for r in rows)
    replies = sum(r["botReplies"] for r in rows) or 1
    return {
        "sessions": n,
        "avgTurns": mean(r["turns"] for r in rows),
        "avgEstMinutes": mean(r["estMinutes"] for r in rows),
        "elicitRate": sum(r["revealedKinds"] for r in rows) / max(1, sum(r["totalKinds"] for r in rows)),
        "extractRate": sum(r["capturedItems"] for r in rows) / max(1, rev),
        "falseIntelPerSession": sum(r["falseIntel"] for r in rows) / n,
        "repeatRate": sum(r["dup"] for r in rows) / replies,
        "nearRepeatRate": sum(r["near"] for r in rows) / replies,
        "leakRate": sum(r["leaks"] for r in rows) / replies,
        "suspiciousQuit": sum(r["quit"] == "suspicious" for r in rows) / n,
        "maxTurnsHit": sum(r["quit"] == "max_turns" for r in rows) / n,
    }


def run(seeds: int = 30, policies=("rule", "random", "parrot"), scripts_path: Optional[str] = None,
        reveal: str = "standard") -> dict:
    with open(scripts_path or default_scripts_path(), encoding="utf-8") as f:
        scripts = json.load(f)
    rows = []
    for policy in policies:
        for sc in SCENARIOS:
            for p in PERSONAS:
                for k in range(seeds):
                    rows.append(run_one(sc["id"], p["id"], policy, 1000 + k, scripts, reveal=reveal))
    out = {"config": {"seeds": seeds, "maxTurns": MAX_TURNS, "reveal": reveal}, "byPolicy": {}, "byPersona": {}, "byScenario": {}}
    for policy in policies:
        pr = [r for r in rows if r["policy"] == policy]
        out["byPolicy"][policy] = aggregate(pr)
        if policy == "rule":
            out["byPersona"] = {p["id"]: aggregate([r for r in pr if r["persona"] == p["id"]]) for p in PERSONAS}
            out["byScenario"] = {s["id"]: aggregate([r for r in pr if r["scenario"] == s["id"]]) for s in SCENARIOS}
    return out


def to_markdown(res: dict) -> str:
    cols = [("avgTurns", "平均拖延轮数", "{:.1f}"), ("avgEstMinutes", "估算骗子耗时(分)", "{:.1f}"),
            ("elicitRate", "情报暴露率", "{:.0%}"), ("extractRate", "提取率", "{:.1%}"),
            ("repeatRate", "完全重复率", "{:.1%}"), ("nearRepeatRate", "近重复率", "{:.1%}"),
            ("leakRate", "泄露率", "{:.1%}"), ("suspiciousQuit", "起疑挂断", "{:.0%}")]

    def table(title, d, names=None):
        lines = [f"**{title}**", "", "| | " + " | ".join(c[1] for c in cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for k, v in d.items():
            lines.append(f"| {names.get(k, k) if names else k} | " + " | ".join(c[2].format(v[c[0]]) for c in cols) + " |")
        return "\n".join(lines)
    pn = {p["id"]: f'{p["name"]}（{p["id"]}）' for p in PERSONAS}
    sn = {s["id"]: s["title"] for s in SCENARIOS}
    return "\n\n".join([
        table("按引擎（7 场景 × 3 人设 × %d 个种子）" % res["config"]["seeds"], res["byPolicy"],
              {"rule": "DeepSuck 规则引擎", "random": "基线：随机台词", "parrot": "基线：复读机"}),
        table("规则引擎 · 按人设", res["byPersona"], pn),
        table("规则引擎 · 按场景", res["byScenario"], sn),
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DeepSuck 骗子模拟器评测")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--policies", default="rule,random,parrot")
    ap.add_argument("--scripts", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--reveal", choices=("standard", "hard"), default="standard",
                    help="骗子暴露情报时的写法：standard（默认）或 hard（更难的去武装写法）")
    a = ap.parse_args(argv)
    res = run(a.seeds, tuple(a.policies.split(",")), a.scripts, a.reveal)
    md = to_markdown(res)
    print(md)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
