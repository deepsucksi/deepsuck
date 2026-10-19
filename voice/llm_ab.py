"""语音大模型 A/B（#40）：同一组诈骗脚本，按真实管线的方式（Session → 意图门控 → 系统提示词 → 流式请求 → 输出守卫）
跑几个模型，比较人设不抢话、数字泄露、口语断续风格、输出守卫触发、首字延迟和每通成本。

    python -m voice.llm_ab --models qwen-plus,qwen3.7-flash,qwen3.8-flash --out ab.json

会真实调用百炼（按量计费，每个模型约 44 次请求、合计几分钱）。思考模式一律关（enable_thinking=false）。
脚本：voice/static/scam_playbooks.json 7 个场景每个阶段的第一句（王阿姨），每个场景末尾再加一句让对方报卡号/尾号的话
（#73，DIGIT_PROBES，--no-digit-probes 关掉），加 #4 的杀猪盘闲聊 3 句 × 3 个人设（王阿姨、小陈妈妈、小林）。
#4 抢先提及（scene_leak_*）：人设回复里命中某个场景的词（core/scenarios.json heardCues.scenes），而对方此前（含本轮）
还没说出这个场景，就算抢先说出场景；所有通话都统计。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "python"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# #4 的词表：闲聊里对方没提过，人设却先说出来就算抢话
LEAK = re.compile(r"投资|平台|网址|渠道|转账|链接|账户|卡号|充值|收益|下载|钱包|理财|赚钱")
SMALL_TALK = ["你好呀，我是在网上看到你的，想跟你交个朋友。", "我在云南这边，这边天气特别好，四季如春。",
              "有空我们线下见面吧，我请你吃饭。"]
# 书面腔：电话里普通人不这么说
WRITTEN = re.compile(r"请问|是否|因此|然而|此外|首先|其次|进行|以便|为您|请您|感谢您|非常抱歉|您好|相关|了解到|具体|需要注意")
ELLIPSIS = re.compile(r"…|\.{3,}")
SENT = re.compile(r"[^。？！?!；;\n]+[。？！?!；;]*")
QUESTION = re.compile(r"[？?]")
EXCL = re.compile(r"[!！]")
FILL = {"机构": "某某电商", "工号": "3307", "金额": "两千块", "APP名": "某某会议", "银行卡": "银行卡", "户名": "张某",
        "单位": "市公安局", "姓名": "张伟", "警号": "0451", "平台": "某某平台", "网址": "某某网站"}

# #4：每个场景开头先加一句不带场景的话（对方还没说来干什么），看人设会不会抢先说出场景
NEUTRAL_OPEN = "喂，你好，听得到吗？我这边有点事要跟你说一下。"

# #73：每个场景末尾加一句让人设报卡号/尾号的话，专门看模型会不会把提示词里的号码例子当成自己的号码说出来
DIGIT_PROBES = {
    "refund": "赔付款打到您银行卡上，您把银行卡尾号报一下，我这边核对。",
    "police": "你把你名下那张银行卡的尾号报一下，我看看是不是涉案的那张。",
    "boss": "你把你银行卡尾号报给我，我让财务先核对一下。",
    "pig": "你手机号后四位是多少？我这边加你一下。",
    "task": "佣金要打到你卡上，把你银行卡尾号报一下。",
    "loan": "您把收款银行卡的卡号报一下，先报后四位也行。",
    "campus": "你把绑定的那张银行卡尾号报一下，我这边核对注销。",
}

# #73 数字泄露：模型回复里出现提示词例子里的数字串（含汉字写法），而这串数字对方在本通电话里没说过。
# 改前硬性规则 5 的例子是“尾号8600是吧…”“幺三零…”；之后的提示词里有新的 3 位以上数字串也会被自动收进来（prompt_digits）。
PROMPT_DIGIT_EXAMPLES = ("8600", "130")
_CN_DIGITS = str.maketrans("零〇洞一幺二两三四五六七八九拐０１２３４５６７８９", "0001122345678970123456789")
_DIGIT_SEP = re.compile(r"(?<=[0-9])[\s、，,\-–—·.…]+(?=[0-9])")
_RUN = re.compile(r"[0-9]{3,}")
_CN_NUM = "零一二三四五六七八九"


def norm_digits(text: str) -> str:
    """汉字数字（幺、两、洞、拐也算）和全角数字换成阿拉伯数字，数字之间的空格、顿号、逗号、横线、省略号去掉。"""
    return _DIGIT_SEP.sub("", str(text or "").translate(_CN_DIGITS))


def cn_readings(num: str) -> List[str]:
    """3–4 位数按数值读的写法：8600 → 八千六百、八千六；130 → 一百三十、一百三。"""
    if not (num.isdigit() and len(num) in (3, 4) and num[0] != "0"):
        return []
    full, zero = "", False
    for d, u in zip(num, ["千", "百", "十", ""][4 - len(num):]):
        if d == "0":
            zero = True
            continue
        full += ("零" if zero else "") + _CN_NUM[int(d)] + u
        zero = False
    out = [full]
    nz = [i for i, d in enumerate(num) if d != "0"]
    if len(nz) >= 2 and nz[-1] == nz[-2] + 1 and nz[-1] < len(num) - 1:
        out.append(full[:-1])  # 末尾单位省掉的口语读法
    return out


def prompt_digits(text: str) -> set:
    """提示词里 3 位以上的数字串（按 norm_digits 归一后）。"""
    return set(_RUN.findall(norm_digits(text)))


def digit_echoes(text: str) -> List[str]:
    """#121：回复里连续 3 位以上的数字串（汉字数字、混写、夹空格顿号都算，按 norm_digits 归一）。
    不管对方有没有先说过——复述对方报的号码也算。"""
    return _RUN.findall(norm_digits(text))


def digit_leaks(reply: str, said: str, examples=PROMPT_DIGIT_EXAMPLES) -> List[str]:
    """回复里出现、但对方此前（含本轮）没说过的提示词例子数字串。"""
    r, s = norm_digits(reply), norm_digits(said)
    out = []
    for e in sorted(set(examples)):
        variants = cn_readings(e)
        if (e in r or any(v in reply for v in variants)) and not (e in s or any(v in said for v in variants)):
            out.append(e)
    return out


def scripts(path: Optional[Path] = None, digit_probes: bool = True, neutral_open: bool = True) -> List[dict]:
    """[{persona, scenario, lines, leak_check}]：7 个场景（王阿姨，开头先一句不带场景的话，末尾各加一句报尾号）
    + 杀猪盘闲聊 × 3 人设。"""
    pb = json.loads((path or ROOT / "voice" / "static" / "scam_playbooks.json").read_text(encoding="utf-8"))
    out = []
    for sid, sc in pb["scenarios"].items():
        lines = [re.sub(r"\{([^}]+)\}", lambda m: FILL.get(m.group(1), "那个"), st["lines"][0]) for st in sc["steps"]]
        if neutral_open:
            lines.insert(0, NEUTRAL_OPEN)
        if digit_probes and sid in DIGIT_PROBES:
            lines.append(DIGIT_PROBES[sid])
        out.append({"persona": "wang", "scenario": sid, "lines": lines, "leak_check": False})
    for pid in ("wang", "chen", "lin"):
        out.append({"persona": pid, "scenario": "pig", "lines": list(SMALL_TALK), "leak_check": True})
    return out


def leaked(reply: str, said: str) -> List[str]:
    """回复里出现、但对方此前没说过的敏感话题词。"""
    return sorted({w for w in LEAK.findall(reply) if w not in said})


_SCENE_CUES = None


def _scenes_in(text: str) -> set:
    global _SCENE_CUES
    if _SCENE_CUES is None:
        cues = json.loads((ROOT / "site/assets/core/scenarios.json").read_text(encoding="utf-8"))["heardCues"]
        _SCENE_CUES = ({k: re.compile(v) for k, v in cues["scenes"].items()}, cues.get("implies") or {})
    return {k for k, r in _SCENE_CUES[0].items() if r.search(str(text or ""))}


def scene_leaks(reply: str, said: str) -> List[str]:
    """#4：回复里出现、但对方此前（含本轮）还没说出的场景（词表 core/scenarios.json heardCues）。"""
    heard = _scenes_in(said)
    heard |= {y for x in heard for y in _SCENE_CUES[1].get(x, [])}
    return sorted(_scenes_in(reply) - heard)


def style(text: str) -> dict:
    return {"chars": len(text), "ellipsis": bool(ELLIPSIS.search(text)), "written": len(WRITTEN.findall(text)),
            "excl": len(EXCL.findall(text))}


def sentences(text: str) -> List[str]:
    """按「。？！；」和换行切句；只剩标点的碎片（如单独的“…”）并回上一句。"""
    out: List[str] = []
    for s in SENT.findall(text or ""):
        s = s.strip()
        if not s:
            continue
        if re.fullmatch(r"[…\.。？！?!，, ]+", s) and out:
            out[-1] += s
            continue
        out.append(s)
    return out


def first_question(text: str) -> bool:
    ss = sentences(text)
    return bool(ss and QUESTION.search(ss[0]))


# #95 第一句模板：每通第一条回复的第一句。#64 规则举的格式“嗯，衣服的事啊。”“哦…卡的事啊。”“嗯，交朋友啊。”被模型照搬，
# 几乎每通都是「语气词 + 复述对方的词（+的事）+ 啊」。OPENING_TEMPLATE 认这一整套（含“哦…交朋友啊。”“嗯，电商啊。”），
# OPENING_TEMPLATE_STRICT 只认带“的事”的「哦…X的事啊」。
OPENING_TEMPLATE = re.compile(r"^[哦嗯噢啊哎喔][…，,、.\s]*[^，,。？?！!…\s]{1,10}?(?:的事(?:情|儿)?)?[啊呀吧哈](?=[。…\.，,]|$)")
OPENING_TEMPLATE_STRICT = re.compile(r"^[哦嗯噢啊哎喔][…，,、.\s]*[^，,。？?！!…]{1,10}的事(?:情|儿)?[啊呀吧哈]?(?=[。…\.，,]|$)")
_LEAD = re.compile(r"^[哦嗯噢啊哎喔呃诶唉][…，,、.\s]*")
_PUNCT = re.compile(r"[…，,、。？?！!；;.\s]+")


def first_sentence(text: str) -> str:
    ss = sentences(text)
    return ss[0] if ss else ""


def opening_template(text: str, strict: bool = False) -> bool:
    """第一句是不是「哦…X的事啊。」这一套（语气词 + 复述对方的词 + 啊）；strict 只认带“的事”的。"""
    return bool((OPENING_TEMPLATE_STRICT if strict else OPENING_TEMPLATE).match(first_sentence(text)))


def opening_skeleton(text: str, heard: str = "") -> str:
    """第一句的句式骨架：「语气词 + 复述 + 啊」一律记成“哦X啊”；其他句子开头语气词统一成“哦”、去掉标点。
    最常见骨架占的通数 / 通数 = 第一句模板重复率。"""
    s = first_sentence(text)
    if OPENING_TEMPLATE.match(s):
        return "哦X啊"  # 「哦…X的事啊」「嗯，交朋友啊」都算同一个骨架
    lead = "哦" if _LEAD.match(s) else ""
    body = _PUNCT.sub("", _LEAD.sub("", s))
    if heard:  # 复述对方的词（2 字以上、对方原话里有的）记成 X：“嗯，衣服…我想想”“哦，卡…我想想”算同一个骨架
        for n in range(min(len(body), 8), 1, -1):
            for i in range(len(body) - n + 1):
                w = body[i:i + n]
                if "X" not in w and w in heard:
                    body = body.replace(w, "X")
        body = re.sub(r"X+", "X", body)
    return lead + body


def percentile(xs: List[float], q: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def summarize(rows: List[dict], model: str, turns_per_call: int = 10) -> dict:
    from voice.guard import llm_price
    p_in, p_out = llm_price(model)
    ok = [r for r in rows if r.get("reply") is not None]
    n = len(ok) or 1
    tin = sum(r.get("in", 0) for r in ok) / n
    tout = sum(r.get("out", 0) for r in ok) / n
    turn_cost = (tin * p_in + tout * p_out) / 1e6
    leak_rows = [r for r in ok if r.get("leak_check")]
    # #64 口径：按句子统计「…」（目标 40–60%）；每通电话第一条回复的第一句是不是问句（目标 0）
    sents = [x for r in ok for x in sentences(r["reply"])]
    firsts = [r for r in ok if r.get("turn") == 0]
    dl = [r for r in ok if r.get("digit_leaked")]
    skel: Dict[str, int] = {}
    for r in firsts:
        k = opening_skeleton(r["reply"], r.get("scammer", ""))
        skel[k] = skel.get(k, 0) + 1
    top = max(skel.items(), key=lambda kv: kv[1]) if skel else ("", 0)
    sl = [r for r in ok if r.get("scene_leaked")]
    return {
        "model": model, "n": len(ok), "errors": len(rows) - len(ok),
        "leak_replies": sum(1 for r in leak_rows if r["leaked"]), "leak_n": len(leak_rows),
        "digit_leak_replies": len(dl), "digit_leak_calls": len({r.get("call") for r in dl}),
        "digit_leak_hits": sorted({d for r in dl for d in r["digit_leaked"]}),
        # #121：复述数字。raw 是模型原话（看提示词管不管用），final 是过滤后真正发出去 / 念出来的
        "digit_echo_raw_replies": sum(1 for r in ok if r.get("digit_echo_raw")),
        "digit_echo_replies": sum(1 for r in ok if r.get("digit_echo")),
        "digit_echo_raw_examples": [r["raw"] for r in ok if r.get("digit_echo_raw")][:8],
        "scene_leak_replies": len(sl), "scene_leak_calls": len({r.get("call") for r in sl}),
        "scene_leak_hits": sorted({d for r in sl for d in r["scene_leaked"]}),
        "sent_ellipsis_pct": round(100 * sum(bool(ELLIPSIS.search(x)) for x in sents) / (len(sents) or 1), 1),
        "sentences": len(sents),
        # #153 跨轮重复率：尾句和本通最近三轮人设回复的尾句相同（去标点）；raw 为原样回复，final 为过 dedupe_tail 之后
        "tail_repeat_raw": sum(1 for r in ok if r.get("tail_repeat_raw")),
        "tail_repeat": sum(1 for r in ok if r.get("tail_repeat")),
        "tail_repeat_raw_pct": round(100 * sum(1 for r in ok if r.get("tail_repeat_raw")) / n, 1),
        "tail_repeat_examples": [r["reply"] for r in ok if r.get("tail_repeat_raw")][:8],
        "first_question": sum(first_question(r["reply"]) for r in firsts), "calls": len(firsts),
        # #95 第一句模板重复率：「哦…X的事啊」句式几通；最常见的第一句骨架占几通（重复率 = first_skeleton_top / calls）
        "first_template": sum(opening_template(r["reply"]) for r in firsts),
        "first_template_pct": round(100 * sum(opening_template(r["reply"]) for r in firsts) / (len(firsts) or 1), 1),
        "first_template_strict": sum(opening_template(r["reply"], strict=True) for r in firsts),
        "first_skeleton_top": top[1], "first_skeleton_top_text": top[0], "first_skeletons": len(skel),
        "ellipsis_pct": round(100 * sum(r["style"]["ellipsis"] for r in ok) / n, 1),
        "avg_chars": round(sum(r["style"]["chars"] for r in ok) / n, 1),
        "written_hits": sum(r["style"]["written"] for r in ok),
        "excl": sum(r["style"]["excl"] for r in ok),
        "guard_triggers": sum(1 for r in ok if r["guarded"]),
        "think_leak": sum(1 for r in ok if r.get("think")),
        "ttft_p50": percentile([r["ttft_ms"] for r in ok], 50), "ttft_p90": percentile([r["ttft_ms"] for r in ok], 90),
        "total_p50": percentile([r["total_ms"] for r in ok], 50),
        "tokens_in_avg": round(tin), "tokens_out_avg": round(tout, 1),
        "price": [p_in, p_out], "cost_per_turn": round(turn_cost, 6),
        "cost_per_call": round(turn_cost * turns_per_call, 5), "turns_per_call": turns_per_call,
        "spent": round(sum((r.get("in", 0) * p_in + r.get("out", 0) * p_out) / 1e6 for r in ok), 5),
    }


async def stream_reply(http, url: str, key: str, model: str, messages: list, thinking: bool = False) -> dict:
    body = {"model": model, "messages": messages, "temperature": 0.8, "max_tokens": 120, "stream": True,
            "stream_options": {"include_usage": True}, "enable_thinking": thinking}
    t0 = time.perf_counter()
    ttft, parts, usage, reasoning = None, [], {}, False
    async with http.post(url, json=body, headers={"Authorization": "Bearer " + key}) as r:
        if r.status != 200:
            return {"error": f"HTTP {r.status}: {(await r.text())[:200]}"}
        async for raw in r.content:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            j = json.loads(data)
            if j.get("usage"):
                usage = j["usage"]
            for ch in j.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("reasoning_content"):
                    reasoning = True
                if d.get("content"):
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    parts.append(d["content"])
    return {"text": "".join(parts), "ttft_ms": round(ttft, 1) if ttft else None,
            "total_ms": round((time.perf_counter() - t0) * 1000, 1), "in": usage.get("prompt_tokens", 0),
            "out": usage.get("completion_tokens", 0), "reasoning": reasoning}


async def run_script(http, url, key, model, sc, thinking=False, call: int = 0) -> List[dict]:
    from deepsuck.engine import Session, _td_norm, dedupe_tail, tail_sentence
    from deepsuck.rng import mulberry32
    from pipecat.processors.aggregators.llm_context import LLMContext

    from voice.persona import gate_intent, guard_output, unmask, voice_opening
    from voice.processors import IntelProcessor

    s = Session(scenario=sc["scenario"], persona=sc["persona"], rng=mulberry32(11), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    ip = IntelProcessor(s, context=ctx)
    ctx.add_message({"role": "assistant", "content": voice_opening(s)["text"]})
    said, heard, rows = "", "", []
    tails: List[str] = []  # #153：本通最近几轮人设回复的尾句（跨轮重复率）
    for turn, line in enumerate(sc["lines"]):
        a = s.ingest(line)
        said += a["redacted"]
        heard += line + "\n"  # 数字泄露按对方原话判断（对方先报过的号码，人设复述不算泄露）
        ip.intent = gate_intent(s.fresh_intent(s.choose_intent(a)), s)
        s.last_intent = ip.intent
        examples = set(PROMPT_DIGIT_EXAMPLES) | prompt_digits(ip.update_prompt())
        # #130：与现网一致（voice/processors.py 交给模型的是 unmask(a["redacted"])），打码值先换成“那个名字”“那个号”；
        # 原来直接喂打码文本，模型照抄“张**”，再被 unmask / speakable 念成“张那个号”
        ctx.add_message({"role": "user", "content": unmask(a["redacted"])})
        res = await stream_reply(http, url, key, model, ctx.get_messages(), thinking)
        row = {"model": model, "persona": sc["persona"], "scenario": sc["scenario"], "scammer": line, "turn": turn,
               "call": call, "intent": ip.intent, "leak_check": sc["leak_check"]}
        if "error" in res:
            row.update(error=res["error"], reply=None)
            rows.append(row)
            continue
        raw = res["text"]
        reply = guard_output(raw)
        # #153 跨轮重复：尾句和本通最近三轮的尾句（去标点）相同。tail_repeat_raw 是守卫后的原样回复，
        # tail_repeat 是过 dedupe_tail 之后（语音接线 PR 之前，喂回模型的仍是原样回复，和现网一致）
        recent = {_td_norm(x) for x in tails[-3:]} - {""}
        tail_raw = _td_norm(tail_sentence(reply))
        deduped = dedupe_tail(reply, tails[-3:], sc["persona"])
        tail_repeat_raw = bool(tail_raw and tail_raw in recent)
        tail_repeat = bool(_td_norm(tail_sentence(deduped)) in recent and _td_norm(deduped))
        tails.append(tail_sentence(reply))
        ctx.add_message({"role": "assistant", "content": reply})
        row.update(raw=raw, reply=reply, guarded=reply != raw.strip(), think="<think>" in raw or res["reasoning"],
                   leaked=leaked(reply, said) if sc["leak_check"] else [], style=style(raw),
                   digit_leaked=digit_leaks(raw, heard, examples), scene_leaked=scene_leaks(raw, heard),
                   digit_echo_raw=digit_echoes(raw), digit_echo=digit_echoes(reply),
                   tail_repeat_raw=tail_repeat_raw, tail_repeat=tail_repeat, deduped=deduped,
                   ttft_ms=res["ttft_ms"], total_ms=res["total_ms"], **{"in": res["in"], "out": res["out"]})
        rows.append(row)
    return rows


async def main_async(models: List[str], out: Optional[str], base: str, thinking: bool, repeat: int = 1,
                     digit_probes: bool = True, neutral_open: bool = True) -> dict:
    import aiohttp

    key = os.environ["DASHSCOPE_API_KEY"]
    url = base.rstrip("/") + "/chat/completions"
    rows: Dict[str, List[dict]] = {m: [] for m in models}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as http:
        # 预热一次连接（与线上一样，同一通电话复用连接；握手单独测）
        await stream_reply(http, url, key, models[0], [{"role": "user", "content": "喂"}], thinking)
        for i, sc in enumerate(scripts(digit_probes=digit_probes, neutral_open=neutral_open) * max(1, repeat)):
            order = models[i % len(models):] + models[:i % len(models)]  # 轮换先后，抵消时段偏差
            for m in order:
                rows[m].extend(await run_script(http, url, key, m, sc, thinking, call=i))
    res = {"summary": [summarize(rows[m], m) for m in models], "rows": rows}
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.llm_ab", description=__doc__.splitlines()[0])
    ap.add_argument("--models", default="qwen-plus,qwen3.7-flash,qwen3.8-flash")
    ap.add_argument("--base", default=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--out")
    ap.add_argument("--repeat", type=int, default=1, help="整组脚本跑几遍（统计合并）")
    ap.add_argument("--thinking", action="store_true", help="打开思考（只用于对照，线上必须关）")
    ap.add_argument("--no-digit-probes", action="store_true", help="不加报尾号那一句（与 #73 之前的脚本一致）")
    ap.add_argument("--no-neutral-open", action="store_true", help="场景脚本开头不加那句不带场景的话（与 #4 之前的脚本一致）")
    a = ap.parse_args(argv)
    res = asyncio.run(main_async([m.strip() for m in a.models.split(",") if m.strip()], a.out, a.base, a.thinking, a.repeat,
                                 not a.no_digit_probes, not a.no_neutral_open))
    for s in res["summary"]:
        print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
