"""secrecy / loan_stall 拖延句池回归：池大小下限、在拖延轮换链上、近期去重、模拟器指标阈值。"""
import re

from deepsuck import sim
from deepsuck.engine import Session
from deepsuck.personas import PERSONAS

POOLS = ("secrecy", "loan_stall")
MIN_POOL = 12


def _texts(lst):
    return [it if isinstance(it, str) else it["t"] for it in lst]


def test_pool_sizes_distinct_and_clean():
    for p in PERSONAS:
        for k in POOLS:
            t = _texts(p["templates"][k])
            assert len(set(t)) >= MIN_POOL, (p["id"], k, len(set(t)))
            plain = [x for x in p["templates"][k] if isinstance(x, str)]
            assert len(plain) >= 8, (p["id"], k)  # 无条件句够多，才不会因上下文不匹配而反复落到同一句
            for x in t:
                assert not re.search(r"\d{6,}", x) and "诈骗" not in x, x


def test_pools_on_stall_rotation_chain():
    for k in POOLS + ("task_stall", "campus_stall"):
        assert k in Session.STALL_FAMILY


def test_exhausted_pool_rotates_instead_of_repeating():
    s = Session("loan", "li", rng=lambda: 0.0, now=lambda: 0)
    n = len([x for x in s.persona["templates"]["secrecy"] if isinstance(x, str)])
    seen = [s.pick(s.fresh_intent("secrecy"), "别告诉家人") for _ in range(n + 4)]
    assert len(seen) == len(set(seen))


def test_recent_dedup_window():
    s = Session("loan", "lin", rng=lambda: 0.0, now=lambda: 0)
    out = []
    for _ in range(30):
        out.append(s.pick("secrecy"))
        assert out[-1] not in out[-1 - Session.RECENT_N:-1]


def test_sim_metrics_thresholds():
    r = sim.run(10, ("rule",))["byPolicy"]["rule"]
    assert r["suspiciousQuit"] <= 0.05
    assert r["repeatRate"] <= 0.01
    assert r["avgTurns"] >= 15.9  # 14b7037 基线
    assert r["extractRate"] >= 0.99
    assert r["leakRate"] == 0
