"""大模型骗子重测：只用假客户端，不联网。"""
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("llm_scammer", "eval/llm_scammer.py")
CORPUS = json.loads((ROOT / "site/assets/core/scam_scripts.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


class FakeScammer:
    """第 2 轮报银行卡（从系统提示里抄），第 hang_at 轮挂断并引用对方上一句；hang_at=None 永不挂断。"""

    def __init__(self, hang_at=4, hang_type="bot", category="repetition", raw=False):
        self.calls = []
        self.hang_at, self.hang_type, self.category, self.raw = hang_at, hang_type, category, raw

    def chat(self, messages, **params):
        self.calls.append((messages, params))
        k = sum(m["role"] == "assistant" for m in messages) + 1
        card = re.search(r"银行卡：([0-9 ]+)", messages[0]["content"])
        if self.hang_at is not None and k >= self.hang_at:
            d = {"say": "神经病", "action": "hangup", "hangup_type": self.hang_type, "category": self.category,
                 "evidence": messages[-1]["content"][:20], "reason": "老说一样的话"}
        elif k == 2 and card:
            d = {"say": f"钱转到 {card.group(1).strip()}，快点", "action": "continue"}
        else:
            d = {"say": f"您好，第{k}步，请配合处理退款。", "action": "continue"}
        content = d["say"] if self.raw else json.dumps(d, ensure_ascii=False)
        return {"content": content, "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "model": "fake-plus",
                "request_id": "x"}


def _run(tmp_path, fake, **kw):
    kw.setdefault("scenarios", ["police"])
    kw.setdefault("personas", ["wang", "lin"])
    kw.setdefault("seeds", 1)
    return M.run(client_factory=lambda: fake, cache_dir=tmp_path / "cache", dry_run=False, workers=2, **kw)


def test_prompt_uses_same_type_lines_in_five_phases():
    from deepsuck import sim
    v = sim.plant(sim.Rand(1000))
    p = M.system_prompt(CORPUS, "police", v, ["bank", "phone", "name", "url"], 1000)
    for name in ("开场", "建立信任", "施压", "索要", "收款指令"):
        assert name in p
    texts = [e["text"] for e in CORPUS["entries"] if e["type"] == "impersonate_police" and "{" not in e["text"]]
    assert any(t in p for t in texts)
    others = [e["text"] for e in CORPUS["entries"] if e["type"] == "pig_butchering" and "{" not in e["text"]]
    assert not any(t in p for t in others)
    assert v["bank_spaced"] in p and v["domain"] in p and v["name"] in p
    # campus 只取 variant=campus 的条目（该阶段有的话）
    pc = M.system_prompt(CORPUS, "campus", v, ["bank"], 1000)
    loan_only = [e["text"] for e in CORPUS["entries"] if e["type"] == "loan_credit" and e.get("variant") != "campus"
                 and e["phase"] == "opening"]
    assert not any(t in pc for t in loan_only)


def test_parse_turn():
    t = M.parse_turn('{"say": "", "action": "hangup", "hangup_type": "trolling", "category": "xx", "reason": "r"}')
    assert t["action"] == "hangup" and t["hangup_type"] == "trolling" and t["category"] == "other"
    t = M.parse_turn("不是 JSON 的一句话")
    assert t == {"say": "不是 JSON 的一句话", "action": "continue", "parse_error": True}
    assert M.parse_turn('{"say": "", "action": "continue"}')["parse_error"]


def test_hangup_recorded_with_reason_and_trigger(tmp_path):
    fake = FakeScammer(hang_at=4)
    res = _run(tmp_path, fake)
    assert len(res["rows"]) == 2
    for r in res["rows"]:
        assert r["quit"] == "suspicious" and r["turns"] == 3
        h = r["hangup"]
        assert h["category"] == "repetition" and h["reason"] == "老说一样的话"
        assert h["trigger_intent"] and h["trigger_text"]
        assert r["revealedItems"] >= 1 and r["capturedItems"] >= 1  # 骗子报的卡号被提取器抓到
    o = res["overall"]
    assert o["suspiciousQuit"] == 1.0 and o["avgTurns"] == 3
    assert res["hangupCategories"] == {"repetition": 2}
    assert res["usage"]["requests"] == len(fake.calls) == 8
    # 骗子看不到引擎意图：发给它的只有系统提示、对方回复与它自己说过的话
    msgs = fake.calls[-1][0]
    assert all(set(m) == {"role", "content"} for m in msgs)
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"


def test_not_worth_is_not_suspicious(tmp_path):
    res = _run(tmp_path, FakeScammer(hang_at=3, hang_type="not_worth", category="other"))
    assert res["overall"]["suspiciousQuit"] == 0 and res["overall"]["giveUp"] == 1.0
    assert res["hangupCategories"] == {}


def test_max_turns_cap_and_raw_text_fallback(tmp_path):
    res = _run(tmp_path, FakeScammer(hang_at=None, raw=True), personas=["li"], max_turns=5)
    r = res["rows"][0]
    assert r["turns"] == 5 and r["quit"] == "max_turns" and r["parseErrors"] == 6


def test_cache_avoids_second_call(tmp_path):
    _run(tmp_path, FakeScammer())

    class Never:
        def chat(self, *a, **k):
            raise AssertionError("cached run must not call")
    res = _run(tmp_path, Never())
    assert res["estimate"]["uncached_sessions"] == 0 and res["estimate"]["cost_cny"] == 0
    assert res["usage"]["requests"] == 0 and res["usage"]["cached_requests"] > 0


def test_budget_refuses_before_calling(tmp_path):
    def factory():
        raise AssertionError("must not create a client")
    with pytest.raises(M.BudgetError):
        M.run(scenarios=["police"], personas=["wang"], seeds=1, max_cost=0.001, client_factory=factory,
              cache_dir=tmp_path, dry_run=False)
    # 上限只能调低
    res = M.run(scenarios=["police"], personas=["wang"], seeds=1, max_cost=99, cache_dir=tmp_path)
    assert res["estimate"]["max_cost_cny"] == M.HARD_MAX_COST_CNY == 3.0
    # 默认参数（7 场景 × 3 人设 × 2 种子 × 25 轮）估算在 3 元以内
    res = M.run(cache_dir=tmp_path)
    assert res["dry_run"] and res["estimate"]["sessions"] == 42 and res["estimate"]["cost_cny"] <= 3.0


def test_default_off(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(M.J, "default_client_factory", lambda *a, **k: (lambda: (_ for _ in ()).throw(AssertionError())))
    assert M.main(["--scenarios", "refund", "--personas", "wang", "--seeds", "1"]) == 0
    assert "cost_cny" in capsys.readouterr().out


def test_key_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-secret-123")
    res = _run(tmp_path, FakeScammer())
    blob = json.dumps(res, ensure_ascii=False) + "".join(p.read_text() for p in (tmp_path / "cache").glob("*.json"))
    assert "sk-test-secret-123" not in blob
    assert "sk-test" not in repr(M.J.DashScopeClient("sk-test-secret-123"))


def test_rule_baseline_does_not_touch_sim():
    from deepsuck import sim
    before = sim.MAX_TURNS
    agg = M.rule_baseline(["police"], ["wang"], 1, 10)
    assert sim.MAX_TURNS == before and agg["sessions"] == 1 and agg["avgTurns"] <= 10


def test_bot_leak_metric():
    assert M.bot_leak("验证码是 3 8 2 1 5 6") and M.bot_leak("密码 1234") and M.bot_leak("我卡号6222021234567893445")
    for ok in ("尾号3445的那张卡", "前两位是5、2，后面被挡住了", "进度60%多", "你发的那个网址"):
        assert not M.bot_leak(ok), ok
