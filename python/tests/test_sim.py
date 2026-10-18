from deepsuck import sim


def test_sim_deterministic_and_rule_beats_baselines():
    # 手写台词（v0.5 基线）上的回归门槛保持不变
    a = sim.run(3, ("rule", "parrot"), lines="legacy")
    b = sim.run(3, ("rule", "parrot"), lines="legacy")
    assert a == b
    r, p = a["byPolicy"]["rule"], a["byPolicy"]["parrot"]
    assert r["avgTurns"] > p["avgTurns"]
    assert r["leakRate"] == 0
    assert r["extractRate"] > 0.95
    assert r["repeatRate"] < 0.05


def test_sim_corpus_lines_reproducible_with_legacy_fallback(tmp_path):
    sc = sim.load_scripts("corpus")
    assert sc["lines"] == "corpus"
    for sid, s in sc["scenarios"].items():
        assert len(s["pitch"]) == len(sim.PITCH_PHASES) and all(s["pitch"])
        for stage in s["pitch"]:
            for line in stage:
                assert not (set(sim.re.findall(r"\{(.+?)\}", line)) - sim.FILL_OK), line
    a = sim.run(2, ("rule",), lines="corpus")
    assert a == sim.run(2, ("rule",), lines="corpus")
    assert a["config"]["lines"] == "corpus"
    r = a["byPolicy"]["rule"]
    assert r["leakRate"] == 0 and r["extractRate"] > 0.95
    # 真实语料里“施压 / 保密”句更密集，人设的 secrecy、loan_stall 等模板池偏小，重复率高于手写台词（见 docs/EVAL.md 局限）
    assert r["repeatRate"] < 0.1
    # 语料文件缺失：退回手写台词
    legacy = sim.load_scripts("corpus", corpus_path=str(tmp_path / "missing.json"))
    assert "lines" not in legacy and legacy == sim.load_scripts("legacy")
    assert sim.run(2, ("rule",), lines="legacy")["config"]["lines"] == "legacy"


def test_sim_corpus_fills_placeholders_deterministically():
    sc = sim.load_scripts("corpus")
    s = sim.Scammer(sc["scenarios"]["boss"], sc["common"], sim.Rand(7))
    t = s.fill("我是{姓氏}总，{机构}的{金额}，工号{工号}，下载{APP名}")
    assert "{" not in t and t == sim.Scammer(sc["scenarios"]["boss"], sc["common"], sim.Rand(7)).fill("我是{姓氏}总，{机构}的{金额}，工号{工号}，下载{APP名}")
