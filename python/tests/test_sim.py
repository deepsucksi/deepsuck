from deepsuck import sim


def test_sim_deterministic_and_rule_beats_baselines():
    a = sim.run(3, ("rule", "parrot"))
    b = sim.run(3, ("rule", "parrot"))
    assert a == b
    r, p = a["byPolicy"]["rule"], a["byPolicy"]["parrot"]
    assert r["avgTurns"] > p["avgTurns"]
    assert r["leakRate"] == 0
    assert r["extractRate"] > 0.95
    assert r["repeatRate"] < 0.05
