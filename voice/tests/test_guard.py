import json

from voice import guard as G


def test_budget_reserve_charge_release_persist(tmp_path):
    t = [1_800_000_000.0]
    b = G.VoiceBudget(cap_cny=1.0, data_dir=str(tmp_path), clock=lambda: t[0])
    lim = G.Limits(max_minutes=5, max_turns=30)
    est = b.session_cost_cap(lim)
    assert 0.1 < est < 0.6
    t1 = b.reserve(est, "a"); t2 = b.reserve(est, "b")
    assert t1 and t2
    n = int(1.0 // est)
    others = [b.reserve(est, str(i)) for i in range(n - 2)]
    assert all(others)
    assert b.reserve(est, "x") is None  # 预占满了
    t1.asr(300); t1.tts(500); t1.llm(30000, 2000)
    assert abs(t1.spent - (300 * 0.00024 + 500 * 0.0001 + (30000 * 0.2 + 2000 * 0.8) / 1e6)) < 1e-9  # 默认 qwen3.7-flash 单价
    t1.close()
    for o in others:
        o.close()
    assert b.reserve(est, "y")  # 释放后有余量
    j = json.loads((tmp_path / "voice-budget.json").read_text())
    assert j["asr_sec"] == 300 and j["tts_chars"] == 500
    b2 = G.VoiceBudget(cap_cny=1.0, data_dir=str(tmp_path), clock=lambda: t[0])
    assert abs(b2.st["spent_cny"] - t1.spent) < 1e-6
    t[0] += 86400  # 跨天清零
    assert b2.status()["usedPct"] == 0


def test_budget_exhausted_and_ticket_over():
    b = G.VoiceBudget(cap_cny=0.01)
    tk = b.reserve(0.005)
    tk.asr(10)  # 0.0024
    assert not tk.over
    tk.tts(100)  # +0.01
    assert tk.over and b.exhausted()
    assert b.reserve(0.001) is None
    assert G.VoiceBudget(cap_cny=0).reserve(999) is not None  # 0 = 不限


def test_gate_concurrency_and_per_ip():
    t = [0.0]
    g = G.Gate(G.Limits(max_sessions=2, per_ip_per_hour=2, per_ip_per_day=3), clock=lambda: t[0])
    assert g.admit("1.1.1.1", "a") is None
    assert g.admit("2.2.2.2", "b") is None
    assert g.admit("3.3.3.3", "c")[0] == 503
    g.release("a"); g.release("b")
    assert g.admit("1.1.1.1", "d") is None; g.release("d")
    assert g.admit("1.1.1.1", "e")[0] == 429  # 每小时 2 次
    t[0] += 3601
    assert g.admit("1.1.1.1", "f") is None; g.release("f")
    t[0] += 3601
    assert "今日" in g.admit("1.1.1.1", "g")[1]


def test_end_reason():
    lim = G.Limits(max_minutes=1, max_turns=3, idle_seconds=20)
    b = G.VoiceBudget()
    kw = dict(limits=lim, ticket=None, budget=b)
    assert G.end_reason(started=0, last_heard=0, turns=0, now=10, **kw) is None
    assert G.end_reason(started=0, last_heard=0, turns=0, now=21, **kw) == "idle"
    assert G.end_reason(started=0, last_heard=50, turns=3, now=55, **kw) == "turns"
    assert G.end_reason(started=0, last_heard=59, turns=0, now=60, **kw) == "time"
    assert set(G.END_TEXT) == set(G.END_NOTE)
