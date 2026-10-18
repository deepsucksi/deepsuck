#!/usr/bin/env python3
"""断续句情报回归评测集（#8，LLM-free，固定种子可复现）。

王阿姨的断续句语音版上线后，骗子 / 对话双方都会出现：用「…」「...」「，」停顿，数字逐位读出（中文数字、阿拉伯数字、幺 / 两混读），
一个号码拆进相邻两三个回合，以及「尾号XXXX」这种只报后 4 位的说法。本评测集按这些写法生成虚构情报并逐回合送进 Session
（与 eval/noise_eval.py 的 C 部分同一入口：单回合提取 + 跨回合拼接），分类型统计召回与误报：

  - account：银行卡（62 开头、过 Luhn 的虚构卡号）；
  - phone：手机号、座机（区号 + 7/8 位）、400 热线；
  - wallet：USDT TRC20（T 开头 34 位 Base58）与 ETH（0x + 40 位十六进制）地址。

正例里提取到的“非真值”的账户 / 电话 / 钱包都计为误报；负例（王阿姨 voiceShots 里不含号码的断续句、只报尾号、验证码、
金额、时间、工号 / 订单号等）里提取到的任何账户 / 电话 / 钱包都计为误报。

用法：python eval/halting_eval.py [--impl 另一份 python/ 目录] [--seeds 30] [--json out.json]
noise_eval.py 会调用 run() 把结果写进 results-noise.json 的 halting 字段。Apache-2.0
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
CN = dict(zip("0123456789", "零一二三四五六七八九"))
CN_YAO = dict(CN, **{"1": "幺"})
GROUP = {"account": ("bank_card",), "phone": ("phone",), "wallet": ("crypto_tron", "crypto_eth")}
TYPE_GROUP = {t: g for g, ts in GROUP.items() for t in ts}
# 号码之间的停顿写法
PAUSES = ("…", "……", "...", "，", "…，", "... ", "，…")
LEAD_IN = ("", "…", "呃…", "嗯…", "那个…")
# 王阿姨式的断续句里不含号码的负例（personas.json wang.voiceShots 之外再补几条带数字但不是号码的）
NEG_HALTING = [
    "两…两千？不是…三千块，你说的",
    "明天…九…九点半，行不行",
    "验证码…三…五…七…九…二…一，我先不念了",
    "验证码是…零…二…一…五…六…八",
    "工号…八…八…六…六，是你吧",
    "订单号…2026…1018…3345，你查查",
    "房间号…三零幺…会议号…不知道",
    "我…六十…不是，五十八块买的",
    "一…一万？哪个网站…你发来，我先看看",
    "等…等十分钟…我找找",
    "二零二六年…十月…十八号那天",
    "第…第三单…要先垫三百",
    "开奖号码是03、15、22、23、35、47，特别号码是09",
    "开奖号码…零三…一五…二二…二三…三五…四七",
]
# 只报尾号：不管几种写法都不能当成完整号码
NEG_TAIL = [
    ["您尾号1234的卡涉嫌洗钱"],
    ["尾号…一…二…三…四…那张卡"],
    ["卡尾号是…1…2…3…4，对吧"],
    ["就是尾号三四四五…那张"],
    ["手机尾号…八…零…零…零…是你本人吗"],
    ["你那张卡…尾号", "一二三四…对，就那张"],
    ["尾号…幺…两…三…四", "…你记一下"],
    ["工行的…尾号…九…九…八…八"],
    ["我把验证码念给你…尾号1234的卡收到的…七…七…九…一…二…三"],
    ["卡号就…不念了…尾号…6…6…8…8"],
]


def luhn_fix(d):
    body = d[:-1]
    tot = 0
    for i, c in enumerate(reversed(body)):
        x = int(c) * (2 if i % 2 == 0 else 1)
        tot += x - 9 if x > 9 else x
    return body + str((10 - tot % 10) % 10)


def gen_card(rd):
    return luhn_fix("62" + "".join(str(rd.randrange(10)) for _ in range(17)))


def gen_mobile(rd):
    return "1" + rd.choice("3456789") + "".join(str(rd.randrange(10)) for _ in range(9))


def gen_landline(rd):
    area = rd.choice(["010", "021", "020", "022", "023", "025", "027", "028", "029", "0755", "0571", "0512", "0371", "0731"])
    n = 8 if len(area) == 3 else rd.choice((7, 8))
    return area, str(rd.randrange(2, 9)) + "".join(str(rd.randrange(10)) for _ in range(n - 1))


def gen_hotline(rd):
    return rd.choice(("400", "800")) + "".join(str(rd.randrange(10)) for _ in range(7))


def gen_tron(rd):
    return "T" + "".join(rd.choice(B58) for _ in range(33))


def gen_eth(rd):
    return "0x" + "".join(rd.choice("0123456789abcdef") for _ in range(40))


def sizes_card(d):
    return [4] * 4 + [len(d) - 16] if len(d) > 16 else [4] * 4


def chunk(s, sizes):
    out, i = [], 0
    for n in sizes:
        if i >= len(s):
            break
        out.append(s[i:i + n])
        i += n
    if i < len(s):
        out.append(s[i:])
    return [x for x in out if x]


def say_digits(s, rd, mode):
    """mode: arabic | cn | yao（幺 / 两混读）| mix（逐位随机阿拉伯 / 中文）"""
    if mode == "arabic":
        return s
    if mode == "cn":
        return "".join(CN[c] for c in s)
    if mode == "yao":
        return "".join({"1": "幺", "2": rd.choice("二两")}.get(c, CN[c]) for c in s)
    return "".join(c if rd.random() < 0.5 else CN_YAO[c] for c in s)


def halting(groups, rd, mode, pause=None):
    p = pause or rd.choice(PAUSES)
    return p.join(say_digits(g, rd, mode) for g in groups)


def per_digit(s, rd, mode, pause=None):
    return halting(list(s), rd, mode, pause)


def split_turns(parts, n, rd):
    """把分组列表拆进 n 个回合（每个回合至少一组）。"""
    cuts = sorted(rd.sample(range(1, len(parts)), n - 1))
    out, last = [], 0
    for c in cuts + [len(parts)]:
        out.append(parts[last:c])
        last = c
    return out


DIGIT_MODES = ("arabic", "cn", "yao", "mix")


def positive_cases(seeds):
    rd = random.Random(20261019)
    cases = []

    def add(group, style, turns, truth):
        cases.append({"group": group, "style": style, "turns": turns, "truth": truth})
    for _ in range(seeds):
        for mode in DIGIT_MODES:
            # ---- 账户：银行卡 ----
            card = gen_card(rd)
            T = [("bank_card", card)]
            add("account", f"分组停顿|{mode}", [f"卡号是{rd.choice(LEAD_IN)}{halting(chunk(card, sizes_card(card)), rd, mode)}，户名王某某"], T)
            add("account", f"逐位停顿|{mode}", [f"卡号{rd.choice(LEAD_IN)}{per_digit(card, rd, mode)}"], T)
            add("account", f"三点省略|{mode}", [f"银行卡…{halting(chunk(card, sizes_card(card)), rd, mode, rd.choice(('...', '... ', '…… ')))}…记好"], T)
            add("account", f"报完说尾号|{mode}", [f"卡号{halting(chunk(card, sizes_card(card)), rd, mode)}…尾号{say_digits(card[-4:], rd, mode)}，记住没"], T)
            g = chunk(card, sizes_card(card))
            for n in (2, 3):
                ts = split_turns(g, n, rd)
                turns = [("卡号是…" if i == 0 else rd.choice(("", "…", "嗯…", "然后…"))) + halting(t, rd, mode) + "…"
                         for i, t in enumerate(ts)]
                add("account", f"跨{n}回合|{mode}", turns, T)
            # ---- 电话：手机 / 座机 / 400 ----
            ph = gen_mobile(rd)
            T = [("phone", ph)]
            add("phone", f"手机分组停顿|{mode}", [f"电话{rd.choice(LEAD_IN)}{halting(chunk(ph, [3, 4, 4]), rd, mode)}，有事打我"], T)
            add("phone", f"手机逐位停顿|{mode}", [f"手机号是{rd.choice(LEAD_IN)}{per_digit(ph, rd, mode)}"], T)
            add("phone", f"手机报完说尾号|{mode}", [f"电话{halting(chunk(ph, [3, 4, 4]), rd, mode)}…尾号{say_digits(ph[-4:], rd, mode)}"], T)
            ts = split_turns(chunk(ph, [3, 4, 4]), 2, rd)
            add("phone", f"手机跨2回合|{mode}", ["电话是…" + halting(ts[0], rd, mode) + "…", rd.choice(("", "嗯…", "然后…")) + halting(ts[1], rd, mode)], T)
            area, sub = gen_landline(rd)
            T = [("phone", area + sub)]
            sg = chunk(sub, [4, 4] if len(sub) == 8 else [3, 4])
            add("phone", f"座机分组停顿|{mode}", [f"座机{rd.choice(LEAD_IN)}{halting([area] + sg, rd, mode)}，打这个"], T)
            add("phone", f"座机逐位停顿|{mode}", [f"办公室电话是…{per_digit(area + sub, rd, mode)}"], T)
            add("phone", f"座机区号横杠|{mode}", [f"固话{say_digits(area, rd, mode)}-{halting(sg, rd, mode)}"], T)
            add("phone", f"座机跨2回合|{mode}", [f"座机号码…{halting([area] + sg[:1], rd, mode)}…", rd.choice(("", "嗯…", "然后…")) + halting(sg[1:], rd, mode)], T)
            hl = gen_hotline(rd)
            add("phone", f"热线停顿|{mode}", [f"客服热线{halting(chunk(hl, [3, 3, 4]), rd, mode)}"], [("phone", hl)])
        # ---- 钱包：TRC20 / ETH（字母数字只按原样分段停顿；数字模式不适用）----
        for pause in ("…", "...", "，", "... ", "……"):
            tr = gen_tron(rd)
            add("wallet", f"TRC20分段|{pause.strip() or '空格'}", [f"USDT地址是…{pause.join(chunk(tr, [rd.choice((4, 5, 6)) for _ in range(9)]))}"], [("crypto_tron", tr)])
            et = gen_eth(rd)
            add("wallet", f"ETH分段|{pause.strip() or '空格'}", [f"ETH钱包…{pause.join(chunk(et, [rd.choice((6, 8, 10)) for _ in range(8)]))}"], [("crypto_eth", et)])
        tr = gen_tron(rd)
        add("wallet", "TRC20报完说尾号", [f"转到…{'…'.join(chunk(tr, [6] * 6))}…尾号{tr[-4:]}"], [("crypto_tron", tr)])
        et = gen_eth(rd)
        add("wallet", "ETH跨2回合", [f"ETH地址…{et[:20]}…", "嗯…" + et[20:]], [("crypto_eth", et)])
        tr = gen_tron(rd)
        add("wallet", "TRC20跨2回合", [f"USDT收款地址…{tr[:17]}…", "然后…" + tr[17:]], [("crypto_tron", tr)])
    return cases


def negative_cases():
    shots = json.loads((ROOT / "site" / "assets" / "core" / "personas.json").read_text(encoding="utf-8"))
    wang = next(p for p in shots["personas"] if p.get("id") == "wang")
    cases = [{"group": "neg", "style": "王阿姨voiceShots", "turns": [s["reply"]], "truth": []} for s in wang.get("voiceShots", [])]
    cases += [{"group": "neg", "style": "数字非号码", "turns": [t], "truth": []} for t in NEG_HALTING]
    cases += [{"group": "neg", "style": "只报尾号", "turns": t, "truth": []} for t in NEG_TAIL]
    # 王阿姨把骗子报过的号以“尾号XXXX”复述（语音线逐位读出），本身不能变成新号码
    cases += [{"group": "neg", "style": "复述尾号", "turns": [t], "truth": []} for t in (
        "尾号…八…零…零…零，是这个吧", "你说的…尾号零幺二五那张？", "那个号…尾号…3…4…4…5…我记下了",
        "尾号四五…不对…三四四五", "622202*********3445…是这张？尾号3445")]
    return cases


def run(Session, canon, seeds=30):
    """Session / canon 由调用方从被测实现导入（便于 --impl 对比）。返回 {byGroup, byStyle, negative, summary}。"""
    pos = positive_cases(seeds)
    neg = negative_cases()

    def got(turns):
        s = Session("refund", "wang", rng=lambda: 0.5, now=lambda: 0)
        for t in turns:
            s.ingest(t)
        return {(i["type"], canon(i["type"], s._raw[k])) for k, i in s.intel.items() if k in s._raw and i["type"] in TYPE_GROUP}

    by_group = {g: {"n": 0, "hit": 0, "falseItems": 0} for g in GROUP}
    by_style = {}
    misses = []
    for c in pos:
        truth = {(t, canon(t, v)) for t, v in c["truth"]}
        g = got(c["turns"])
        hit = len(truth & g)
        b = by_group[c["group"]]
        b["n"] += len(truth)
        b["hit"] += hit
        for t, _ in g - truth:
            by_group[TYPE_GROUP[t]]["falseItems"] += 1
        st = by_style.setdefault(c["group"] + "|" + c["style"], {"n": 0, "hit": 0, "falseItems": 0})
        st["n"] += len(truth)
        st["hit"] += hit
        st["falseItems"] += len(g - truth)
        if hit < len(truth) and len(misses) < 40:
            misses.append({"style": c["style"], "turns": c["turns"]})
    neg_false = {g: 0 for g in GROUP}
    neg_by = {}
    neg_hits = []
    for c in neg:
        g = got(c["turns"])
        for t, _ in g:
            neg_false[TYPE_GROUP[t]] += 1
        nb = neg_by.setdefault(c["style"], {"cases": 0, "falseItems": 0})
        nb["cases"] += 1
        nb["falseItems"] += len(g)
        if g:
            neg_hits.append({"style": c["style"], "turns": c["turns"], "types": sorted(t for t, _ in g)})
    for b in list(by_group.values()) + list(by_style.values()):
        b["recall"] = b["hit"] / max(1, b["n"])
    summary = {
        **{f"{g}Recall": by_group[g]["recall"] for g in GROUP},
        **{f"{g}FalseItems": by_group[g]["falseItems"] + neg_false[g] for g in GROUP},
        "recall": sum(b["hit"] for b in by_group.values()) / max(1, sum(b["n"] for b in by_group.values())),
        "items": sum(b["n"] for b in by_group.values()),
        "posCases": len(pos), "negCases": len(neg), "negFalseItems": sum(neg_false.values()),
        "falseItems": sum(b["falseItems"] for b in by_group.values()) + sum(neg_false.values()),
    }
    return {"seeds": seeds, "byGroup": by_group, "byStyle": by_style,
            "negative": {"cases": len(neg), "falseItems": neg_false, "byStyle": neg_by, "hits": neg_hits},
            "misses": misses, "summary": summary}


def to_markdown(r):
    sm = r["summary"]
    names = {"account": "账户（银行卡）", "phone": "电话（手机 / 座机 / 400）", "wallet": "钱包（TRC20 / ETH）"}
    lines = ["**F. 断续句评测集**（「…」「...」「，」停顿、逐位读、跨回合、尾号；%d 组正例 / %d 组负例）" % (sm["posCases"], sm["negCases"]), "",
             "| 类型 | 召回 | 误报（正例多出 + 负例） |", "|---|---|---|"]
    for g in GROUP:
        lines.append(f"| {names[g]} | {r['byGroup'][g]['recall']:.1%}（{r['byGroup'][g]['hit']}/{r['byGroup'][g]['n']}） | {sm[g + 'FalseItems']} |")
    lines += ["", "| 写法 | 召回 | 误报 |", "|---|---|---|"]
    for k, v in r["byStyle"].items():
        lines.append(f"| {k} | {v['recall']:.1%} | {v['falseItems']} |")
    lines += ["", "负例：" + "，".join(f"{k} {v['falseItems']}/{v['cases']}" for k, v in r["negative"]["byStyle"].items())]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", default=str(ROOT / "python"))
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--json")
    a = ap.parse_args()
    sys.path.insert(0, a.impl)
    from deepsuck import sim  # noqa: E402
    from deepsuck.engine import Session  # noqa: E402
    res = run(Session, sim._canon, a.seeds)
    print(to_markdown(res))
    print(json.dumps(res["summary"], ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
