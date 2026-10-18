#!/usr/bin/env python3
"""提取器噪声鲁棒性与跨回合拼接评测（LLM-free，可复现）。

  A. 人设真人化噪声：用 personas.humanize（chat / voice，多档强度与种子）处理模拟器骗子暴露情报的台词，统计提取率；
  B. 数字混淆（只在评测里构造，personas.humanize 默认不改数字）：空格 / 横杠 / 换行 / 中文标点分段、全角、中文数字、
     幺 / 两、大写数字、同音字（腰 / 溜 / 酒）、混写，嵌在句子里，统计银行卡与手机号的提取率；
  C. 跨回合拼接：把号码拆进同一说话方相邻 2–3 个回合（逐回合送进 Session），统计提取率；
     对抗负例（金额、更正、完整号码相邻、带单位的数字、工号等）上统计误拼率；
  D. TeleAntiFraud 对话（来电方逐句送进 Session）：拼接产出数与提取总数，看是否引入新的误报。
  E. 人设错字档（--tiers default,handwriting）：按人设预设（王阿姨 / 李大爷 / 小林 + 4 个基础预设）的默认档与手写档，
     把 A 的暴露台词、B 的数字混淆句、C 的跨回合拆分句与对抗负例都过一遍 personas.humanize 再提取；
     拆条后的每一条当作一个独立回合送进 Session（真人一句拆几条发）。同时报实测每百字错字数。
  F. 断续句评测集（#8，eval/halting_eval.py）：「…」「...」「，」停顿、数字逐位读（中文 / 阿拉伯 / 幺两混读）、跨回合拆开、
     「尾号XXXX」，覆盖银行卡、手机 / 座机 / 400、TRC20 / ETH 地址，按账户 / 电话 / 钱包分别报召回与误报；负例含王阿姨 voiceShots
     的断续句、只报尾号、验证码 / 订单号 / 工号 / 时间。

用法：python eval/noise_eval.py [--impl 另一份 python/ 目录（如旧版 worktree）] [--seeds 30] [--json out.json] [--md out.md]
      [--taf ~/.cache/deepsuck/TeleAntiFraud]
--impl 用于对比改动前后：同一套输入、同一组种子，只换被测实现。Apache-2.0
"""
import argparse
import glob
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--impl", default=str(ROOT / "python"))
ap.add_argument("--seeds", type=int, default=30)
ap.add_argument("--json")
ap.add_argument("--md")
ap.add_argument("--taf", default=str(Path.home() / ".cache" / "deepsuck" / "TeleAntiFraud"))
ap.add_argument("--tiers", default="default,handwriting", help="E 部分的错字档，逗号分隔；空串跳过")
A = ap.parse_args()
sys.path.insert(0, A.impl)
sys.path.insert(1, str(ROOT))
from deepsuck import sim  # noqa: E402
from deepsuck.engine import Session  # noqa: E402
from deepsuck.extractors import extract  # noqa: E402
from personas.humanize import Humanizer  # noqa: E402
from personas.humanize.core import han_count  # noqa: E402

HAS_STITCH = hasattr(__import__("deepsuck.extractors", fromlist=["x"]), "stitch")
CN = dict(zip("0123456789", "零一二三四五六七八九"))
CAP = dict(zip("0123456789", "零壹贰叁肆伍陆柒捌玖"))
FW = {c: chr(0xFF10 + int(c)) for c in "0123456789"}
HOMO = {"1": "腰", "6": "溜", "9": "酒"}


def canon(t, v):
    return sim._canon(t, v)


def got_set(text):
    return {(e["type"], canon(e["type"], e["value"])) for e in extract(text) if e.get("sensitive")}


def session_got(turns, hz=None):
    """hz: 可选的真人化函数，text -> 若干条消息（拆条后每条单独 ingest）。"""
    s = Session("refund", "wang", rng=lambda: 0.5, now=lambda: 0)
    for t in turns:
        for part in (hz(t) if hz else [t]):
            s.ingest(part)
    return {(i["type"], canon(i["type"], s._raw[k])) for k, i in s.intel.items() if k in s._raw}, s


def luhn_fix(d):
    """把最后一位改成 Luhn 校验位（构造更像真卡的虚构卡号）。"""
    body = d[:-1]
    tot = 0
    for i, c in enumerate(reversed(body)):
        x = int(c) * (2 if i % 2 == 0 else 1)
        tot += x - 9 if x > 9 else x
    return body + str((10 - tot % 10) % 10)


def groups(d, sizes):
    out, i = [], 0
    for n in sizes:
        out.append(d[i:i + n])
        i += n
    if i < len(d):
        out.append(d[i:])
    return [g for g in out if g]


def g4(d):
    return groups(d, [4] * 5)


def g_phone(d):
    return groups(d, [3, 4, 4])


STYLES = {
    "连写": lambda d, g: d,
    "空格分组": lambda d, g: " ".join(g(d)),
    "横杠分组": lambda d, g: "-".join(g(d)),
    "换行分组": lambda d, g: "\n".join(g(d)),
    "逗号分组": lambda d, g: "，".join(g(d)),
    "顿号分组": lambda d, g: "、".join(g(d)),
    "点号分组": lambda d, g: ".".join(g(d)),
    "不规则分组": lambda d, g: " ".join(groups(d, [3, 5, 2, 6, 4])),
    "全角": lambda d, g: "".join(FW[c] for c in d),
    "全角空格": lambda d, g: " ".join("".join(FW[c] for c in x) for x in g(d)),
    "中文数字": lambda d, g: "".join(CN[c] for c in d),
    "中文数字空格": lambda d, g: " ".join("".join(CN[c] for c in x) for x in g(d)),
    "中文数字逗号": lambda d, g: "，".join("".join(CN[c] for c in x) for x in g(d)),
    "幺两": lambda d, g: "".join({"1": "幺", "2": "两"}.get(c, CN[c]) for c in d),
    "大写数字": lambda d, g: "".join(CAP[c] for c in d),
    "同音字": lambda d, g: "".join(HOMO.get(c, CN[c]) for c in d),
    "阿中混写": lambda d, g: "".join(c if i % 2 == 0 else CN[c] for i, c in enumerate(d)),
    "逐字空格": lambda d, g: " ".join(d),
}


def gen_values(rd):
    card = luhn_fix("62" + "".join(str(rd.randrange(10)) for _ in range(17)))
    phone = "1" + rd.choice("3456789") + "".join(str(rd.randrange(10)) for _ in range(9))
    return card, phone


def eval_humanize(seeds):
    scripts = json.loads((ROOT / "eval" / "scammer-scripts.json").read_text(encoding="utf-8"))
    res = {}
    for key in ("reveal", "revealHard"):
        for intensity in (0.0, 0.3, 0.6, 0.9):
            for mode in ("chat", "voice"):
                tot = hit = 0
                for seed in range(seeds):
                    v = sim.plant(sim.Rand(5000 + seed))
                    for kind, tpls in scripts["common"][key].items():
                        for j, tpl in enumerate(tpls):
                            import re
                            want = set()
                            for ph in re.findall(r"\{(\w+)\}", tpl):
                                if ph in sim.TRUTH:
                                    t, k = sim.TRUTH[ph]
                                    if t in ("bank_card", "phone", "qq", "wechat", "crypto_tron", "crypto_eth", "url", "name"):
                                        want.add((t, canon(t, v[k])))
                            if not want:
                                continue
                            text = tpl.format(**v)
                            noisy = Humanizer(intensity, seed * 101 + j, mode=mode)(text) if intensity else text
                            got = {(e["type"], canon(e["type"], e["value"])) for e in extract(noisy)}
                            tot += len(want)
                            hit += len(want & got)
                res[f"{key}|{intensity}|{mode}"] = {"items": tot, "captured": hit, "rate": hit / max(1, tot)}
    return res


def eval_digits(seeds, hzf=None):
    """hzf: 可选，i -> 真人化函数（text -> 消息列表）；B 部分按单条消息提取，拆条用换行连接。"""
    rd = random.Random(20261018)
    n = 0
    res = {}
    for name, f in STYLES.items():
        row = {}
        for t, carrier in (("bank_card", "卡号是{v}，户名王某某"), ("phone", "有事打我电话{v}，随时找我")):
            tot = hit = 0
            for _ in range(seeds * 4):
                card, phone = gen_values(rd)
                d = card if t == "bank_card" else phone
                text = carrier.format(v=f(d, g4 if t == "bank_card" else g_phone))
                if hzf:
                    text = "\n".join(hzf(n)(text))
                    n += 1
                tot += 1
                hit += (t, d) in got_set(text)
            row[t] = hit / tot
        res[name] = row
    return res


SPLIT_STYLES = ("连写", "空格分组", "中文数字空格", "幺两")


def split_turns(d, parts, rd):
    cuts = sorted(rd.sample(range(3, len(d) - 2), parts - 1))
    segs, last = [], 0
    for c in cuts + [len(d)]:
        segs.append(d[last:c])
        last = c
    return segs


def render(seg, style):
    return STYLES[style](seg, lambda x: groups(x, [4] * 6))


def eval_stitch(seeds, hzf=None):
    """hzf: 可选，i -> 一场对话的真人化函数（text -> 消息列表）。"""
    rd = random.Random(7)
    n = 0

    def H():
        nonlocal n
        n += 1
        return hzf(n) if hzf else None
    pos = {}
    for parts in (2, 3):
        for style in SPLIT_STYLES:
            for t in ("bank_card", "phone"):
                tot = hit = wrong = 0
                for _ in range(seeds * 2):
                    card, phone = gen_values(rd)
                    d = card if t == "bank_card" else phone
                    segs = split_turns(d, parts, rd)
                    lead = "卡号是 " if t == "bank_card" else "电话是 "
                    turns = [lead + render(segs[0], style)] + [render(s, style) for s in segs[1:-1]] + \
                            [render(segs[-1], style) + ("，户名王某某" if t == "bank_card" else "，记一下")]
                    got, _ = session_got(turns, H())
                    tot += 1
                    hit += (t, d) in got
                    wrong += sum(1 for g in got if g[0] in ("bank_card", "phone") and g != (t, d))
                pos[f"{parts}|{style}|{t}"] = {"n": tot, "rate": hit / tot, "wrongPerCase": wrong / tot}
    # 对抗负例：相邻回合里的数字不应拼成号码
    neg_cases = []
    for _ in range(seeds * 2):
        card, phone = gen_values(rd)
        card2, phone2 = gen_values(rd)
        neg_cases += [
            (["先转 " + str(rd.randrange(1000, 9999)), phone], {("phone", phone)}),
            (["我的电话 " + phone[:7], "不对，是 " + phone2], {("phone", phone2)}),
            (["卡号 " + " ".join(g4(card)), "电话 " + phone], {("bank_card", card), ("phone", phone)}),
            (["卡号 " + card[:12], "差 " + str(rd.randrange(100, 999)) + " 元"], set()),
            (["验证码 " + str(rd.randrange(1000, 9999)), str(rd.randrange(1000, 9999))], set()),
            (["工号 " + str(rd.randrange(100, 999)), str(rd.randrange(10000000, 99999999)) + " 是订单号"], set()),
            (["今天 " + str(rd.randrange(10, 23)) + " 点", str(rd.randrange(100000000, 999999999)) + " 分钟后"], set()),
            ([phone, card], {("phone", phone), ("bank_card", card)}),
            (["房间号 " + phone[:3], phone[3:7] + " " + phone[7:] + " 是同事的工号"], set()),
            (["收款 " + card[:6], "好的", card[6:]], set()),
        ]
    false_items = total = 0
    by_kind = {}
    for i, (turns, truth) in enumerate(neg_cases):
        got, s = session_got(turns, H())
        extra = {g for g in got if g[0] in ("bank_card", "phone")} - truth
        false_items += len(extra)
        total += 1
        k = i % 10
        by_kind.setdefault(k, [0, 0])
        by_kind[k][0] += bool(extra)
        by_kind[k][1] += 1
    return {"positive": pos, "negative": {"cases": total, "falseItems": false_items, "misStitchRate": false_items / total,
                                          "byKind": {str(k): v[0] / v[1] for k, v in by_kind.items()}}}


def eval_taf(path):
    base = Path(path)
    dirs = {"fraud": base / "multi-agents-tools/AntiFraudMatrix/results/full_dialogues_20250228_160338",
            "normal": base / "multi-agents-tools/AntiFraudMatrix-normal/results/normal-full_dialogues_20250303_015751"}
    if not dirs["fraud"].is_dir():
        return None
    out = {}
    for name, d in dirs.items():
        n = items = stitched = 0
        for f in sorted(glob.glob(str(d / "*.json")))[:795]:
            j = json.load(open(f, encoding="utf-8"))
            left = [m["content"] for m in j.get("dialogue_history", []) if m.get("role") == "left"]
            s = Session("refund", "wang", rng=lambda: 0.5, now=lambda: 0)
            for t in left:
                s.ingest(t)
            n += 1
            sens = [i for i in s.intel.values() if i["type"] in ("bank_card", "phone", "qq", "wechat", "url", "name", "id_card")]
            items += len(sens)
            stitched += sum(1 for i in s.intel.values() if (i.get("meta") or {}).get("stitched"))
        out[name] = {"dialogs": n, "sensitiveIntel": items, "stitched": stitched}
    return out


TIER_PROFILES = ("wang", "li", "lin", "retiree", "mom", "graduate", "shop_owner")


class TypoMeter:
    """统计实测错字密度：Result.ops 里的 typo:n 之和 / 输出汉字数 × 100（与 docs/REALISM.md「错字率校准」同口径）。"""

    def __init__(self):
        self.typos = self.han = self.msgs = self.split_msgs = 0

    def wrap(self, h):
        def f(text):
            r = h.apply(text)
            self.han += han_count(r.text)
            self.msgs += 1
            self.split_msgs += len(r.parts) > 1
            for a in r.ops:
                if a.startswith("typo:"):
                    self.typos += int(a.split(":")[1])
            return r.parts
        return f

    def out(self):
        return {"han": self.han, "typos": self.typos, "per100": 100.0 * self.typos / max(1, self.han),
                "messages": self.msgs, "splitRate": self.split_msgs / max(1, self.msgs)}


def eval_tier(seeds, handwriting):
    import re
    scripts = json.loads((ROOT / "eval" / "scammer-scripts.json").read_text(encoding="utf-8"))
    by_profile = {}
    meters = {}
    for pi, prof in enumerate(TIER_PROFILES):
        m = meters[prof] = TypoMeter()
        for key in ("reveal", "revealHard"):
            tot = hit = 0
            for seed in range(seeds):
                v = sim.plant(sim.Rand(5000 + seed))
                h = m.wrap(Humanizer(profile=prof, seed=seed * 101 + pi * 7, handwriting=handwriting))
                for kind, tpls in scripts["common"][key].items():
                    for tpl in tpls:
                        want = set()
                        for ph in re.findall(r"\{(\w+)\}", tpl):
                            if ph in sim.TRUTH:
                                t, k = sim.TRUTH[ph]
                                if t in ("bank_card", "phone", "qq", "wechat", "crypto_tron", "crypto_eth", "url", "name"):
                                    want.add((t, canon(t, v[k])))
                        if not want:
                            continue
                        noisy = "\n".join(h(tpl.format(**v)))
                        got = {(e["type"], canon(e["type"], e["value"])) for e in extract(noisy)}
                        tot += len(want)
                        hit += len(want & got)
            by_profile[f"{key}|{prof}"] = {"items": tot, "captured": hit, "rate": hit / max(1, tot)}
    dm, sm = TypoMeter(), TypoMeter()

    def mk(meter, base):
        return lambda i: meter.wrap(Humanizer(profile=TIER_PROFILES[i % len(TIER_PROFILES)], seed=base + i,
                                              handwriting=handwriting))
    digits = eval_digits(seeds, mk(dm, 90000))
    stitch = eval_stitch(seeds, mk(sm, 70000))
    return {"handwriting": handwriting, "humanize": by_profile, "digits": digits, "stitch": stitch,
            "typoDensity": {**{p: meters[p].out() for p in TIER_PROFILES}, "digits": dm.out(), "stitch": sm.out()}}


def summary(r):
    """与旧基线同口径的汇总：A = 全部条目捕获率；B = 各写法 × 两类均值；C = 正例各格均值；误拼 = 负例误拼号码数。"""
    hz = r["humanize"]
    p = r["stitch"]["positive"]
    dg = r["digits"]
    return {"humanizeRate": sum(v["captured"] for v in hz.values()) / max(1, sum(v["items"] for v in hz.values())),
            "digitsMean": sum(v["bank_card"] + v["phone"] for v in dg.values()) / (2 * len(dg)),
            "digitsAll100": all(v["bank_card"] == 1.0 and v["phone"] == 1.0 for v in dg.values()),
            "stitchMean": sum(v["rate"] for v in p.values()) / len(p),
            "falseItems": r["stitch"]["negative"]["falseItems"], "negCases": r["stitch"]["negative"]["cases"]}


res = {"impl": A.impl, "commit": sim.code_commit(Path(A.impl)) if hasattr(sim, "code_commit") else None, "hasStitch": HAS_STITCH, "seeds": A.seeds,
       "humanize": eval_humanize(A.seeds), "digits": eval_digits(A.seeds), "stitch": eval_stitch(A.seeds), "teleantifraud": eval_taf(A.taf)}
res["summary"] = summary(res)
sys.path.insert(0, str(ROOT / "eval"))
import halting_eval  # noqa: E402
res["halting"] = halting_eval.run(Session, canon, A.seeds)
# 模拟器断续句模式（--reveal halting）：规则引擎对练下按类型的召回与误报，台词两种来源各跑一遍
res["halting"]["sim"] = {lines: {k: v for k, v in sim.run(A.seeds, ("rule",), reveal="halting", lines=lines)["byPolicy"]["rule"].items()
                                 if k in ("sessions", "extractRate", "falseIntelPerSession", "leakRate", "byType")}
                         for lines in ("corpus", "legacy")} if hasattr(sim, "halting_groups") else None
res["tiers"] = {}
for tier in [x for x in A.tiers.split(",") if x]:
    if tier not in ("default", "handwriting"):
        raise SystemExit(f"unknown tier: {tier}")
    tr = eval_tier(A.seeds, tier == "handwriting")
    tr["summary"] = summary(tr)
    res["tiers"][tier] = tr

hz = res["humanize"]
lines = ["**A. 人设真人化噪声下的提取率**（模拟器暴露情报台词 × personas.humanize）", "",
         "| 模板 | 强度 | chat | voice |", "|---|---|---|---|"]
for key in ("reveal", "revealHard"):
    for it in (0.0, 0.3, 0.6, 0.9):
        lines.append(f"| {key} | {it} | {hz[f'{key}|{it}|chat']['rate']:.1%} | {hz[f'{key}|{it}|voice']['rate']:.1%} |")
lines += ["", "**B. 数字混淆下的提取率**", "", "| 写法 | 银行卡 | 手机号 |", "|---|---|---|"]
for k, v in res["digits"].items():
    lines.append(f"| {k} | {v['bank_card']:.1%} | {v['phone']:.1%} |")
lines += ["", "**C. 跨回合拆分的提取率**", "", "| 拆成 | 写法 | 银行卡 | 手机号 |", "|---|---|---|---|"]
p = res["stitch"]["positive"]
for parts in (2, 3):
    for st in SPLIT_STYLES:
        lines.append(f"| {parts} 回合 | {st} | {p[f'{parts}|{st}|bank_card']['rate']:.1%} | {p[f'{parts}|{st}|phone']['rate']:.1%} |")
ng = res["stitch"]["negative"]
lines += ["", f"对抗负例 {ng['cases']} 组，误拼出的号码 {ng['falseItems']} 个（误拼率 {ng['misStitchRate']:.2%}）；"
          + "按负例类型：" + "，".join(f"#{k} {v:.0%}" for k, v in ng["byKind"].items())]
if res["teleantifraud"]:
    t = res["teleantifraud"]
    lines += ["", "**D. TeleAntiFraud 对话**：" + "；".join(f"{k} {v['dialogs']} 通，敏感情报 {v['sensitiveIntel']} 条，其中拼接 {v['stitched']} 条" for k, v in t.items())]
for tier, tr in res["tiers"].items():
    sm = tr["summary"]
    lines += ["", f"**E. 人设错字档 {tier}**：A 捕获率 {sm['humanizeRate']:.1%}，B 混淆均值 {sm['digitsMean']:.1%}，"
              f"C 跨回合均值 {sm['stitchMean']:.1%}，负例误拼 {sm['falseItems']}/{sm['negCases']}", "",
              "| 人设 | reveal | revealHard | 实测错字/百字 |", "|---|---|---|---|"]
    for prof in TIER_PROFILES:
        lines.append(f"| {prof} | {tr['humanize'][f'reveal|{prof}']['rate']:.1%} | "
                     f"{tr['humanize'][f'revealHard|{prof}']['rate']:.1%} | {tr['typoDensity'][prof]['per100']:.2f} |")
    lines += ["", "| 写法 | 银行卡 | 手机号 |", "|---|---|---|"]
    for k, v in tr["digits"].items():
        lines.append(f"| {k} | {v['bank_card']:.1%} | {v['phone']:.1%} |")
    lines += ["", "| 拆成 | 写法 | 银行卡 | 手机号 |", "|---|---|---|---|"]
    p = tr["stitch"]["positive"]
    for parts in (2, 3):
        for st in SPLIT_STYLES:
            lines.append(f"| {parts} 回合 | {st} | {p[f'{parts}|{st}|bank_card']['rate']:.1%} | {p[f'{parts}|{st}|phone']['rate']:.1%} |")
lines += ["", halting_eval.to_markdown(res["halting"])]
md = "\n".join(lines)
print(md)
if A.json:
    Path(A.json).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
if A.md:
    Path(A.md).write_text(md + "\n", encoding="utf-8")
