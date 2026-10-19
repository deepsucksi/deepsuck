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
    res = _run(tmp_path, FakeScammer(hang_at=None, raw=True), personas=["zheng"], max_turns=5)
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
    # 默认参数（7 场景 × 4 人设 × 1 种子 × 25 轮）估算在 3 元以内；默认人设 = personas.json 的四位
    res = M.run(cache_dir=tmp_path)
    assert res["dry_run"] and res["estimate"]["sessions"] == 28 and res["estimate"]["cost_cny"] <= 3.0
    assert res["config"]["personas"] == ["wang", "chen", "lin", "zheng"]


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


# ---------------------------------------------------------------- #164：高压档、对照组、缓存计费
def test_fixed_prefix_is_identical_across_sessions():
    from deepsuck import sim
    for prof in M.PROFILES:
        fx = M.fixed_prompt(prof)
        a = M.system_prompt(CORPUS, "police", sim.plant(sim.Rand(1000)), ["bank"], 1000, prof)
        b = M.system_prompt(CORPUS, "pig", sim.plant(sim.Rand(1001)), ["url", "wallet"], 1001, prof)
        assert a.startswith(fx) and b.startswith(fx) and a != b
        assert len(fx) > 300   # 场景、收款信息都在固定前缀之后
    assert "suspicion" in M.fixed_prompt("hard") and "strikes" in M.fixed_prompt("hard") and "试探" in M.fixed_prompt("hard")
    assert "suspicion" not in M.fixed_prompt("default")
    assert M.params_for(M.MODEL, 1)["enable_thinking"] is False
    with pytest.raises(ValueError):
        M.fixed_prompt("nope")


def test_parse_hard_fields():
    t = M.parse_turn('{"say": "你在哪", "action": "continue", "suspicion": "12", "probe": 1, "strikes": 2}')
    assert t["suspicion"] == 10 and t["probe"] == 1 and t["strikes"] == 2
    t = M.parse_turn('{"say": "x", "action": "continue"}')
    assert "suspicion" not in t and "probe" not in t


class FakeHard:
    """hard 档假骗子：每轮打起疑分 = 轮次 × 3，第 3 轮挂断。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, **params):
        self.calls.append(messages)
        k = sum(m["role"] == "assistant" for m in messages) + 1
        d = {"say": f"第{k}步", "action": "continue", "suspicion": 3 * k, "probe": k % 2, "strikes": k - 1}
        if k >= 3:
            d.update({"action": "hangup", "hangup_type": "bot", "category": "template", "evidence": "", "reason": "r"})
        return {"content": json.dumps(d, ensure_ascii=False),
                "usage": {"prompt_tokens": 2000, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 1024}},
                "model": "qwen3.8-flash"}


def test_hard_profile_keeps_fields_in_history_and_meters_cache(tmp_path):
    fake = FakeHard()
    res = _run(tmp_path, fake, personas=["wang"], profile="hard")
    r = res["rows"][0]
    assert r["suspicion"] == [3, 6, 9] and r["probes"] == 2 and r["flaggedTurns"] == 1 and r["quit"] == "suspicious"
    hist = [json.loads(m["content"]) for m in fake.calls[-1] if m["role"] == "assistant"]
    assert hist[0] == {"say": "第1步", "action": "continue", "suspicion": 3, "probe": 1, "strikes": 0}
    assert fake.calls[-1][0]["content"].startswith(M.fixed_prompt("hard"))
    o = res["overall"]
    assert o["avgSuspicion"] == 6 and o["suspiciousQuitEarly"] == 1.0 and o["probesPerSession"] == 2
    u = res["usage"]
    assert u["cached_tokens"] == 3 * 1024 and u["cache_hit_rate"] == round(1024 / 2000, 4)
    assert u["cost_cny"] == pytest.approx(3 * M.J.cost_cny(2000, 30, 1024), abs=1e-6)
    assert res["config"]["profile"] == "hard" and res["config"]["enableThinking"] is False


def test_bad_and_stall_responders_are_deterministic_and_repetitive(tmp_path):
    b1, b2 = M.BadResponder(7), M.BadResponder(7)
    seq = [b1.reply(f"第{i}句话请马上转账") for i in range(10)]
    assert seq == [b2.reply(f"第{i}句话请马上转账") for i in range(10)]
    assert len(set(seq)) < len(seq) and any("第2句话请马上转账" in x for x in seq)  # 复读 + 原样复述
    st = M.StallResponder(3)
    s2 = [st.reply("x") for _ in range(12)]
    assert s2[:6] == s2[6:] and all(x in M.STALL_LINES for x in s2)
    res = _run(tmp_path, FakeScammer(hang_at=None), personas=["wang"], responder="bad", max_turns=6)
    r = res["rows"][0]
    assert r["responder"] == "bad" and all(m["intent"] == "bad" for m in r["transcript"][1:] if m["role"] == "bot")
    assert r["revealedItems"] >= 1 and r["capturedItems"] >= 1   # 情报提取照常
    with pytest.raises(ValueError):
        _run(tmp_path, FakeScammer(), responder="nope")


def test_cli_books_cached_tokens_and_budget_guard(tmp_path, monkeypatch):
    led = tmp_path / "l.csv"
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path / "c")
    fake = FakeHard()
    monkeypatch.setattr(M.J, "default_client_factory", lambda *a, **k: (lambda: fake))
    monkeypatch.setattr(M, "run", lambda *a, **k: M.__dict__["_orig_run"](*a, **{**k, "cache_dir": tmp_path / "c"}))
    rc = M.main(["--run", "--profile", "hard", "--personas", "wang", "--scenarios", "police", "--seeds", "1",
                 "--budget-tag", "t", "--ledger", str(led), "--no-rule-baseline"])
    assert rc == 0
    import csv
    rows = list(csv.DictReader(open(led, encoding="utf-8")))
    assert rows[-1]["cached_tokens"] == str(3 * 1024) and "profile=hard" in rows[-1]["note"]
    assert float(rows[-1]["cost_cny"]) == pytest.approx(3 * M.J.cost_cny(2000, 30, 1024), abs=1e-6)
    M.L.append("t", "x", "m", {"cost_cny": 10.0}, ledger=led)   # 总预算用完：拒绝运行，不建客户端
    assert M.main(["--run", "--profile", "hard", "--personas", "wang", "--scenarios", "police", "--seeds", "1",
                   "--budget-tag", "t", "--ledger", str(led)]) == 2


M.__dict__.setdefault("_orig_run", M.run)


def test_empty_reply_is_a_silent_turn_not_a_stall_turn(tmp_path, monkeypatch):
    """#164：人设回复为空串（例如尾句去重删空）时，这一轮算没回复：不计入拖延轮数，骗子看到“对方没有回复”。"""
    orig = M.Session.rule_reply
    n = {"k": 0}

    def rule_reply(self, *a, **k):
        r = orig(self, *a, **k)
        n["k"] += 1
        return dict(r, text="") if n["k"] in (2, 3) else r
    monkeypatch.setattr(M.Session, "rule_reply", rule_reply)
    fake = FakeScammer(hang_at=None)
    res = M.run(client_factory=lambda: fake, cache_dir=tmp_path / "cache", dry_run=False, workers=1,
                scenarios=["police"], personas=["wang"], seeds=1, max_turns=6, humanize=False)
    row = res["rows"][0]
    assert row["turns"] == 6 and row["silentTurns"] == 2 and row["botReplies"] == 6
    last = fake.calls[-1][0]
    assert sum(m["role"] == "user" and m["content"] == M.SILENT_MARK for m in last) == 2
    assert all(m["content"] for m in last)  # 空串不会发给模型


def test_redact_text_masks_required_types_only():
    from deepsuck import sim as SIM
    v = SIM.plant(SIM.Rand(1000))
    t = (f"钱转到 {v['bank_spaced']}，户名{v['name']}，微信{v['wx']} QQ {v['qq']} 身份证110101199003071234 "
         f"电话{v['phone']} 网址 https://{v['domain']} 钱包 {v['tron']} 支付宝 abc@example.com 卡号{v['bank']}")
    r = M.redact_text(t, v)
    for x in (v["bank_spaced"], v["bank"], v["name"], v["wx"], v["qq"], "110101199003071234", "abc@example.com"):
        assert x not in r
    for x in (v["phone"], v["domain"], v["tron"]):
        assert x in r
    assert M.redact_text("名字叫" + v["name"], v).count(v["name"]) == 0  # 没有上下文也按植入值兜底


def test_json_transcripts_are_redacted(tmp_path, monkeypatch):
    fake = FakeScammer(hang_at=4)
    out = tmp_path / "r.json"
    monkeypatch.setattr(M.J, "default_client_factory", lambda *a, **k: (lambda: fake))
    real_run = M.run
    monkeypatch.setattr(M, "run", lambda *a, **k: real_run(*a, cache_dir=tmp_path / "cache", **k))  # 不碰仓库里的真缓存
    assert M.main(["--run", "--scenarios", "police", "--personas", "wang", "--no-rule-baseline", "--json", str(out),
                   "--json-transcripts"]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    tr = d["rows"][0]["transcript"]
    assert tr[0]["role"] == "bot" and "raw" in tr[0] and any(m["role"] == "scammer" for m in tr)
    from deepsuck import sim as SIM
    v = SIM.plant(SIM.Rand(1000))
    assert v["bank"] not in out.read_text(encoding="utf-8").replace(" ", "")
    assert "transcriptFormat" in d
