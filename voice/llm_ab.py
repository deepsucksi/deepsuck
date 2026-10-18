"""语音大模型 A/B（#40）：同一组诈骗脚本，按真实管线的方式（Session → 意图门控 → 系统提示词 → 流式请求 → 输出守卫）
跑几个模型，比较人设不抢话、口语断续风格、输出守卫触发、首字延迟和每通成本。

    python -m voice.llm_ab --models qwen-plus,qwen3.7-flash,qwen3.8-flash --out ab.json

会真实调用百炼（按量计费，每个模型约 44 次请求、合计几分钱）。思考模式一律关（enable_thinking=false）。
脚本：voice/static/scam_playbooks.json 7 个场景每个阶段的第一句（王阿姨），加 #4 的杀猪盘闲聊 3 句 × 3 个人设。
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
EXCL = re.compile(r"[!！]")
FILL = {"机构": "某某电商", "工号": "3307", "金额": "两千块", "APP名": "某某会议", "银行卡": "银行卡", "户名": "张某",
        "单位": "市公安局", "姓名": "张伟", "警号": "0451", "平台": "某某平台", "网址": "某某网站"}


def scripts(path: Optional[Path] = None) -> List[dict]:
    """[{persona, scenario, lines, leak_check}]：7 个场景（王阿姨）+ 杀猪盘闲聊 × 3 人设。"""
    pb = json.loads((path or ROOT / "voice" / "static" / "scam_playbooks.json").read_text(encoding="utf-8"))
    out = []
    for sid, sc in pb["scenarios"].items():
        lines = [re.sub(r"\{([^}]+)\}", lambda m: FILL.get(m.group(1), "那个"), st["lines"][0]) for st in sc["steps"]]
        out.append({"persona": "wang", "scenario": sid, "lines": lines, "leak_check": False})
    for pid in ("wang", "li", "lin"):
        out.append({"persona": pid, "scenario": "pig", "lines": list(SMALL_TALK), "leak_check": True})
    return out


def leaked(reply: str, said: str) -> List[str]:
    """回复里出现、但对方此前没说过的敏感话题词。"""
    return sorted({w for w in LEAK.findall(reply) if w not in said})


def style(text: str) -> dict:
    return {"chars": len(text), "ellipsis": bool(ELLIPSIS.search(text)), "written": len(WRITTEN.findall(text)),
            "excl": len(EXCL.findall(text))}


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
    return {
        "model": model, "n": len(ok), "errors": len(rows) - len(ok),
        "leak_replies": sum(1 for r in leak_rows if r["leaked"]), "leak_n": len(leak_rows),
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


async def run_script(http, url, key, model, sc, thinking=False) -> List[dict]:
    from deepsuck.engine import Session
    from deepsuck.rng import mulberry32
    from pipecat.processors.aggregators.llm_context import LLMContext

    from voice.persona import gate_intent, guard_output, voice_opening
    from voice.processors import IntelProcessor

    s = Session(scenario=sc["scenario"], persona=sc["persona"], rng=mulberry32(11), now=lambda: 0)
    ctx = LLMContext([{"role": "system", "content": "x"}])
    ip = IntelProcessor(s, context=ctx)
    ctx.add_message({"role": "assistant", "content": voice_opening(s)["text"]})
    said, rows = "", []
    for line in sc["lines"]:
        a = s.ingest(line)
        said += a["redacted"]
        ip.intent = gate_intent(s.fresh_intent(s.choose_intent(a)), s)
        s.last_intent = ip.intent
        ip.update_prompt()
        ctx.add_message({"role": "user", "content": a["redacted"]})
        res = await stream_reply(http, url, key, model, ctx.get_messages(), thinking)
        row = {"model": model, "persona": sc["persona"], "scenario": sc["scenario"], "scammer": line,
               "intent": ip.intent, "leak_check": sc["leak_check"]}
        if "error" in res:
            row.update(error=res["error"], reply=None)
            rows.append(row)
            continue
        raw = res["text"]
        reply = guard_output(raw)
        ctx.add_message({"role": "assistant", "content": reply})
        row.update(raw=raw, reply=reply, guarded=reply != raw.strip(), think="<think>" in raw or res["reasoning"],
                   leaked=leaked(reply, said) if sc["leak_check"] else [], style=style(raw),
                   ttft_ms=res["ttft_ms"], total_ms=res["total_ms"], **{"in": res["in"], "out": res["out"]})
        rows.append(row)
    return rows


async def main_async(models: List[str], out: Optional[str], base: str, thinking: bool) -> dict:
    import aiohttp

    key = os.environ["DASHSCOPE_API_KEY"]
    url = base.rstrip("/") + "/chat/completions"
    rows: Dict[str, List[dict]] = {m: [] for m in models}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as http:
        # 预热一次连接（与线上一样，同一通电话复用连接；握手单独测）
        await stream_reply(http, url, key, models[0], [{"role": "user", "content": "喂"}], thinking)
        for i, sc in enumerate(scripts()):
            order = models[i % len(models):] + models[:i % len(models)]  # 轮换先后，抵消时段偏差
            for m in order:
                rows[m].extend(await run_script(http, url, key, m, sc, thinking))
    res = {"summary": [summarize(rows[m], m) for m in models], "rows": rows}
    if out:
        Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.llm_ab", description=__doc__.splitlines()[0])
    ap.add_argument("--models", default="qwen-plus,qwen3.7-flash,qwen3.8-flash")
    ap.add_argument("--base", default=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--out")
    ap.add_argument("--thinking", action="store_true", help="打开思考（只用于对照，线上必须关）")
    a = ap.parse_args(argv)
    res = asyncio.run(main_async([m.strip() for m in a.models.split(",") if m.strip()], a.out, a.base, a.thinking))
    for s in res["summary"]:
        print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
