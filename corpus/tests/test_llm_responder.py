"""#194：llm_scammer --responder llm（大模型扮人设）。只用假 LLM，不联网。"""
import importlib.util
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("llm_scammer", "eval/llm_scammer.py")
LP = M.load_persona()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


class FakeLLM:
    """同一个假客户端同时扮骗子（带 response_format）和人设（不带）。骗子第 2 轮报卡号，第 hang_at 轮挂断；
    人设按 replies 轮流说（含要被过滤掉的“已经转了”和长数字）。"""

    def __init__(self, replies=None, hang_at=5):
        self.scam_calls, self.persona_calls = [], []
        self.replies = replies or ["我已经转过去了，你看收到没？", "卡号6222021234567890123对吧", "哎…你说慢点，我找找眼镜"]
        self.hang_at = hang_at

    def chat(self, messages, **params):
        usage = {"prompt_tokens": 200, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 120}}
        if "response_format" in params:
            self.scam_calls.append((messages, params))
            k = sum(m["role"] == "assistant" for m in messages) + 1
            card = re.search(r"银行卡：([0-9 ]+)", messages[0]["content"])
            if k >= self.hang_at:
                d = {"say": "算了", "action": "hangup", "hangup_type": "bot", "category": "repetition",
                     "evidence": messages[-1]["content"][:10], "reason": "像机器人", "suspicion": 9, "probe": 0, "strikes": 3}
            elif k == 2 and card:
                d = {"say": f"钱转到 {card.group(1).strip()}，收款人写对", "action": "continue", "suspicion": 2}
            else:
                d = {"say": f"我是公安局的，第{k}次通知你配合调查", "action": "continue", "suspicion": 3}
            return {"content": json.dumps(d, ensure_ascii=False), "usage": usage, "model": "fake"}
        self.persona_calls.append((messages, params))
        return {"content": self.replies[(len(self.persona_calls) - 1) % len(self.replies)], "usage": usage, "model": "fake"}


def _run(tmp_path, fake, **kw):
    kw.setdefault("scenarios", ["police", "refund"])
    kw.setdefault("personas", ["wang", "chen"])
    return M.run(client_factory=lambda: fake, cache_dir=tmp_path / "cache", dry_run=False, workers=1,
                 profile="hard", responder="llm", **kw)


def test_rotate_plan_one_per_scenario():
    sc = [s["id"] for s in M.SCENARIOS]
    ps = [p["id"] for p in M.PERSONAS]
    jobs = M.plan(sc, ps, 1, "rotate")
    assert len(jobs) == 7 and [j[0] for j in jobs] == sc
    assert [j[1] for j in jobs] == [ps[i % len(ps)] for i in range(7)]
    assert M.plan(sc, ps, 2, "rotate")[7][1] == ps[1]  # 第二轮整体错开一位


def test_llm_responder_filters_and_params(tmp_path):
    fake = FakeLLM()
    res = _run(tmp_path, fake)
    assert res["config"]["pairing"] == "rotate" and res["overall"]["sessions"] == 2
    assert fake.persona_calls and fake.scam_calls
    for _, p in fake.persona_calls + fake.scam_calls:
        assert p["enable_thinking"] is False and p["model"] == M.MODEL
    for _, p in fake.persona_calls:
        assert p["temperature"] == LP.TEMPERATURE and p["max_tokens"] == LP.MAX_TOKENS and "response_format" not in p
    bots = [m for r in res["rows"] for m in r["transcript"][1:] if m["role"] == "bot"]
    assert bots and all(m["raw"] in fake.replies for m in bots)
    sent = " ".join(m["text"] for m in bots)
    assert "转过去了" not in sent and not re.search(r"[0-9]{2,}", sent)  # holdTransfer、长数字、vagueDigits 都过了
    assert res["overall"]["leakRate"] == 0
    assert res["overall"]["intelSessions"] >= 1 and res["overall"]["avgReplyChars"] > 0
    u = res["usage"]
    assert u["cached_tokens"] == 120 * u["requests"] and set(u["by"]) == {"scammer", "responder"}
    assert u["by"]["responder"]["requests"] == len(fake.persona_calls)


def test_cache_layout_fixed_prefix_and_append_only(tmp_path):
    fake = FakeLLM(hang_at=8)
    _run(tmp_path, fake, scenarios=["police"], personas=["wang"])
    calls = [m for m, _ in fake.persona_calls]
    assert len(calls) >= 3
    first = calls[0][0]
    assert first["role"] == "system" and "硬性规则：" in first["content"] and "本轮建议策略" not in first["content"]
    for msgs in calls:
        assert msgs[0] == first  # 固定行每轮逐字不变，放最前
        assert msgs[-1]["role"] == "system" and "本轮建议策略" in msgs[-1]["content"]
    for a, b in zip(calls, calls[1:]):
        assert b[:len(a) - 1] == a[:-1]  # 历史只往后追加


def test_web_layout_matches_build_messages(tmp_path):
    fake = FakeLLM(hang_at=4)
    _run(tmp_path, fake, scenarios=["police"], personas=["wang"], persona_layout="web")
    msgs = fake.persona_calls[-1][0]
    tr = [{"role": "scammer" if m["role"] == "user" else "bot", "text": m["content"]} for m in msgs[1:]]
    js = subprocess.run(["node", "-e", "const L=require('./site/assets/js/llm.js');process.stdout.write(String(L.buildMessages("
                         + json.dumps({"persona": "wang", "scenario": "police", "hint": "generic", "transcript": []})
                         + ")[0].content.split('\\n')[0]))"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert msgs[0]["role"] == "system" and msgs[0]["content"].split("\n")[0] == js
    assert sum(m["role"] == "system" for m in msgs) == 1 and tr


def test_cache_key_includes_prompt_source(tmp_path):
    src_a = LP.PromptSource(None)
    fake = FakeLLM(hang_at=4)
    _run(tmp_path, fake, scenarios=["police"], personas=["wang"], prompt_source=src_a)
    n = len(fake.persona_calls)
    again = FakeLLM(hang_at=4)
    _run(tmp_path, again, scenarios=["police"], personas=["wang"], prompt_source=src_a)
    assert n and not again.persona_calls and not again.scam_calls  # 同一来源：全命中本地缓存
    other = tmp_path / "assets"
    for sub in ("js", "core"):
        (other / sub).mkdir(parents=True)
        for p in (ROOT / "site/assets" / sub).glob("*"):
            if p.is_file():
                (other / sub / p.name).write_bytes(p.read_bytes())
    pj = other / "core/personas.json"
    pj.write_text(pj.read_text(encoding="utf-8").replace("不超过 80 字", "不超过 30 字"), encoding="utf-8")
    src_b = LP.PromptSource(assets_dir=other)
    assert src_b.key != src_a.key and LP.version_for(src_a, "cache") != LP.version_for(src_b, "cache")
    third = FakeLLM(hang_at=4)
    _run(tmp_path, third, scenarios=["police"], personas=["wang"], prompt_source=src_b)
    assert third.persona_calls  # 换了来源：不串缓存


def test_prompt_source_from_ref_does_not_touch_worktree():
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    src = LP.PromptSource("HEAD")
    assert src.key.startswith("ref:HEAD@") and (src.dir / "js/llm.js").exists() and (src.dir / "core/personas.json").exists()
    assert src.fixed_lines("wang")
    assert subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout == before
    with pytest.raises(LP.PromptSourceError):
        LP.PromptSource("--output=/tmp/x")


def test_estimate_only_cli_with_ref(tmp_path):
    out = subprocess.run([sys.executable, "eval/llm_scammer.py", "--profile", "hard", "--responder", "llm", "--seeds", "1",
                          "--persona-prompt-ref", "HEAD", "--ledger", str(tmp_path / "spend.csv")],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    e = json.loads(out)
    assert e["sessions"] == 7 and e["pairing"] == "rotate" and e["persona_prompt"]["ref"] == "HEAD"
    assert 0 < e["cost_cny_if_cached"] < e["cost_cny"] <= M.HARD_MAX_COST_CNY and e["responder_cost_cny"] > 0
    assert not (tmp_path / "spend.csv").exists()  # 估算不记账


def test_estimate_guard(tmp_path):
    kw = dict(scenarios=None, personas=None, seeds=1, cache_dir=tmp_path / "c", profile="hard", responder="llm")
    with pytest.raises(M.BudgetError):
        M.run(max_cost=0.43, **kw)
    est = M.run(max_cost=0.43, estimate_guard="cached", **kw)["estimate"]
    assert est["guard"] == "cached" and est["cost_cny_if_cached"] <= 0.43 < est["cost_cny"]


def test_transcript_redaction_llm_rows(tmp_path):
    fake = FakeLLM(replies=["收款人张伟对吧，卡号6222021234567890123"], hang_at=4)
    res = _run(tmp_path, fake, scenarios=["police"], personas=["wang"])
    t = M.redact_transcript(res["rows"][0])
    blob = json.dumps(t, ensure_ascii=False)
    planted = M.SIM.plant(M.SIM.Rand(res["rows"][0]["seed"]))
    assert planted["bank"] not in blob.replace(" ", "") and "6222021234567890123" not in blob


# ---------------------------------------------------------------- 预算：到上限立即停（审核意见）
class CostlyLLM(FakeLLM):
    """每次请求按 usage 计 0.05 元左右（6 万输入 token），并记下发请求那一刻 Meter 是否已经停止。"""

    def __init__(self, holder, **kw):
        super().__init__(hang_at=50, **kw)
        self.holder, self.sent_after_stop, self.n = holder, 0, 0

    def chat(self, messages, **params):
        m = self.holder.get("m")
        self.n += 1
        if m is not None and m.stopped:
            self.sent_after_stop += 1
        r = super().chat(messages, **params)
        r["usage"] = {"prompt_tokens": 60000, "completion_tokens": 100}
        return r


def _budget_run(tmp_path, monkeypatch, max_cost, workers=2, **kw):
    monkeypatch.setattr(M, "estimate_session", lambda *a, **k: {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
                                                                "responder_prompt_tokens": 0, "responder_completion_tokens": 0})
    holder = {}
    fake = CostlyLLM(holder)
    res = M.run(scenarios=[s["id"] for s in M.SCENARIOS], personas=None, seeds=1, client_factory=lambda: fake,
                cache_dir=tmp_path / "cache", dry_run=False, workers=workers, profile="hard", responder="llm",
                max_cost=max_cost, meter_hook=lambda m: holder.__setitem__("m", m), **kw)
    return res, fake, holder["m"]


def test_budget_stops_before_sending(tmp_path, monkeypatch):
    res, fake, m = _budget_run(tmp_path, monkeypatch, max_cost=0.3, workers=1)
    assert res["stoppedByBudget"] is True and res["stopReason"] and m.stopped
    assert fake.sent_after_stop == 0  # 停止标志置上以后，所有场都没有再发请求
    assert fake.n == m.u["requests"] and m.refused >= 1
    # 发请求前先检查（含单次预估余量）：最多只有最后一个在途请求按实际 usage 越过上限一次
    assert m.u["cost_cny"] <= 0.3 + 0.05 * 2
    assert res["unfinished"] and len(res["rows"]) + len(res["unfinished"]) == 7
    assert res["usage"]["refused_requests"] == m.refused


def test_budget_concurrent_only_inflight(tmp_path, monkeypatch):
    res, fake, m = _budget_run(tmp_path, monkeypatch, max_cost=0.3, workers=4)
    # 并发时，停止那一刻已经通过检查、正在路上的请求（至多 workers - 1 个）会返回；之后没有新请求
    assert res["stoppedByBudget"] and fake.sent_after_stop <= 3 and fake.n == m.u["requests"]
    assert m.u["cost_cny"] <= 0.3 + 0.05 * 4


def test_budget_margin_refuses_first_request(tmp_path, monkeypatch):
    res, fake, m = _budget_run(tmp_path, monkeypatch, max_cost=0.0005)
    assert fake.n == 0 and m.u["requests"] == 0  # 单次请求的预估余量就超了：一个请求都不发
    assert res["stoppedByBudget"] is True and res["rows"] == [] and len(res["unfinished"]) == 7


def test_budget_cancels_queued_sessions(tmp_path, monkeypatch):
    res, fake, m = _budget_run(tmp_path, monkeypatch, max_cost=0.12, workers=1)
    assert fake.sent_after_stop == 0 and res["stoppedByBudget"]
    assert len(res["unfinished"]) == 7 and fake.n <= 3  # 第一场里就停，排队的 6 场被取消，没有各多付一次


def test_meter_reserve_and_stop_flag():
    m = M.Meter(0.01)
    r = m.reserve(0.004)
    assert m.reserved == r
    m.add(1000, 10, 0, "scammer", r)
    assert m.reserved == 0 and not m.stopped
    with pytest.raises(M.BudgetError):
        m.reserve(0.02)
    assert m.stopped
    with pytest.raises(M.BudgetError):
        m.reserve(0.0)  # 停了以后再小的请求也不发
    assert m.refused == 2


def test_cli_partial_result_flag(tmp_path, monkeypatch):
    holder = {}
    fake = CostlyLLM(holder)
    orig = M.run
    monkeypatch.setattr(M, "estimate_session", lambda *a, **k: {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
                                                                "responder_prompt_tokens": 0, "responder_completion_tokens": 0})
    monkeypatch.setattr(M, "run", lambda *a, **k: orig(*a, **{**k, "cache_dir": tmp_path / "cache",
                                                              "meter_hook": lambda m: (holder.__setitem__("m", m), k["meter_hook"](m))}))
    monkeypatch.setattr(M.J, "default_client_factory", lambda *a, **k: (lambda: fake))
    out = tmp_path / "audit" / "eval194"
    rc = M.main(["--run", "--profile", "hard", "--responder", "llm", "--seeds", "1", "--max-cost", "0.2",
                 "--workers", "1", "--budget-tag", "t194", "--ledger", str(tmp_path / "spend.csv"), "--no-rule-baseline",
                 "--json", str(out / "a.json"), "--json-transcripts", "--transcripts", str(out / "a.jsonl"), "--md", str(out / "a.md")])
    assert rc == 2 and fake.sent_after_stop == 0
    res = json.loads((out / "a.json").read_text(encoding="utf-8"))
    assert res["stoppedByBudget"] is True and res["unfinished"]
    assert "stoppedByBudget=true" in (out / "a.md").read_text(encoding="utf-8")
    assert "去掉空白后的字数" in (out / "a.md").read_text(encoding="utf-8")
    assert "stopped:budget" in (tmp_path / "spend.csv").read_text(encoding="utf-8")
    for line in (out / "a.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        planted = M.SIM.plant(M.SIM.Rand(row["seed"]))
        assert planted["bank"] not in line.replace(" ", "")  # 对话全文 JSONL 也打码
