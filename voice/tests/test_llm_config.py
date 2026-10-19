"""#40：语音大模型可配、思考默认关、单价按模型取。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "python"):
    sys.path.insert(0, str(p))

from voice import guard as G  # noqa: E402
from voice import llm_ab as AB  # noqa: E402


def test_default_model_and_price():
    assert G.DEFAULT_LLM_MODEL == "qwen3.8-flash"
    p = G.Prices.from_env(env={})
    assert p.llm_model == "qwen3.8-flash" and (p.llm_in_per_m, p.llm_out_per_m) == (0.8, 2.7)
    d = G.Prices()
    assert (d.llm_in_per_m, d.llm_out_per_m, d.llm_model) == (0.8, 2.7, "qwen3.8-flash")


def test_price_table_lookup():
    assert G.llm_price("qwen-plus") == (0.8, 2.0)
    assert G.llm_price("qwen3.8-flash") == (0.8, 2.7)
    assert G.llm_price("qwen3.7-flash-2026-07-15") == (0.2, 0.8)   # 快照按前缀
    assert G.llm_price("qwen-plus-2025-12-01") == (0.8, 2.0)
    assert G.llm_price("some-unknown") == (0.8, 2.7)               # 不认识按最贵算
    assert G.llm_price("x-model", env={"PRICE_LLM_TABLE": "x-model:1:3, bad"}) == (1.0, 3.0)


def test_proxy_price_only_for_same_model():
    prod = {"LLM_MODEL": "qwen-plus", "PRICE_LLM_IN_PER_M": "0.8", "PRICE_LLM_OUT_PER_M": "2",
            "DEEPSUCK_LLM_MODEL": "qwen3.7-flash"}
    p = G.Prices.from_env(env=prod)
    assert (p.llm_in_per_m, p.llm_out_per_m) == (0.2, 0.8)          # 代理单价不套到别的模型
    p = G.Prices.from_env(env=dict(prod, DEEPSUCK_LLM_MODEL="qwen-plus", PRICE_LLM_IN_PER_M="0.9"))
    assert p.llm_in_per_m == 0.9                                    # 同一模型时沿用
    p = G.Prices.from_env(env={"PRICE_LLM_IN_PER_M": "5"})            # LLM_MODEL 未设 = 代理默认 qwen-plus
    assert p.llm_in_per_m == 0.8                                    # 语音默认 qwen3.8-flash 查表，不套代理单价
    p = G.Prices.from_env(env=dict(prod, VOICE_PRICE_LLM_IN_PER_M="0.3", VOICE_PRICE_LLM_OUT_PER_M="1"))
    assert (p.llm_in_per_m, p.llm_out_per_m) == (0.3, 1.0)


def test_thinking_off_by_default():
    from voice.app import llm_settings_extra
    assert llm_settings_extra({}) == {"extra_body": {"enable_thinking": False}}
    assert llm_settings_extra({"DEEPSUCK_LLM_THINKING": "1"}) == {"extra_body": {"enable_thinking": True}}


def test_env_examples_agree():
    dep = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    assert "DEEPSUCK_LLM_MODEL=" + G.DEFAULT_LLM_MODEL in dep and "DEEPSUCK_LLM_THINKING=0" in dep
    assert "DEEPSUCK_LLM_MODEL=" + G.DEFAULT_LLM_MODEL in (ROOT / "voice" / ".env.example").read_text(encoding="utf-8")


def test_ab_metrics():
    sc = AB.scripts()
    assert len(sc) == 10 and sum(len(s["lines"]) for s in sc) == 57  # #4 每个场景开头加一句不带场景的话
    assert sum(len(s["lines"]) for s in AB.scripts(digit_probes=False)) == 50
    assert sum(len(s["lines"]) for s in AB.scripts(digit_probes=False, neutral_open=False)) == 43
    assert not any("{" in l for s in sc for l in s["lines"])
    assert AB.leaked("你在哪个平台呀", "") == ["平台"] and AB.leaked("哪个平台", "我在平台上") == []
    assert AB.style("嗯…请问您好！") == {"chars": 7, "ellipsis": True, "written": 2, "excl": 1}
    assert AB.percentile([1, 2, 3, 4], 50) == 2.5 and AB.percentile([], 90) is None
    rows = [{"reply": "嗯…", "leak_check": True, "leaked": [], "guarded": False, "style": AB.style("嗯…"),
             "ttft_ms": 100, "total_ms": 200, "in": 1000, "out": 10}]
    s = AB.summarize(rows, "qwen3.7-flash")
    assert s["cost_per_turn"] == round((1000 * 0.2 + 10 * 0.8) / 1e6, 6) and s["cost_per_call"] == round(s["cost_per_turn"] * 10, 5)
