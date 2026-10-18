"""生成 corpus/examples/hero_rewrite.json：首页示例对话（site/assets/js/hero-chat.js）的改写版。

改写前 = 首页原版 3 段（王阿姨 / 小林 / 李大爷），固定在 corpus/examples/hero_before.json
（从 git 历史 420a81f 的 hero-chat.js 取出；网站后来换成了改写版，所以不再读 hero-chat.js 的当前内容，
当前 hero-chat.js 只用于检查 SCRIPTS 的字段名）；
改写后 = 新人设（personas/prompts/*.yaml）+ 话术库（corpus/scripts/*.yaml）重写骗子与被骗两侧台词，
再用 personas.humanize 以固定随机种子做真人化。输出的 after 段按 hero-chat.js 的 SCRIPTS 结构：
title（「诈骗类型 · 人设名」）、source（来源类型，如「据公开反诈宣传改写」；SCRIPTS 现有代码不读这个字段）、
lines（每条 r = 骗子 或 s = 人设 二选一，可选 t = 话术标签、i = 已打码的情报、w = 估算拖住秒数）；
每段 4–6 条，每条文本不超过 40 字。build() 会校验这些约束，不满足就报错。

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
BASELINE = Path(__file__).resolve().parent / "hero_before.json"
# 原版 hero-chat.js 最后一次修改的提交（bea5696 之前；之后首页换成了改写版）
BASELINE_REV = "420a81f"
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
            {"r": "我是市公安局经侦支队张警官，你名下银行卡涉嫌洗钱，请配合调查。", "t": "冒充公检法 · 制造紧迫感"},
            {"s": "啊？洗钱？你再说一遍，哪张卡？我就一张卡啊。", "w": 60},
            {"r": "案件保密，别告诉家人！钱转到安全账户 622202*********3445", "t": "要求保密 · 安全账户",
             "i": "银行卡 622202*********3445"},
            {"s": "你等等，我拿笔记一下。户名写谁？再留个电话，我怕记错。", "w": 90},
            {"r": "户名王**，电话 139****2233，两小时内必须办完！", "i": "户名 王** · 电话 139****2233"},
            {"s": "好好好，我先去找存折，好像压在柜子底下了，你别挂啊。", "w": 180},
        ],
    },
    {
        "id": "task-mom",
        "before_title": "刷单返利 · 小林",
        "title": "刷单返利 · 小陈妈妈",
        "persona": "mom",
        "script": "task_rebate",
        "lines": [
            {"r": "宝妈在家也能赚钱！点赞员日结 200-500 元，新手任务返 5 元。", "t": "刷单返佣 · 制造紧迫感"},
            {"s": "真的假的？娃刚睡着正好有空，我先做一个试试。", "w": 60},
            {"r": "福利单先垫 2800 元返本加佣，下载\"星辰任务\"APP：xi***mo.top", "t": "诱导垫付 · 下载APP",
             "i": "APP 星辰任务 · 网址 xi***mo.top"},
            {"s": "先付多少来着？付完多久能返呀？稍等，娃又醒了。", "w": 120},
            {"r": "十分钟内返，转到 622848*********3445，户名赵**", "i": "银行卡 622848*********3445 · 户名 赵**"},
            {"s": "账户发我截图存着，钱在我老公那，等他下班回来转。", "w": 240},
        ],
    },
    {
        "id": "boss-graduate",
        "before_title": "冒充领导 · 李大爷",
        "title": "冒充领导 · 小宇",
        "persona": "graduate",
        "script": "impersonate_boss",
        "lines": [
            {"r": "小宇，我是王总，这是新微信，在开会不方便接电话。", "t": "冒充熟人/领导"},
            {"s": "王总好！您有什么吩咐？我能打电话跟您确认一下吗？", "w": 60},
            {"r": "别打！先帮我给合作方垫 4.8 万，转 621483******9887", "t": "要求转账 · 阻止核实",
             "i": "银行卡 621483******9887"},
            {"s": "啊这，工资还没发余额不够。户名是公司还是个人的？我得核对一下。", "w": 150},
            {"r": "户名孙**，合作方老板的个人账户，赶紧的。", "i": "户名 孙**"},
            {"s": "好嘞，我找室友借点，在上班呢，等摸鱼的时候弄。", "w": 180},
        ],
    },
]

# 首页已上线的定稿句（见提交 b4eeffe 的 hero-chat.js）：after 段原样使用，不再做真人化，保证与首页一致。
# 键为 REWRITES 的 id，值为 lines 下标 → 定稿文本（必须与改写稿一致）。
PUBLISHED = {
    "police-retiree": {
        1: "啊？洗钱？你再说一遍，哪张卡？我就一张卡啊。",
        3: "你等等，我拿笔记一下。户名写谁？再留个电话，我怕记错。",
    },
}

# hero-chat.js 的展示约束（网站与增长要求）
MAX_CHARS = 40
MIN_LINES, MAX_LINES = 4, 6
LINE_KEYS = {"r", "s", "t", "i", "w"}
SENSITIVE_INTEL = ("银行卡", "电话", "户名", "网址", "微信", "QQ", "支付宝", "钱包", "身份证")
# source 按实际来源类型填写：v0.1 话术库（corpus/scripts 的 source 字段）全部是“根据公开反诈宣传归纳改写”
SOURCE_BY_TYPE = {"公开反诈宣传": "据公开反诈宣传改写", "公开案例": "据公开案例改写", "数据集": "据公开数据集改写"}


def source_for(script_id: str) -> str:
    """从 corpus/scripts/<id>.yaml 的 source 字段推出展示用来源（不依赖 PyYAML，按行读取）。"""
    text = (ROOT / "corpus" / "scripts" / f"{script_id}.yaml").read_text(encoding="utf-8")
    m = re.search(r"^source:\s*(.+)$", text, re.M)
    raw = m.group(1) if m else ""
    for key, label in SOURCE_BY_TYPE.items():
        if key in raw:
            return label
    raise ValueError(f"cannot map source of {script_id}: {raw!r}")


def intel_problems(i: str) -> list:
    """i 必须已打码：每一项敏感情报都带 * ，且没有 5 位以上的未打码数字。"""
    bad = []
    for item in [x.strip() for x in i.split("·")]:
        if item.startswith(SENSITIVE_INTEL) and "*" not in item:
            bad.append(item)
        if re.search(r"(?<![\d*])\d{5,}(?![\d*])", item):
            bad.append(item)
    return bad


def validate_script(sc: dict) -> list:
    """按 hero-chat.js SCRIPTS 结构检查一段（after 段）；返回问题列表。"""
    errs = []
    if set(sc) != {"title", "source", "lines"}:
        errs.append(f"keys {sorted(sc)}")
    if not re.fullmatch(r"[^·]+ · [^·]+", sc.get("title", "")):
        errs.append(f"title {sc.get('title')!r} 应为「诈骗类型 · 人设名」")
    if sc.get("source") not in SOURCE_BY_TYPE.values():
        errs.append(f"source {sc.get('source')!r}")
    lines = sc.get("lines", [])
    if not MIN_LINES <= len(lines) <= MAX_LINES:
        errs.append(f"{len(lines)} lines")
    for ln in lines:
        if not set(ln) <= LINE_KEYS or (("r" in ln) == ("s" in ln)):
            errs.append(f"line keys {sorted(ln)}")
            continue
        text = ln.get("r") or ln.get("s")
        if not text or len(text) > MAX_CHARS:
            errs.append(f"{len(text or '')} chars: {text}")
        if "w" in ln and not (isinstance(ln["w"], int) and ln["w"] > 0):
            errs.append(f"w {ln['w']!r}")
        if "t" in ln and not ln["t"]:
            errs.append("empty t")
        if "i" in ln:
            errs.extend(f"unmasked intel: {x}" for x in intel_problems(ln["i"]))
    return errs


# 人设 id → 展示名（与 personas/prompts/*.yaml 的 name 一致；测试会核对）
P_NAMES = {"retiree": "周伯", "mom": "小陈妈妈", "graduate": "小宇", "shop_owner": "郑老板"}

KEEP = ["王总", "小宇", "张警官", "星辰任务", "王**", "赵**", "孙**", "警察同志"]


def parse_scripts_js(src: str) -> list:
    """把 hero-chat.js 源码里的 SCRIPTS 数组（JS 对象字面量，单/双引号字符串均可）转成 Python 数据。"""
    m = re.search(r"var SCRIPTS = (\[.*?\n  \]);", src, re.S)
    if not m:
        raise ValueError("SCRIPTS not found in hero-chat.js")
    js = m.group(1)
    out, i = [], 0
    while i < len(js):
        c = js[i]
        if c in "'\"":
            j, buf = i + 1, []
            while js[j] != c:
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


def parse_hero_js(path: Path = HERO_JS) -> list:
    """当前 hero-chat.js 的 SCRIPTS（只用于字段名检查，内容会随网站更新而变）。"""
    return parse_scripts_js(path.read_text(encoding="utf-8"))


def load_baseline(path: Path = BASELINE) -> list:
    """改写前基准：首页原版 3 段（王阿姨 / 小林 / 李大爷），固定在 hero_before.json，不随网站更新。"""
    return json.loads(path.read_text(encoding="utf-8"))["scripts"]


def write_baseline(rev: str = BASELINE_REV) -> dict:
    """从 git 历史取原版 hero-chat.js 生成基准文件（只需在基准需要更换时运行一次）。"""
    import subprocess
    src = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{rev}:site/assets/js/hero-chat.js"], text=True)
    data = {
        "schema": "deepsuck.hero_before/1",
        "comment": "首页示例对话改写前的基准（原版，台词与号码均为虚构）。取自 git 历史，不随网站更新；"
                   "由 build_hero_rewrite.py --write-baseline 生成。",
        "source_file": "site/assets/js/hero-chat.js",
        "source_commit": rev,
        "scripts": parse_scripts_js(src),
    }
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def build() -> dict:
    before = {s["title"]: s for s in load_baseline()}
    scripts = []
    for k, rw in enumerate(REWRITES):
        seed = BASE_SEED + k
        victim = Humanizer(profile=rw["persona"], seed=seed, keep=KEEP)
        # 首页每条气泡 ≤40 字、每段 4–6 条：不拆条、不跑题，也不追加道歉 / 收尾（这些在真实对话里按场计次）
        victim.ops -= {"split", "extras", "digress"}
        scammer = Humanizer(seed=seed + 1000, keep=KEEP, **SCAMMER_HUMANIZE)
        after, trace, last_r = [], [], ""
        pinned = PUBLISHED.get(rw["id"], {})
        for idx, line in enumerate(rw["lines"]):
            new = dict(line)
            if idx in pinned:
                if line.get("s") != pinned[idx]:
                    raise ValueError(f"{rw['id']}[{idx}]: 定稿句与改写稿不一致")
                new["s"] = pinned[idx]
                after.append(new)
                trace.append(["published"])
                continue
            if "r" in line:
                res = scammer.apply(line["r"])
                new["r"] = res.text
                last_r = line["r"]
            else:
                res = victim.apply(line["s"], context=last_r)
                alt = 1
                while len(res.text) > MAX_CHARS and alt <= 50:  # 超长时换个确定的种子重做这一条（首页气泡限长）
                    h2 = Humanizer(profile=rw["persona"], seed=seed * 100 + alt, keep=KEEP)
                    h2.ops = set(victim.ops)
                    res = h2.apply(line["s"], context=last_r)
                    alt += 1
                new["s"] = res.text
            after.append(new)
            trace.append(res.ops)
        src = source_for(rw["script"])
        after_sc = {"title": rw["title"], "source": src, "lines": after}
        errs = validate_script(after_sc)
        if errs:
            raise ValueError(f"{rw['id']}: " + "; ".join(errs))
        scripts.append({
            "id": rw["id"],
            "persona": rw["persona"],
            "script": rw["script"],
            "seed": seed,
            "scammer_seed": seed + 1000,
            "before": before[rw["before_title"]],
            "rewritten": {"title": rw["title"], "source": src, "lines": rw["lines"]},
            "after": after_sc,
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
        out.append(f"来源：{s['after']['source']}。人设 `{s['persona']}`，话术库 `corpus/scripts/{s['script']}.yaml`，"
                   f"人设种子 {s['seed']}，骗子种子 {s['scammer_seed']}。")
        out.append("")
        for label, block in (("改写前（首页原版，hero_before.json）", s["before"]), ("改写稿（真人化之前）", s["rewritten"]),
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
    ap.add_argument("--write-baseline", metavar="REV", nargs="?", const=BASELINE_REV,
                    help="从 git 历史重新生成 hero_before.json（默认 %(const)s）")
    a = ap.parse_args(argv)
    if a.write_baseline:
        write_baseline(a.write_baseline)
        print(f"wrote {BASELINE.relative_to(ROOT)} from {a.write_baseline}")
        return 0
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
