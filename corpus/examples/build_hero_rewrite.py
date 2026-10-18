"""生成 corpus/examples/hero_rewrite.json：首页示例对话（site/assets/js/hero-chat.js）的改写版。

改写前 = hero-chat.js 里现有的 3 段 SCRIPTS（只读解析，不改 site/）；
改写后 = 新人设（personas/prompts/*.yaml）+ 话术库（corpus/scripts/*.yaml）重写骗子与被骗两侧台词，
再用 personas.humanize 以固定随机种子做真人化。输出的 after 段与 hero-chat.js 的 SCRIPTS 同格式
（r = 骗子，s = 人设，t = 话术标签，i = 已打码的情报，w = 估算拖住秒数），可直接替换。

    python corpus/examples/build_hero_rewrite.py            # 重新生成 JSON
    python corpus/examples/build_hero_rewrite.py --md       # 打印 docs/REALISM.md 对比章节用的 Markdown
    python corpus/examples/build_hero_rewrite.py --check    # 只检查 JSON 是否最新（CI 用）

情报值沿用 hero-chat.js 原有的虚构打码值（如 622202*********3445），不新增任何号码。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personas.humanize import Humanizer  # noqa: E402

HERO_JS = ROOT / "site" / "assets" / "js" / "hero-chat.js"
OUT = Path(__file__).resolve().parent / "hero_rewrite.json"
BASE_SEED = 20261018

# 骗子一侧只做轻度错别字：话术照“剧本”复制粘贴，标点通常整齐（乱加 ~ 会削弱施压语气），偶尔手打有错字
SCAMMER_HUMANIZE = {"intensity": 0.3, "mode": "chat", "ops": ["typo"], "weights": {"typo": 0.6}}

# 改写稿（真人化之前）。骗子侧依据 corpus/scripts 的阶段台词改写，人设侧依据 personas/prompts 的拖延与诱导手法。
REWRITES = [
    {
        "id": "police-retiree",
        "before_title": "冒充公检法 · 王阿姨",
        "title": "冒充公检法 · 周伯",
        "persona": "retiree",
        "script": "impersonate_police",
        "lines": [
            {"r": "我是市公安局经侦支队的张警官，你名下一张银行卡涉嫌洗钱，现在需要你配合调查。",
             "t": "冒充公检法 · 制造紧迫感"},
            {"s": "啊？警察同志你慢点说，我这耳朵不好使。洗钱？我就一张领退休金的卡啊。", "w": 60},
            {"r": "案件处于保密阶段，不要告诉家人。把资金转到国家安全账户 622202*********3445，户名王**，查清后原路退回。",
             "t": "要求保密 · 安全账户", "i": "银行卡 622202*********3445 · 户名 王**"},
            {"s": "你等会儿啊，我找一下老花镜，把这个账户抄在本子上。户名是姓王是吧？你再留个电话，我这手机老是断。", "w": 90},
            {"r": "打 139****2233，两个小时之内必须办完，快点！", "i": "电话 139****2233"},
            {"s": "好好好，我先去找存折，好像压在柜子最底下了，你别挂啊。", "w": 180},
        ],
    },
    {
        "id": "task-mom",
        "before_title": "刷单返利 · 小林",
        "title": "刷单返利 · 小陈妈妈",
        "persona": "mom",
        "script": "task_rebate",
        "lines": [
            {"r": "宝妈在家也能赚钱！招线上点赞员，动动手指日结 200-500 元，先做新手任务，返 5 元马上到账。",
             "t": "刷单返佣 · 制造紧迫感"},
            {"s": "真的假的？我娃刚睡着，正好有空，那我先做一个试试。", "w": 60},
            {"r": "新手任务奖励到了吧？下一单是福利单，先垫付 2800 元，本金加佣金一起返。任务在\"星辰任务\"APP 上做：xi***mo.top",
             "t": "诱导垫付 · 下载APP", "i": "APP 星辰任务 · 网址 xi***mo.top"},
            {"s": "先付多少来着？付完多久能返回来呀？稍等，娃又醒了。", "w": 120},
            {"r": "十分钟内返，转到 622848*********3445，户名赵**", "i": "银行卡 622848*********3445"},
            {"s": "你把账户发我，我截图存着。钱在我老公那里，等他下班回来我让他转。", "w": 240},
        ],
    },
    {
        "id": "boss-graduate",
        "before_title": "冒充领导 · 李大爷",
        "title": "冒充领导 · 小宇",
        "persona": "graduate",
        "script": "impersonate_boss",
        "lines": [
            {"r": "小宇，我是王总，这是我新的微信，在开会不方便接电话。", "t": "冒充熟人/领导"},
            {"s": "王总好！我刚入职没多久，您有什么吩咐？我能打个电话跟您确认一下吗？", "w": 60},
            {"r": "别打，会议室不能接电话。合作方的款要急着付，你先帮我垫 4.8 万，转 621483******9887",
             "t": "要求转账 · 阻止核实", "i": "银行卡 621483******9887"},
            {"s": "啊这，我卡里余额不够，工资还没发。户名是公司的还是个人的？我得跟财务一样核对一下。", "w": 150},
            {"r": "户名孙**，是合作方老板的个人账户，赶紧的。", "i": "户名 孙**"},
            {"s": "好嘞，我先找室友借一点，您稍等哈，我这边在上班，等摸鱼的时候弄。", "w": 180},
        ],
    },
]

KEEP = ["王总", "小宇", "张警官", "星辰任务", "王**", "赵**", "孙**"]


def parse_hero_js(path: Path = HERO_JS) -> list:
    """把 hero-chat.js 的 SCRIPTS 数组（JS 对象字面量，单引号字符串）转成 Python 数据。"""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"var SCRIPTS = (\[.*?\n  \]);", src, re.S)
    if not m:
        raise ValueError("SCRIPTS not found in hero-chat.js")
    js = m.group(1)
    out, i = [], 0
    while i < len(js):
        c = js[i]
        if c == "'":
            j, buf = i + 1, []
            while js[j] != "'":
                if js[j] == "\\":
                    j += 1
                buf.append(js[j])
                j += 1
            out.append(json.dumps("".join(buf), ensure_ascii=False))
            i = j + 1
        else:
            out.append(c)
            i += 1
    text = "".join(out)
    text = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def build() -> dict:
    before = {s["title"]: s for s in parse_hero_js()}
    scripts = []
    for k, rw in enumerate(REWRITES):
        seed = BASE_SEED + k
        victim = Humanizer(profile=rw["persona"], seed=seed, keep=KEEP)
        scammer = Humanizer(seed=seed + 1000, keep=KEEP, **SCAMMER_HUMANIZE)
        after, trace, last_r = [], [], ""
        for line in rw["lines"]:
            new = dict(line)
            if "r" in line:
                res = scammer.apply(line["r"])
                new["r"] = res.text
                last_r = line["r"]
            else:
                res = victim.apply(line["s"], context=last_r)
                new["s"] = res.text
            after.append(new)
            trace.append(res.ops)
        scripts.append({
            "id": rw["id"],
            "persona": rw["persona"],
            "script": rw["script"],
            "seed": seed,
            "scammer_seed": seed + 1000,
            "before": before[rw["before_title"]],
            "rewritten": {"title": rw["title"], "lines": rw["lines"]},
            "after": {"title": rw["title"], "lines": after},
            "ops": trace,
        })
    return {
        "schema": "deepsuck.hero_rewrite/1",
        "comment": "首页示例对话改写对比；全部台词与号码为虚构，号码沿用 hero-chat.js 的打码值。由 corpus/examples/build_hero_rewrite.py 生成，勿手改。",
        "generator": {"base_seed": BASE_SEED, "victim_humanize": "personas/humanize/profiles.py 中对应人设的预设",
                      "scammer_humanize": SCAMMER_HUMANIZE},
        "scripts": scripts,
    }


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _md_lines(lines):
    rows = []
    for ln in lines:
        who, text = ("骗子", ln["r"]) if "r" in ln else ("人设", ln["s"])
        extra = []
        if ln.get("t"):
            extra.append(f"话术：{ln['t']}")
        if ln.get("i"):
            extra.append(f"情报：{ln['i']}")
        if ln.get("w"):
            extra.append(f"拖住约 {ln['w']} 秒")
        rows.append(f"| {who} | {text} | {'；'.join(extra)} |")
    return rows


def markdown(data: dict) -> str:
    out = []
    for n, s in enumerate(data["scripts"], 1):
        out.append(f"### {n}. {s['before']['title']} → {s['after']['title']}")
        out.append("")
        out.append(f"人设 `{s['persona']}`，话术库 `corpus/scripts/{s['script']}.yaml`，"
                   f"人设种子 {s['seed']}，骗子种子 {s['scammer_seed']}。")
        out.append("")
        for label, block in (("改写前（hero-chat.js 现有）", s["before"]), ("改写稿（真人化之前）", s["rewritten"]),
                             ("改写后（真人化）", s["after"])):
            out.append(f"**{label}**")
            out.append("")
            out.append("| 说话方 | 台词 | 标注 |")
            out.append("|---|---|---|")
            out.extend(_md_lines(block["lines"]))
            out.append("")
        ops = [", ".join(o) or "（无）" for o in s["ops"]]
        out.append("真人化实际生效的操作（逐行）：" + " / ".join(ops))
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    data = build()
    if a.md:
        print(markdown(data))
        return 0
    text = dump(data)
    if a.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("hero_rewrite.json is up to date" if ok else "hero_rewrite.json is stale; rerun the builder")
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
